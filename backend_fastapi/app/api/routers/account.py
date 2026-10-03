"""Reader account endpoints: Microsoft sign-in, username availability and the
one-time profile completion step. There are no passwords: readers sign in
with a magic link, Google or Microsoft.

Registered BEFORE the main auth router, whose catch-all ``GET /auth/{provider}``
would otherwise shadow these paths.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...core.settings import settings
from ...dependencies.auth import get_current_user
from ...models import User
from ...services import microsoft_oauth
from ...services import site_functions
from ...services.auth_service import issue_tokens_for_user
from ...utils.endpoint_limiter import async_endpoint_limiter
from ...utils.sanitizer import strip_all_html
from .auth import _set_auth_cookies

logger = structlog.get_logger("backend_fastapi.account")

router = APIRouter(prefix="/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")
RESERVED_USERNAMES = {
    "admin",
    "administrator",
    "root",
    "system",
    "support",
    "moderator",
    "mod",
    "staff",
    "owner",
    "official",
    "null",
    "undefined",
    "anonymous",
}
MIN_AGE = 13
MAX_AGE = 120
GENDERS = {"male", "female", "non-binary", "other", "prefer not to say", "not specified"}


def _clean_username(raw: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", (raw or "").strip().lower())


def _username_problem(db: Session, username: str, *, exclude_user_id: int | None) -> str | None:
    if not username:
        return "Username is required."
    if not USERNAME_RE.match(username):
        return "Username must be 3-30 characters: lowercase letters, numbers or underscores."
    if username in RESERVED_USERNAMES:
        return f'"{username}" is reserved. Please choose another.'
    query = db.query(User.id).filter(func.lower(User.username) == username)
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    if query.first() is not None:
        return (
            f'Username "{username}" is already taken. Unique names are solo '
            "identifiers across the entire website."
        )
    return None


def _parse_birth_date(raw: str) -> date:
    try:
        born = date.fromisoformat((raw or "").strip())
    except ValueError:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Birth date must be a valid date.", field="birth_date")
    today = datetime.utcnow().date()
    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if born > today or age > MAX_AGE:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Please enter your real date of birth.", field="birth_date")
    if age < MIN_AGE:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"You must be at least {MIN_AGE} years old to create an account.",
            field="birth_date",
        )
    return born


def _apply_birth_date(user: User, raw: Optional[str]) -> None:
    if not raw:
        return
    born = _parse_birth_date(raw)
    if user.birth_date and user.birth_date != born:
        # Age drives the under-18 content filter, so it is set once.
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Age is permanently locked once verified and cannot be altered.",
            field="birth_date",
        )
    user.birth_date = born


def _clean_name(raw: str) -> str:
    name = strip_all_html(raw or "").strip()
    if not name:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Please enter your display name.", field="name")
    if len(name) > 60:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Display name must be 60 characters or fewer.", field="name")
    return name


def _clean_profile_image(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = raw.strip()
    if len(value) > 500 or not (value.startswith("https://") or value.startswith("/api/")):
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Profile picture must be an https:// image URL or an uploaded image.",
            field="profile_image",
        )
    return value


def _user_payload(user: User) -> Dict[str, Any]:
    from ...schemas import UserRead

    return UserRead.model_validate(user).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Username + profile
# ---------------------------------------------------------------------------


@router.get("/check-username")
async def check_username(
    request: Request,
    username: str = Query("", max_length=64),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"check_username:{current_user.id}", limit=120, window_seconds=600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        clean = _clean_username(username)
        problem = _username_problem(db, clean, exclude_user_id=current_user.id)
        if problem:
            return {"available": False, "username": clean, "message": problem}
        return {"available": True, "username": clean, "message": f'"{clean}" is unique and available!'}

    return await run_in_db_threadpool(_work)


class CompleteProfilePayload(BaseModel):
    name: str = Field(..., max_length=200)
    username: str = Field(..., max_length=64)
    birth_date: str = Field(..., max_length=10)


@router.post("/complete-profile")
async def complete_profile(
    request: Request,
    payload: CompleteProfilePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"complete_profile:{current_user.id}", limit=30, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        name = _clean_name(payload.name)
        username = _clean_username(payload.username)
        problem = _username_problem(db, username, exclude_user_id=current_user.id)
        if problem:
            raise ApiError(ErrorCode.VALIDATION_FAILED, problem, field="username")
        _apply_birth_date(current_user, payload.birth_date)

        current_user.name = name
        current_user.username = username
        current_user.profile_completed = True
        db.commit()
        db.refresh(current_user)
        return {"success": True, "message": "Profile completed.", "user": _user_payload(current_user)}

    return await run_in_db_threadpool(_work)


class ProfileUpdatePayload(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    username: Optional[str] = Field(None, max_length=64)
    gender: Optional[str] = Field(None, max_length=32)
    birth_date: Optional[str] = Field(None, max_length=10)
    profile_image: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = Field(None, max_length=500)


@router.post("/profile")
async def update_profile(
    request: Request,
    payload: ProfileUpdatePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"update_profile:{current_user.id}", limit=60, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        if payload.name is not None:
            current_user.name = _clean_name(payload.name)
        if payload.username:
            username = _clean_username(payload.username)
            if username != (current_user.username or "").lower():
                problem = _username_problem(db, username, exclude_user_id=current_user.id)
                if problem:
                    raise ApiError(ErrorCode.VALIDATION_FAILED, problem, field="username")
                current_user.username = username
        if payload.gender is not None:
            gender = strip_all_html(payload.gender).strip()
            current_user.gender = gender if gender.lower() in GENDERS else "Not specified"
        _apply_birth_date(current_user, payload.birth_date)
        image = _clean_profile_image(payload.profile_image or payload.avatar_url)
        if image:
            current_user.profile_image = image
        db.commit()
        db.refresh(current_user)
        return {
            "success": True,
            "message": "Profile and identity updated successfully.",
            "user": _user_payload(current_user),
        }

    return await run_in_db_threadpool(_work)


# ---------------------------------------------------------------------------
# Microsoft sign-in
# ---------------------------------------------------------------------------


def _login_redirect(error_key: str) -> RedirectResponse:
    base = (settings.frontend_url or "").rstrip("/")
    response = RedirectResponse(
        f"{base}/login?{urlencode({'error': error_key})}", status_code=status.HTTP_302_FOUND
    )
    response.delete_cookie(microsoft_oauth.MICROSOFT_STATE_COOKIE)
    return response


@router.get("/microsoft")
def microsoft_login(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    if not site_functions.is_enabled(db, "sign_in_microsoft"):
        return _login_redirect("provider_disabled")
    if not microsoft_oauth.configured():
        return _login_redirect("microsoft_not_configured")

    state, verifier, challenge = microsoft_oauth.new_state_and_challenge()
    params = {
        "client_id": settings.microsoft_oauth_client_id,
        "response_type": "code",
        "redirect_uri": microsoft_oauth.redirect_uri(request),
        "response_mode": "query",
        "scope": microsoft_oauth.MICROSOFT_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    response = RedirectResponse(
        f"{microsoft_oauth.authorize_endpoint()}?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )
    response.set_cookie(
        microsoft_oauth.MICROSOFT_STATE_COOKIE,
        f"{state}.{verifier}",
        max_age=microsoft_oauth.MICROSOFT_STATE_TTL,
        httponly=True,
        secure=settings.force_https_redirects,
        samesite="lax",
    )
    return response


@router.get("/microsoft/callback", name=microsoft_oauth.MICROSOFT_CALLBACK_ROUTE_NAME)
def microsoft_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not site_functions.is_enabled(db, "sign_in_microsoft"):
        return _login_redirect("provider_disabled")
    if not microsoft_oauth.configured():
        return _login_redirect("microsoft_not_configured")
    if error or not code:
        return _login_redirect("oauth_denied" if error else "oauth_error")

    stored = request.cookies.get(microsoft_oauth.MICROSOFT_STATE_COOKIE) or ""
    expected_state, _, verifier = stored.partition(".")
    if not expected_state or not verifier or not secrets.compare_digest(expected_state, state or ""):
        return _login_redirect("oauth_error")

    try:
        user = microsoft_oauth.exchange_code_for_user(
            code, verifier, microsoft_oauth.redirect_uri(request), db
        )
    except microsoft_oauth.MicrosoftOAuthError as exc:
        return _login_redirect(str(exc) or "oauth_error")

    if not user.is_active:
        return _login_redirect("account_disabled")

    pair = issue_tokens_for_user(user, db)
    target = settings.magic_link_redirect_url or settings.frontend_url or "/"
    response = RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(microsoft_oauth.MICROSOFT_STATE_COOKIE)
    _set_auth_cookies(response, db, pair.access_token, pair.refresh_token)
    return response


__all__ = ["router"]
