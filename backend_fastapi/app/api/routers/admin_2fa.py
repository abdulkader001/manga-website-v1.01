"""Admin second factor endpoints (roadmap item 15).

These are reachable with a normal login, because they are how an admin gets
past the step-up. They are limited to admin-tier accounts.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sqlalchemy.orm import object_session

from ...core.admin_identity import admin_sign_in_in_use
from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
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


def _owner_managed(user: User) -> bool:
    return is_main_admin(user) and admin_sign_in_in_use(object_session(user))


def _managed_by_admin_sign_in(user: User) -> None:
    """The main admin's authenticator is set up only by the one-time Admin
    sign-in (e-mail + server password) or reset on the server -- never from a
    session that a stolen Google account or inbox could have produced."""

    if _owner_managed(user):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "The site owner's authenticator can only be changed on the server. "
            "Lost your phone? See the guide: reset-2fa, then a new one-time password.",
            details={"reason": "managed_by_admin_sign_in"},
        )


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
        max_age=second_factor.STEP_UP_MINUTES * 60,
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
        "required": _owner_managed(user),
        "managed_by_admin_sign_in": _owner_managed(user),
    }


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

    _managed_by_admin_sign_in(user)

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
    _managed_by_admin_sign_in(user)
    await _limit_codes(request, user)
    if not second_factor.enable(db, user, payload.code):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "That code is not valid.", field="code")
    log_admin_action(db, request, user, "ADMIN_2FA_ENABLE", "user", str(user.id), "success")
    # The admin just proved possession of the device, so start unlocked.
    _set_step_up_cookie(response, user)
    return {"enabled": True, "unlocked": True}


@router.post("/verify")
async def two_factor_verify(
    request: Request,
    response: Response,
    payload: CodePayload,
    user: User = Depends(_admin_only),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await _limit_codes(request, user)
    if not second_factor.verify_user_code(db, user, payload.code, enabled_only=True):
        log_admin_action(
            db, request, user, "ADMIN_2FA_VERIFY", "user", str(user.id), "invalid_code"
        )
        raise ApiError(ErrorCode.VALIDATION_FAILED, "That code is not valid.", field="code")
    _set_step_up_cookie(response, user)
    return {"enabled": True, "unlocked": True}


@router.post("/disable")
async def two_factor_disable(
    request: Request,
    response: Response,
    payload: CodePayload,
    user: User = Depends(_admin_only),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _managed_by_admin_sign_in(user)
    await _limit_codes(request, user)
    if not second_factor.verify_user_code(db, user, payload.code, enabled_only=True):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "That code is not valid.", field="code")
    second_factor.disable(db, user)
    log_admin_action(db, request, user, "ADMIN_2FA_DISABLE", "user", str(user.id), "success")
    response.delete_cookie(second_factor.STEP_UP_COOKIE)
    return {"enabled": False, "unlocked": False}
