"""Secret vault endpoints: the main admin's GUI for integration settings.

Access is deliberately narrower than every other admin page:

* Main admin only (``require_main_admin_user``). This is a role-tier check,
  not a catalogue permission, so no permission override or preset can ever
  extend it to a secondary admin or moderator.
* An authenticator app must be enrolled.
* Reading the listing needs the usual admin step-up; changing, removing or
  revealing a value additionally needs a vault unlock -- a fresh TOTP code
  that opens a 10-minute window bound to this admin.

Plaintext values are never written to logs or the audit trail, and the
listing only ever returns masked previews.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...core.security import _create_token, _get_algorithm, _get_secret_key
from ...core.settings import settings
from ...dependencies.auth import require_main_admin_user
from ...models import User
from ...services import admin_second_factor as second_factor
from ...services import secret_vault as vault
from ...utils.audit_logger import log_admin_action
from ...utils.client_ip import resolve_client_ip
from ...utils.endpoint_limiter import async_endpoint_limiter

router = APIRouter(prefix="/admin/vault", tags=["admin-vault"])

UNLOCK_COOKIE = "admin_vault_unlock"
UNLOCK_TOKEN_TYPE = "vault_unlock"
UNLOCK_MINUTES = 10

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class UnlockPayload(BaseModel):
    code: str = Field(..., min_length=6, max_length=12)


class ValuePayload(BaseModel):
    value: str = Field(..., max_length=vault.MAX_VALUE_LENGTH + 64)


async def require_vault_owner(
    user: User = Depends(require_main_admin_user),
) -> User:
    if not getattr(user, "totp_enabled", False):
        # FORBIDDEN rather than REVERIFICATION_REQUIRED: the frontend treats the
        # latter as "the admin step-up expired" and re-prompts every admin page.
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Set up your authenticator app before opening the secret vault.",
            details={"reason": "enrolment_required"},
        )
    return user


def _unlock_valid(request: Request, user: User) -> bool:
    token = request.cookies.get(UNLOCK_COOKIE)
    if not token:
        return False
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[_get_algorithm()])
    except JWTError:
        return False
    if payload.get("type") != UNLOCK_TOKEN_TYPE or payload.get("sub") != str(user.id):
        return False
    from ...services import token_revocation

    return not token_revocation.issued_before_cutoff(user, payload)


async def require_vault_unlocked(
    request: Request, user: User = Depends(require_vault_owner)
) -> User:
    if not _unlock_valid(request, user):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Enter your authenticator code to unlock the vault.",
            details={"reason": "vault_locked"},
        )
    return user


def _managed_key(key: str) -> str:
    if key not in vault.MANAGED_KEYS:
        raise ApiError(ErrorCode.NOT_FOUND, "That setting is not managed by the vault.")
    return key


def _vault_ready() -> None:
    try:
        vault._cipher()
    except vault.VaultUnavailable as exc:
        raise ApiError(ErrorCode.SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("")
def list_vault(
    request: Request,
    response: Response,
    user: User = Depends(require_vault_owner),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _vault_ready()
    response.headers.update(_NO_STORE)
    vault.refresh(db)
    return {
        "unlocked": _unlock_valid(request, user),
        "unlock_minutes": UNLOCK_MINUTES,
        "entries": vault.listing(db),
    }


@router.post("/unlock")
async def unlock_vault(
    request: Request,
    response: Response,
    payload: UnlockPayload,
    user: User = Depends(require_vault_owner),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    # Same budget as the step-up endpoint: a code is only six digits.
    await async_endpoint_limiter.check_limit(
        request, f"admin_vault_user:{user.id}", limit=10, window_seconds=600
    )
    await async_endpoint_limiter.check_limit(
        request, f"admin_vault_ip:{resolve_client_ip(request)}", limit=30, window_seconds=600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        if not second_factor.verify_user_code(db, user, payload.code, enabled_only=True):
            log_admin_action(db, request, user, "VAULT_UNLOCK", "vault", "-", "invalid_code")
            raise ApiError(ErrorCode.VALIDATION_FAILED, "That code is not valid.", field="code")
        response.set_cookie(
            UNLOCK_COOKIE,
            _create_token(str(user.id), UNLOCK_TOKEN_TYPE, timedelta(minutes=UNLOCK_MINUTES)),
            max_age=UNLOCK_MINUTES * 60,
            httponly=True,
            secure=settings.force_https_redirects,
            samesite="strict",
        )
        log_admin_action(db, request, user, "VAULT_UNLOCK", "vault", "-", "success")
        return {"unlocked": True, "unlock_minutes": UNLOCK_MINUTES}

    return await run_in_db_threadpool(_work)


@router.post("/lock")
def lock_vault(response: Response, _user: User = Depends(require_vault_owner)) -> Dict[str, Any]:
    response.delete_cookie(UNLOCK_COOKIE)
    return {"unlocked": False}


@router.put("/{key}")
def set_vault_value(
    key: str,
    payload: ValuePayload,
    request: Request,
    response: Response,
    user: User = Depends(require_vault_unlocked),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _managed_key(key)
    _vault_ready()
    previous_source = "vault" if vault.is_overridden(key) else "env"
    try:
        vault.store(db, key, payload.value, actor_id=user.id)
    except vault.VaultError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), field="value") from exc
    # Never the plaintext: the audit trail records that a value changed, not what it is.
    log_admin_action(
        db, request, user, "VAULT_SET", "vault", key, "success",
        previous_value=previous_source, new_value="vault",
    )
    response.headers.update(_NO_STORE)
    entry = next(e for e in vault.listing(db) if e["key"] == key)
    return {"entry": entry}


@router.delete("/{key}")
def remove_vault_value(
    key: str,
    request: Request,
    response: Response,
    user: User = Depends(require_vault_unlocked),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _managed_key(key)
    _vault_ready()
    removed = vault.remove(db, key)
    log_admin_action(
        db, request, user, "VAULT_REMOVE", "vault", key,
        "success" if removed else "not_set",
    )
    response.headers.update(_NO_STORE)
    entry = next(e for e in vault.listing(db) if e["key"] == key)
    return {"removed": removed, "entry": entry}


@router.post("/{key}/reveal")
def reveal_vault_value(
    key: str,
    request: Request,
    response: Response,
    user: User = Depends(require_vault_unlocked),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _managed_key(key)
    _vault_ready()
    value = vault.current_value(db, key)
    log_admin_action(db, request, user, "VAULT_REVEAL", "vault", key, "success")
    response.headers.update(_NO_STORE)
    return {"key": key, "value": value}


def _probe_domain(domain: str) -> Dict[str, Any]:
    """Can the world reach THIS site at ``domain``? (blocking; run in a thread)

    Resolves the name and asks https://<domain>/healthz. The request goes
    through the SSRF-safe fetcher, so a domain pointing at a private address
    is reported, not contacted.
    """

    from ...services.pinned_fetch import get_pinned_following_redirects
    from ...services.url_guard import validate_remote_image_url_resolved

    result: Dict[str, Any] = {
        "domain": domain,
        "resolves": False,
        "addresses": [],
        "https": False,
        "is_this_site": False,
        "detail": "",
    }
    error, addresses = validate_remote_image_url_resolved(f"https://{domain}/healthz")
    result["addresses"] = list(addresses or ())
    if addresses:
        result["resolves"] = True
    if error and not addresses:
        result["detail"] = (
            "The name does not point anywhere yet. Create the DNS record (A/AAAA or CNAME) at your "
            "domain registrar, then check again; it can take a few minutes."
        )
        return result
    if error:
        result["detail"] = f"Not usable: {error}"
        return result
    try:
        response = get_pinned_following_redirects(
            f"https://{domain}/healthz",
            validate_remote_image_url_resolved,
            timeout=8,
            max_redirects=2,
            max_bytes=4096,
        )
    except Exception as exc:
        result["detail"] = (
            "The name resolves, but https://%s did not answer (%s). Point it at this server and "
            "install an HTTPS certificate (GUIDE.md section 8), then check again." % (domain, type(exc).__name__)
        )
        return result
    result["https"] = True
    try:
        body = response.json()
    except ValueError:
        body = {}
    result["is_this_site"] = response.status_code == 200 and body.get("ok") is True
    result["detail"] = (
        "Ready: this domain reaches this site over HTTPS."
        if result["is_this_site"]
        else "HTTPS works, but something other than this site answered. Check which server the domain points to."
    )
    return result


@router.get("/domain")
def get_domain(
    response: Response,
    _user: User = Depends(require_vault_owner),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    _vault_ready()
    response.headers.update(_NO_STORE)
    return vault.domain_status(db)


class DomainCheckPayload(BaseModel):
    domain: str = Field(..., max_length=300)


@router.post("/domain/check")
async def check_domain(
    request: Request,
    payload: DomainCheckPayload,
    user: User = Depends(require_vault_owner),
) -> Dict[str, Any]:
    """Dry run before switching: DNS, HTTPS and 'is this our site' for a domain."""

    from starlette.concurrency import run_in_threadpool

    await async_endpoint_limiter.check_limit(
        request, f"admin_vault_domain:{user.id}", limit=20, window_seconds=600
    )
    try:
        domain = vault.normalize_domain(payload.domain)
    except vault.VaultError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), field="domain") from exc
    return await run_in_threadpool(_probe_domain, domain)


__all__ = ["router"]
