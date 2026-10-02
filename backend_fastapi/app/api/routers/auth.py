"""Authentication routes implemented purely in FastAPI."""

from __future__ import annotations

import secrets
from typing import Any, NoReturn
from urllib.parse import urlencode

import structlog

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session


from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import User
from ...services.auth_service import (
    issue_tokens_for_user,
    normalize_email,
    ensure_magic_link_user,
    create_magic_login_token,
    consume_magic_link as ctrl_consume_magic_link,
    get_session_expiry_days,
)
from ...services.oauth_service import (
    google_oauth_configured,
    resolve_google_redirect_uri,
    exchange_google_code_for_user,
    OAuthExchangeError,
    OAuthUserError,
    GOOGLE_AUTH_ENDPOINT,
    GOOGLE_OAUTH_SCOPES,
    GOOGLE_STATE_COOKIE,
    GOOGLE_STATE_TTL,
    GOOGLE_CALLBACK_ROUTE_NAME,
)
from ...schemas import RefreshRequest, TokenPair, UserRead
from ...core.api_errors import ApiError, ErrorCode
from ...core.security import (
    decode_token,
    get_access_token_expiry_minutes,
)
from ...core.settings import settings
from ...services import token_revocation
from ...utils.client_ip import resolve_client_ip
from ...utils.endpoint_limiter import async_endpoint_limiter


async def _limit_login_attempts(request: Request) -> None:
    """Per-source-IP cap on the OAuth login entry points (roadmap item 6).

    The magic-link endpoints carry their own limits; this covers Google login
    and its callbacks, which had none beyond the generic middleware limit.
    nginx applies a coarser per-IP limit in front of the same paths.
    """

    await async_endpoint_limiter.check_limit(
        request,
        f"login_source:{resolve_client_ip(request)}",
        limit=30,
        window_seconds=600,
    )


def _bearer_token(request: Request) -> str | None:
    """Return the bearer token when a non-browser client sends one."""

    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None

logger = structlog.get_logger("backend_fastapi.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


def _frontend_base_url() -> str:
    """Resolve the frontend's public origin for building absolute links.

    Mirrors the ``frontend_url`` fallback the OAuth callback already uses for
    its post-login redirect target (``auth.py`` success path below), but
    yields only the bare origin since callers here prepend their own path
    rather than using this as a final destination.
    """

    base = settings.frontend_url or ""
    return base.rstrip("/")


def _set_auth_cookies(
    response: Response, db: Session, access_token: str, refresh_token: str
) -> None:
    """Set both auth cookies with a ``Max-Age`` matching each token's real TTL.

    F-6: these used to be session cookies (no ``Max-Age``/``Expires``), so the
    browser discarded them at browser-close while the refresh token inside
    kept living for ``get_session_expiry_days(db)`` days (default 14,
    admin-configurable 1-30) -- the admin's session-length setting had no
    effect on browser-persisted sessions.
    """

    response.set_cookie(
        "access_token_cookie",
        access_token,
        max_age=get_access_token_expiry_minutes() * 60,
        httponly=True,
        secure=settings.force_https_redirects,
        samesite="lax",
    )
    response.set_cookie(
        "refresh_token_cookie",
        refresh_token,
        max_age=get_session_expiry_days(db) * 86400,
        httponly=True,
        secure=settings.force_https_redirects,
        samesite="lax",
    )


def _oauth_status_redirect(status_key: str) -> RedirectResponse:
    """Redirect back to the frontend login page with a ``?magic=`` status.

    Lets ``MagicLinkLogin.js``'s existing ``statusCopy`` banners render
    instead of a raw backend error page/JSON body.
    """

    target = f"{_frontend_base_url()}/login?{urlencode({'magic': status_key})}"
    response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(GOOGLE_STATE_COOKIE)
    return response


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkResponse(BaseModel):
    message: str
    # Populated only in non-production test mode (see core.test_mode.
    # test_mode_active) so the harness can consume the link without an email
    # round-trip. Never returned in production: the field is gated on the
    # deployment environment, not on a raw flag, so no APP_ENV=production
    # response can ever include it.
    debug_token: str | None = None


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(
    request: Request,
    response: Response,
    body: RefreshRequest | None = Body(default=None),
    db: Session = Depends(get_db),
) -> TokenPair:
    """Issue a new access/refresh token pair using a refresh token.

    F-66: the token is taken from the ``refresh_token_cookie`` when no body is
    supplied. This endpoint used to require it in the JSON body, which no
    browser could ever satisfy — the cookie is ``httponly``, so JavaScript
    cannot read it to put it there, and the client correctly posts no body.
    Every browser call therefore returned 422 and session refresh was
    impossible, silently logging users out at the access-token expiry
    regardless of the configured session length. An explicit body is still
    accepted for non-browser clients.
    """

    token_value = (body.refresh_token if body else None) or request.cookies.get(
        "refresh_token_cookie"
    )
    if not token_value:
        # An absent token is an authentication failure, not a schema violation.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )

    try:
        payload: dict[str, Any] = decode_token(token_value)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    token_type = payload.get("type")
    if token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        )

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        ) from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    # Refresh-token rotation. Each refresh consumes the token it was given and
    # issues a fresh one, so a stolen refresh token has a useful life measured
    # in one round trip rather than the full session length.
    #
    # Presenting an already-consumed refresh token therefore means either a
    # replay or that the legitimate client and an attacker both hold the same
    # token and one of them got there first. Neither is recoverable by
    # guessing which is which, so the whole account's sessions are revoked and
    # both parties have to log in again.
    if token_revocation.is_revoked(db, payload):
        token_revocation.revoke_all_for_user(db, user, reason="refresh_token_reuse")
        logger.warning(
            "refresh_token_reuse_detected",
            user_id=user.id,
            jti=payload.get("jti"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has already been used",
        )

    if token_revocation.issued_before_cutoff(user, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked"
        )

    token_revocation.revoke(db, payload, reason="rotated")

    pair = issue_tokens_for_user(user, db)

    # F-66: hand the new tokens back as cookies too. Returning them only in the
    # body is useless to a cookie-based client -- the browser would keep sending
    # the old, expired access token and nothing would actually be refreshed.
    _set_auth_cookies(response, db, pair.access_token, pair.refresh_token)

    return pair


@router.get("/me", response_model=UserRead)
def read_me(current_user: User = Depends(get_current_user)) -> UserRead:
    """Return the authenticated user's profile."""

    return current_user


@router.post("/request-magic-link", response_model=MagicLinkResponse)
async def request_magic_link(
    request: Request, payload: MagicLinkRequest, db: Session = Depends(get_db)
) -> MagicLinkResponse:
    """Create a one-time magic-link login token for ``payload.email``."""

    email = normalize_email(payload.email)
    # Two limits, because they stop different abuse. The per-email cap stops
    # one address being mail-bombed; on its own it does nothing against a
    # caller walking a list of addresses, since each one gets a fresh budget.
    # The per-source cap covers that, and the generic middleware limit (300
    # req/min) is far too generous for an endpoint that sends real email.
    client = resolve_client_ip(request)
    await async_endpoint_limiter.check_limit(
        request, f"magic_link_source:{client}", limit=10, window_seconds=3600
    )
    await async_endpoint_limiter.check_limit(
        request, f"magic_link_email:{email}", limit=3, window_seconds=3600
    )

    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        from ...core.test_mode import test_mode_active

        # Test-only convenience: return/consume the token without an email round
        # trip. Gated on the deployment env, never on the raw flag — in production
        # this is always False, so no token ever leaves in the response body.
        testing = test_mode_active()

        # Disposable-email rule (SRS 1D.2 / 1D.1A.5): the check runs BEFORE anything
        # is sent, and never as a bypass. A blocked domain receives no link and the
        # SAME non-enumerating confirmation screen — no account is created.
        # The owner's first sign-in: while the one-time Admin sign-in is open
        # (set up in .env and not yet used), the configured owner e-mail is
        # sent on to /admin-login instead of getting a link. No link is e-mailed
        # and no account is made. Once the password is used this never matches,
        # so the page can't be found again from here.
        from ...core.admin_identity import is_configured_main_admin_email
        from .admin_login import setup_page_open

        if setup_page_open(db) and is_configured_main_admin_email(email):
            return MagicLinkResponse(message="admin_setup", debug_token=None)

        from ...services.disposable_email import is_disposable_domain

        if is_disposable_domain(email):
            logger.info("magic_link_blocked_disposable_domain")
            return MagicLinkResponse(message="magic_link_sent", debug_token=None)

        from ...services.auth_service import get_user_by_email
        from ...services.site_content_service import registration_open

        if not registration_open(db) and get_user_by_email(db, email) is None:
            # Registration is closed: no account is created and no link is sent,
            # behind the same non-enumerating confirmation.
            logger.info("magic_link_blocked_registration_closed")
            return MagicLinkResponse(message="magic_link_sent", debug_token=None)

        user = ensure_magic_link_user(db, email)
        _token_record, magic_token = create_magic_login_token(db, user)

        from ...tasks.email_tasks import send_magic_link_email

        if not testing:
            magic_link = f"{_frontend_base_url()}/magic-link/{magic_token}"
            send_magic_link_email.delay(email=email, magic_link=magic_link)

        return MagicLinkResponse(
            message="magic_link_sent",
            debug_token=magic_token if testing else None,
        )

    return await run_in_db_threadpool(_work)


@router.post("/magic/request", response_model=MagicLinkResponse)
async def request_magic_link_v2(
    request: Request, payload: MagicLinkRequest, db: Session = Depends(get_db)
) -> MagicLinkResponse:
    """Compatibility alias mirroring ``/request-magic-link``."""

    return await request_magic_link(request, payload, db)


def _raise_magic_link_error(exc: HTTPException) -> NoReturn:
    """Translate the generic ``HTTPException`` a failed redemption raises into
    the matching ``MAGIC_LINK_*`` error code (#6).

    ``consume_magic_link``/``_redeem_login_token`` only ever distinguish three
    outcomes today -- not found/malformed, already used (including the
    concurrent-redemption race), and expired -- so those are the only codes
    wired here from real detail strings. There is no device-fingerprint check
    anywhere in the magic-link flow, so ``MAGIC_LINK_DEVICE_MISMATCH`` has no
    trigger site to wire up; inventing one would be a behavior change beyond
    this fix's scope.
    """

    detail = str(exc.detail)
    lowered = detail.lower()
    if "expired" in lowered:
        raise ApiError(ErrorCode.MAGIC_LINK_EXPIRED, detail) from exc
    if "already been used" in lowered:
        raise ApiError(ErrorCode.MAGIC_LINK_ALREADY_USED, detail) from exc
    raise ApiError(ErrorCode.MAGIC_LINK_INVALID, detail) from exc


@router.get("/magic-link/{token}")
async def consume_magic_link(
    request: Request, token: str, db: Session = Depends(get_db)
) -> JSONResponse:
    """Redeem a magic-link token and return access credentials."""

    # Redemption presents a credential, so it is worth a specific budget:
    # tokens are random and stored only as hashes, which makes guessing
    # impractical rather than impossible, and an unbounded guess rate is the
    # one thing that would make it practical.
    await async_endpoint_limiter.check_limit(
        request,
        f"magic_link_redeem:{resolve_client_ip(request)}",
        limit=20,
        window_seconds=3600,
    )

    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        try:
            payload = ctrl_consume_magic_link(db, token)
        except HTTPException as exc:
            _raise_magic_link_error(exc)
        response = JSONResponse(payload)
        _set_auth_cookies(response, db, payload["access_token"], payload["refresh_token"])
        return response

    return await run_in_db_threadpool(_work)


@router.get("/magic/verify")
async def verify_magic_link(
    request: Request, token: str = Query(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Verify a magic-link token (without issuing cookies)."""

    await async_endpoint_limiter.check_limit(
        request,
        f"magic_link_redeem:{resolve_client_ip(request)}",
        limit=20,
        window_seconds=3600,
    )

    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        try:
            return ctrl_consume_magic_link(db, token)
        except HTTPException as exc:
            _raise_magic_link_error(exc)

    return await run_in_db_threadpool(_work)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    all_sessions: bool = Query(
        default=False,
        alias="all",
        description="Sign out of every device, not just this one.",
    ),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """End the session: revoke its tokens server-side, then clear the cookies.

    Clearing the cookies alone was cosmetic. The tokens are stateless JWTs, so
    a refresh token captured off the wire or left in a stolen browser profile
    stayed valid for the whole configured session length (up to 30 days) after
    the user pressed "log out". Both tokens are now denylisted by ``jti``.

    ``?all=true`` additionally sets the account's sign-out-everywhere cutoff,
    which invalidates every other outstanding token for that user.
    """

    revoked_any = False
    for cookie_name, header_token in (
        ("access_token_cookie", _bearer_token(request)),
        ("refresh_token_cookie", None),
    ):
        raw = request.cookies.get(cookie_name) or header_token
        if not raw:
            continue
        try:
            payload = decode_token(raw)
        except JWTError:
            # Already expired or malformed: nothing left to revoke.
            continue
        revoked_any = token_revocation.revoke(db, payload, reason="logout") or revoked_any

        if all_sessions:
            subject = payload.get("sub")
            try:
                user = db.get(User, int(subject)) if subject is not None else None
            except (TypeError, ValueError):
                user = None
            if user is not None:
                token_revocation.revoke_all_for_user(db, user, reason="logout_all")

    response.delete_cookie("access_token_cookie")
    response.delete_cookie("refresh_token_cookie")
    return {"message": "logged_out_everywhere" if all_sessions else "logged_out"}


@router.get("/options")
def auth_options() -> dict[str, Any]:
    """Return authentication capability metadata for the frontend."""

    providers = ["magic_link"]
    response: dict[str, Any] = {
        "providers": providers,
        "magic_link": {
            "enabled": True,
            "request_endpoint": "/api/auth/magic/request",
            "verify_endpoint": "/api/auth/magic/verify",
        },
    }

    if google_oauth_configured():
        providers.append("google")
        response["google"] = {
            "enabled": True,
            "login_endpoint": "/api/auth/google",
            "callback_endpoint": "/api/auth/google/callback",
        }

    return response


@router.get("/google", dependencies=[Depends(_limit_login_attempts)])
def google_login(request: Request) -> RedirectResponse:
    """Redirect the user to Google's OAuth 2.0 authorisation endpoint."""

    if not google_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="google_oauth_not_configured",
        )

    redirect_uri = resolve_google_redirect_uri(request)
    state = secrets.token_urlsafe(32)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_OAUTH_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    url = f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        GOOGLE_STATE_COOKIE,
        state,
        max_age=GOOGLE_STATE_TTL,
        httponly=True,
        secure=settings.force_https_redirects,
        samesite="lax",
    )
    return response


def _handle_google_callback(
    request: Request,
    *,
    code: str | None,
    state: str | None,
    error: str | None,
    db: Session,
) -> RedirectResponse:
    """Shared implementation for handling Google OAuth callbacks.

    Every failure branch redirects back to the frontend login page with a
    ``?magic=<status>`` key (see ``_oauth_status_redirect``) instead of
    raising a raw HTTPException, so the browser — which was navigated here
    directly by Google, not by a frontend fetch call — always lands
    somewhere the existing ``statusCopy`` error UI can render.
    """

    if not google_oauth_configured():
        return _oauth_status_redirect("provider_disabled")

    if error or not code:
        # Google omits `code` and sets `error` (typically `access_denied`)
        # when the user declines consent; a missing code with no error is an
        # unexpected/malformed callback.
        return _oauth_status_redirect("oauth_denied" if error else "oauth_error")

    expected_state = request.cookies.get(GOOGLE_STATE_COOKIE)
    if not expected_state or not secrets.compare_digest(expected_state, state or ""):
        return _oauth_status_redirect("oauth_error")

    redirect_uri = resolve_google_redirect_uri(request)

    try:
        user = exchange_google_code_for_user(code, redirect_uri, db)
    except (OAuthUserError, OAuthExchangeError):
        return _oauth_status_redirect("oauth_error")

    pair = issue_tokens_for_user(user, db)

    target = settings.magic_link_redirect_url or settings.frontend_url or "/"

    redirect = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(GOOGLE_STATE_COOKIE)
    _set_auth_cookies(redirect, db, pair.access_token, pair.refresh_token)

    return redirect


@router.get(
    "/google/callback",
    name=GOOGLE_CALLBACK_ROUTE_NAME,
    dependencies=[Depends(_limit_login_attempts)],
)
def google_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle the OAuth callback from Google and establish a session."""

    return _handle_google_callback(request, code=code, state=state, error=error, db=db)


@router.get(
    "/callback",
    name="google_callback_legacy",
    dependencies=[Depends(_limit_login_attempts)],
)
def google_callback_legacy(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Backward compatible Google OAuth callback endpoint."""

    return _handle_google_callback(request, code=code, state=state, error=error, db=db)


@router.get("/{provider}")
def login_provider(provider: str) -> None:
    """Handle provider logins where native support is unavailable."""

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"provider_{provider.lower()}_unsupported",
    )


__all__ = ["router"]
