"""Admin sign-in without Google, Microsoft or e-mail.

The main admin proves who they are with three things, none of which is an
inbox or a Google account:

1. the e-mail matching ``MAIN_ADMIN_EMAIL_HASH`` (in the server's ``.env``),
2. the ONE-TIME password matching ``MAIN_ADMIN_PASSWORD_HASH`` (also only in
   ``.env``); it is void after it signs the admin in once,
3. a code from their authenticator app. On the very first sign-in the app is
   enrolled right here, in the same flow, before any session is issued.

Someone who steals the admin's Gmail can sign in as a reader at most: admin
features ask for the authenticator code, and the authenticator can only be
set up or reset through this flow or on the server.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.admin_identity import (
    admin_password_configured,
    get_main_admin_password_hash,
    is_configured_main_admin_email,
    verify_main_admin_password,
)
from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...models import SystemSettings, User, UserRole
from ...services import admin_second_factor as second_factor
from ...services.system_settings_service import get_or_create_system_settings
from ...services.auth_service import (
    ensure_magic_link_user,
    issue_tokens_for_user,
    normalize_email,
)
from ...utils.audit_logger import log_admin_action
from ...utils.client_ip import resolve_client_ip
from ...utils.endpoint_limiter import async_endpoint_limiter
from .admin_2fa import _set_step_up_cookie
from .auth import _set_auth_cookies

router = APIRouter(prefix="/auth/admin", tags=["auth"])

_WRONG = "Email, password or code is not right."
_USED = (
    "This one-time admin password has already been used. Sign in with Google, "
    "Microsoft or a magic link; admin pages ask for your authenticator code. "
    "Locked out? Make a new one-time password on the server: cli_bootstrap admin-hashes."
)


def _fingerprint() -> Optional[str]:
    value = get_main_admin_password_hash()
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None


def _password_used(db: Session) -> bool:
    row = get_or_create_system_settings(db)
    fp = _fingerprint()
    return bool(fp) and row.admin_setup_password_used == fp


def _burn_password(db: Session) -> bool:
    """Mark the current password used, atomically. False if it already was."""

    row = get_or_create_system_settings(db)
    fp = _fingerprint()
    updated = (
        db.query(SystemSettings)
        .filter(
            SystemSettings.id == row.id,
            (SystemSettings.admin_setup_password_used.is_(None))
            | (SystemSettings.admin_setup_password_used != fp),
        )
        .update({SystemSettings.admin_setup_password_used: fp}, synchronize_session=False)
    )
    db.commit()
    return bool(updated)


class AdminLoginPayload(BaseModel):
    email: str = Field(..., max_length=320)
    password: str = Field(..., max_length=1024)
    code: Optional[str] = Field(default=None, max_length=12)


@router.get("/status")
def admin_login_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Whether a one-time admin password is set up and still unused."""

    configured = admin_password_configured()
    used = configured and _password_used(db)
    return {"enabled": configured and not used, "used": used}


def _promote(user: User) -> bool:
    changed = False
    for field, value in (
        ("role", UserRole.PERMANENT),
        ("permanent", True),
        ("is_main_admin", True),
        ("is_secondary_admin", True),
    ):
        if getattr(user, field, None) != value:
            setattr(user, field, value)
            changed = True
    return changed


@router.post("/login")
async def admin_login(
    request: Request,
    response: Response,
    payload: AdminLoginPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    if not admin_password_configured():
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Admin sign-in is not set up on this server (MAIN_ADMIN_PASSWORD_HASH).",
        )
    client = resolve_client_ip(request)
    await async_endpoint_limiter.check_limit(
        request, f"admin_login_ip:{client}", limit=10, window_seconds=900
    )
    await async_endpoint_limiter.check_limit(
        request, "admin_login_all", limit=60, window_seconds=3600
    )

    # Both checks always run, so a wrong e-mail and a wrong password take the
    # same time and get the same answer.
    email_ok = is_configured_main_admin_email(payload.email)
    password_ok = verify_main_admin_password(payload.password)
    if not (email_ok and password_ok):
        raise ApiError(ErrorCode.UNAUTHENTICATED, _WRONG)
    # Single use: once it has signed the admin in, this password is void.
    if _password_used(db):
        raise ApiError(ErrorCode.UNAUTHENTICATED, _USED, details={"reason": "password_used"})

    user = ensure_magic_link_user(db, normalize_email(payload.email))
    if not getattr(user, "is_active", True):
        raise ApiError(ErrorCode.FORBIDDEN, "This account is not active.")

    code = (payload.code or "").strip()
    account = user.username or user.name or "admin"
    if user.totp_enabled:
        if not code:
            return {"step": "code"}
        await async_endpoint_limiter.check_limit(
            request, f"admin_2fa_user:{user.id}", limit=10, window_seconds=600
        )
        if not second_factor.verify_user_code(db, user, code, enabled_only=True):
            raise ApiError(ErrorCode.UNAUTHENTICATED, _WRONG, field="code")
    else:
        if not code:
            # First sign-in: enrol the authenticator before any session exists.
            secret = second_factor.start_enrolment(db, user)
            return {
                "step": "enrol",
                "secret": secret,
                "otpauth_uri": second_factor.provisioning_uri(secret, account),
            }
        await async_endpoint_limiter.check_limit(
            request, f"admin_2fa_user:{user.id}", limit=10, window_seconds=600
        )
        if not second_factor.enable(db, user, code):
            raise ApiError(ErrorCode.UNAUTHENTICATED, _WRONG, field="code")

    if not _burn_password(db):  # lost a race with another sign-in
        raise ApiError(ErrorCode.UNAUTHENTICATED, _USED, details={"reason": "password_used"})
    if _promote(user):
        db.commit()
    db.refresh(user)
    log_admin_action(db, request, user, "ADMIN_SIGN_IN", "user", str(user.id), "success")

    pair = issue_tokens_for_user(user, db)
    _set_auth_cookies(response, db, pair.access_token, pair.refresh_token)
    _set_step_up_cookie(response, user)
    return {"step": "done"}


__all__ = ["router"]
