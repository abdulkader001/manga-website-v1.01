"""Admin second factor endpoints (roadmap item 15).

These are reachable with a normal login, because they are how an admin gets
past the step-up. They are limited to admin-tier accounts.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response
from jose import JWTError
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.admin_identity import owner_sign_in_in_use
from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...core.security import decode_token
from ...core.settings import settings
from ...dependencies.auth import (
    get_current_user,
    is_main_admin,
    is_secondary_or_higher,
)
from ...models import User
from ...services import admin_second_factor as second_factor
from ...utils.audit_logger import log_admin_action
from ...utils.client_ip import resolve_client_ip
from ...utils.endpoint_limiter import async_endpoint_limiter

router = APIRouter(prefix="/admin/2fa", tags=["admin-2fa"])


class CodePayload(BaseModel):
    code: str = Field(..., min_length=6, max_length=12)


async def _admin_only(current_user: User = Depends(get_current_user)) -> User:
    if not is_secondary_or_higher(current_user):
        raise ApiError(ErrorCode.FORBIDDEN, "Admin privileges required")
    return current_user


def _owner_must_enrol(user: User) -> bool:
    """The owner always needs an authenticator once the owner e-mail is set up."""

    return is_main_admin(user) and owner_sign_in_in_use()


async def _limit_codes(request: Request, user: User) -> None:
    """A code is only six digits, so cap guesses per account and per address."""

    await async_endpoint_limiter.check_limit(
        request, f"admin_2fa_user:{user.id}", limit=10, window_seconds=600
    )
    await async_endpoint_limiter.check_limit(
        request,
        f"admin_2fa_ip:{resolve_client_ip(request)}",
        limit=30,
        window_seconds=600,
    )


def _set_step_up_cookie(response: Response, user: User) -> None:
    response.set_cookie(
        second_factor.STEP_UP_COOKIE,
        second_factor.create_step_up_token(user),
        max_age=second_factor.step_up_seconds(),
        httponly=True,
        secure=settings.force_https_redirects,
        samesite="lax",
    )


def _status(request: Request, user: User) -> Dict[str, Any]:
    enabled = bool(user.totp_enabled)
    unlocked = enabled and second_factor.step_up_valid(
        user, request.cookies.get(second_factor.STEP_UP_COOKIE)
    )
    return {
        "enabled": enabled,
        "unlocked": bool(unlocked),
        "required": _owner_must_enrol(user),
        "valid_hours": second_factor.step_up_hours(),
    }


def _asset_user(request: Request, db: Session) -> User | None:
    """The admin-tier account behind this browser's sign-in cookies, if any.

    The access cookie lasts an hour, so an admin who comes back later would get
    a broken admin page before the app has had a chance to refresh it. A live
    refresh cookie therefore counts too; it is only read here, never rotated.
    """

    from ...services import token_revocation

    for cookie, kind in (("access_token_cookie", "access"), ("refresh_token_cookie", "refresh")):
        token = request.cookies.get(cookie)
        if not token:
            continue
        try:
            payload = decode_token(token)
            user_id = int(payload.get("sub"))
        except (JWTError, TypeError, ValueError):
            continue
        if payload.get("type") != kind:
            continue
        user = db.get(User, user_id)
        if user is None or not getattr(user, "is_active", True):
            continue
        if token_revocation.issued_before_cutoff(user, payload) or token_revocation.is_revoked(db, payload):
            continue
        return user
    return None


@router.get("/asset-access", include_in_schema=False)
def admin_asset_access(request: Request, db: Session = Depends(get_db)) -> Response:
    """nginx asks this before it hands out the admin area's script files.

    Visitors never download the admin screens' code: ``/assets/admin/*`` is
    served only when this answers 204 (``deployment/nginx/site.conf``). The
    real protection is still every admin API route's own check.
    """

    user = _asset_user(request, db)
    if user is None:
        return Response(status_code=401, headers={"Cache-Control": "no-store"})
    suspended = getattr(user, "powers_suspended", False) and not is_main_admin(user)
    if not is_secondary_or_higher(user) or suspended:
        return Response(status_code=403, headers={"Cache-Control": "no-store"})
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/status")
def two_factor_status(
    request: Request, user: User = Depends(_admin_only)
) -> Dict[str, Any]:
    return _status(request, user)


@router.post("/setup")
def two_factor_setup(
    user: User = Depends(_admin_only), db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Create a secret to scan into an authenticator app (not active yet)."""

    if user.totp_enabled:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "A second factor is already active. Disable it first to set up a new one.",
        )
    secret = second_factor.start_enrolment(db, user)
    account = user.username or user.name or f"admin-{user.id}"
    return {
        "secret": secret,
        "otpauth_uri": second_factor.provisioning_uri(secret, account),
    }


@router.post("/enable")
async def two_factor_enable(
    request: Request,
    response: Response,
    payload: CodePayload,
    user: User = Depends(_admin_only),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await _limit_codes(request, user)
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        if not second_factor.enable(db, user, payload.code):
            raise ApiError(ErrorCode.VALIDATION_FAILED, "That code is not valid.", field="code")
        log_admin_action(db, request, user, "ADMIN_2FA_ENABLE", "user", str(user.id), "success")
        # The admin just proved possession of the device, so start unlocked.
        _set_step_up_cookie(response, user)
        return {"enabled": True, "unlocked": True}

    return await run_in_db_threadpool(_work)


@router.post("/verify")
async def two_factor_verify(
    request: Request,
    response: Response,
    payload: CodePayload,
    user: User = Depends(_admin_only),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await _limit_codes(request, user)
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        if not second_factor.verify_user_code(db, user, payload.code, enabled_only=True):
            log_admin_action(
                db, request, user, "ADMIN_2FA_VERIFY", "user", str(user.id), "invalid_code"
            )
            raise ApiError(ErrorCode.VALIDATION_FAILED, "That code is not valid.", field="code")
        _set_step_up_cookie(response, user)
        return {"enabled": True, "unlocked": True}

    return await run_in_db_threadpool(_work)


@router.post("/disable")
async def two_factor_disable(
    request: Request,
    response: Response,
    payload: CodePayload,
    user: User = Depends(_admin_only),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await _limit_codes(request, user)
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        if not second_factor.verify_user_code(db, user, payload.code, enabled_only=True):
            raise ApiError(ErrorCode.VALIDATION_FAILED, "That code is not valid.", field="code")
        second_factor.disable(db, user)
        log_admin_action(db, request, user, "ADMIN_2FA_DISABLE", "user", str(user.id), "success")
        response.delete_cookie(second_factor.STEP_UP_COOKIE)
        return {"enabled": False, "unlocked": False}

    return await run_in_db_threadpool(_work)
