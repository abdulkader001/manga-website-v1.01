"""Authentication dependencies for FastAPI routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..models import User, UserRole
from ..core.security import decode_token
from ..core.api_errors import ApiError, ErrorCode

_bearer_scheme = HTTPBearer(auto_error=False)

# Auth cookie set by the magic-link / OAuth flows. C1: the frontend authenticates
# via this httponly cookie, so it must be accepted here in addition to the bearer
# header (which remains the contract for API clients and tests). Cookie-based
# state-changing requests are protected by the double-submit CSRF middleware.
ACCESS_TOKEN_COOKIE = "access_token_cookie"


def _extract_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    """Return the auth token from the bearer header, falling back to the cookie."""

    if credentials is not None:
        return credentials.credentials
    return request.cookies.get(ACCESS_TOKEN_COOKIE)


def release_connection(db: Session) -> None:
    """Hand the session's pooled connection back once the guard has read.

    The request keeps the same session (and the user object, since sessions
    don't expire on commit) and checks a connection out again only if the
    route queries. Without this every signed-in request held a connection for
    its whole life while the route opened more, which ran the pool dry under a
    burst of readers.
    """

    if db.in_transaction() and not (db.new or db.dirty or db.deleted):
        db.commit()


def _resolve_user(
    token: str | None,
    db: Session,
    *,
    allow_anonymous: bool = False,
) -> User | None:
    """Return the authenticated user or ``None`` when anonymous access is permitted."""

    if not token:
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    try:
        payload = decode_token(token)
    except JWTError:
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    token_type = payload.get("type")
    if token_type != "access":
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type"
        )

    subject = payload.get("sub")
    if subject is None:
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        )

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        ) from None

    user = db.get(User, user_id)
    if user is None:
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    # A suspended/banned/deleted account is inactive and can no longer
    # authenticate (SRS 1E.6.1). Deactivating an account therefore also
    # effectively revokes its sessions on the next request (SRS 1E.6.2).
    if not getattr(user, "is_active", True):
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is not active"
        )

    # Server-side revocation. A signed JWT is otherwise valid until it expires
    # no matter what the server does, so without these two checks logout and
    # "sign out everywhere" cannot actually end a session.
    from ..services import token_revocation

    if token_revocation.issued_before_cutoff(user, payload) or token_revocation.is_revoked(
        db, payload
    ):
        if allow_anonymous:
            return None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked"
        )

    release_connection(db)
    return user


# The guards below that read the database are plain ``def``: FastAPI runs them
# in its thread pool. As ``async def`` their queries ran on the event loop, so
# one wait for a pooled connection froze every request in the worker.
def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Return the user from the bearer header or the auth cookie."""

    token = _extract_token(request, credentials)
    user = _resolve_user(token, db, allow_anonymous=False)
    assert user is not None  # Satisfy type-checkers; anonymous not allowed.
    return user


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """Return the current user if authenticated; otherwise ``None``."""

    token = _extract_token(request, credentials)
    return _resolve_user(token, db, allow_anonymous=True)


async def require_processing_user(
    current_user: User | None = Depends(get_optional_user),
) -> User:
    """Require an authenticated account for OCR/translation/AI processing.

    SRS 1D.3.2/1D.3.4: browsing and reading never require login, but *any*
    processing — including platform-default providers — always does. There is no
    anonymous quota. The check is server-side, on the processing endpoint, so a
    guest calling the API directly is rejected regardless of the UI.
    """

    if current_user is None:
        raise ApiError(
            ErrorCode.LOGIN_REQUIRED_FOR_PROCESSING,
            "Sign in to use OCR, translation, or AI processing. "
            "Browsing and reading do not require an account.",
        )
    return current_user


def is_main_admin(user: User) -> bool:
    """Return ``True`` if the user is the owner (main/permanent admin tier).

    F-4/F-5: a thin comparison against ``core.permissions.effective_role``,
    the single canonical resolver that folds ``permanent``/``is_main_admin``/
    ``is_secondary_admin`` and ``role`` into one answer -- kept as a
    self-contained predicate (rather than three separate reimplementations)
    so ``has_permission`` and every role-tier gate agree on who is privileged.
    Public (not ``_``-prefixed) so other modules needing the same
    main-admin-or-not distinction -- e.g. deciding whether to mask a
    plaintext email in a response body, not just whether to allow the
    request at all -- reuse this instead of writing their own check.
    """

    if not user:
        return False
    from ..core.permissions import effective_role

    return effective_role(user) in {UserRole.ADMIN, UserRole.PERMANENT}


def is_secondary_or_higher(user: User) -> bool:
    """Return ``True`` for sub-admins or higher: sub-admin, Admin, owner (see :func:`is_main_admin`)."""

    if not user:
        return False
    from ..core.permissions import effective_role

    return effective_role(user) in {
        UserRole.SECONDARY,
        UserRole.CO_ADMIN,
        UserRole.ADMIN,
        UserRole.PERMANENT,
    }


def enforce_admin_second_factor(request: Request, user: User) -> None:
    """Roadmap item 15: admins with a second factor also need a step-up.

    Applies to admin-tier accounts only. With a second factor enrolled, admin
    routes need the short-lived step-up cookie (see ``POST /admin/2fa/verify``).
    A main admin who has no authenticator is held back until they enrol one.
    """

    if not is_secondary_or_higher(user):
        return

    from ..services import admin_second_factor as second_factor

    if getattr(user, "totp_enabled", False):
        token = request.cookies.get(second_factor.STEP_UP_COOKIE)
        if not second_factor.step_up_valid(user, token):
            raise ApiError(
                ErrorCode.REVERIFICATION_REQUIRED,
                "Enter your authenticator code to continue.",
                details={"reason": "step_up_required"},
            )
        return

    # The owner always needs the authenticator once the owner e-mail is set up.
    # Their first Google sign-in is enough to enrol it, and until they have,
    # every admin feature stays shut.
    from ..core.admin_identity import owner_sign_in_in_use

    if is_main_admin(user) and owner_sign_in_in_use():
        raise ApiError(
            ErrorCode.REVERIFICATION_REQUIRED,
            "Set up your authenticator app before using admin features.",
            details={"reason": "enrolment_required"},
        )


def require_permission(permission: str):
    """Dependency factory enforcing an effective permission (SRS 1F.10).

    Resolution is server-side on every request (never-grantable -> override ->
    role default). Because it reads live from the DB, a revoked permission takes
    effect on the very next request, not at next login (1F.10 cache rule is
    satisfied trivially — there is no stale cache to invalidate).
    """

    def _dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        from ..services.permissions_service import has_permission

        enforce_admin_second_factor(request, current_user)

        allowed = has_permission(db, current_user, permission)
        release_connection(db)
        if not allowed:
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "You do not have permission to perform this action.",
                details={"permission": permission},
            )
        return current_user

    _dependency.__name__ = f"require_permission_{permission}"
    _dependency.permission = permission  # type: ignore[attr-defined]
    return _dependency


async def require_admin_user(
    request: Request, current_user: User = Depends(get_current_user)
) -> User:
    """Ensure the requester is at least a secondary admin."""

    if not is_secondary_or_higher(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    if getattr(current_user, "powers_suspended", False) and not is_main_admin(current_user):
        # The owner switched all this person's powers off: they keep the seat,
        # but nothing in the admin area answers them.
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "The site owner has switched your admin powers off.",
            details={"reason": "powers_suspended"},
        )
    enforce_admin_second_factor(request, current_user)
    return current_user


async def require_main_admin_user(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """Ensure the requester has full (main/permanent) admin rights."""

    if not is_main_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Main admin privileges required",
        )
    enforce_admin_second_factor(request, current_user)
    return current_user
