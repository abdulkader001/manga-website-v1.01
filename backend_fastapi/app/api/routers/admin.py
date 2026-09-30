"""Administrative routes for managing manga content, users, and tasks."""

from __future__ import annotations

import structlog
import math
from datetime import datetime
from typing import Any, Dict, Iterator, Optional, Sequence, List
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...schemas.admin import (
    AdminUsersResponse,
    RoleToggleResponse,
    AdminActionResponse,
    AdminAuditLogEntry,
    AdminAuditLogPage,
    AdminScrapingJobBase,
    AdminTokenBase,
    RescrapeResponse,
    AdminDomainResponse,
    AdminDomainDeleteResponse,
    AdsConfigPayload,
    AdsConfigResponse,
    AdminStatusResponse,
)
from ...schemas.manga import MangaBase

from ...core.db import get_db
from ...core.pagination import MAX_PAGE
from ...core.api_errors import ApiError, ErrorCode
from ...dependencies.auth import (
    get_current_user,
    is_main_admin,
    require_admin_user,
    require_main_admin_user,
    require_permission,
)
from ...utils.endpoint_limiter import async_endpoint_limiter
from ...utils.client_ip import resolve_client_ip
from ...utils.audit_logger import log_admin_action
from ...models import (
    AdminAuditLog,
    AdminPromotionToken,
    ApprovedSourceDomain,
    Chapter,
    Manga,
    ProviderCredentials,
    ScrapingJob,
    SystemSettings,
    User,
)
from ...services import ads_config_service
from ...services.permissions_service import has_permission
from ...services.ocr_service import OCRServiceEngineError
from ...services.provider_config import (
    ProviderConfigError,
    mask_api_key,
    normalize_provider_payload,
)
from ...services.provider_registry import (
    ProviderRegistryState,
    check_configured_providers,
)
from ...services.system_settings_service import get_or_create_system_settings
from ...services.scraper_service import (
    delete_chapter_pages_only,
)
from ...services.admin_service import (
    bool_env,
    resolve_rescrape_limit,
    user_to_dict,
    normalize_role,
    find_user,
    audit_entry_to_dict,
    scraping_job_to_dict,
    token_to_dict,
    promote_user_to_secondary,
    demote_user_from_secondary,
    demote_user_from_main,
    promote_user_role,
    demote_user_role,
    promote_to_moderator,
    demote_moderator,
    effective_moderator_limit,
    count_moderators_for,
    AdminServiceError,
    RateLimitExceeded,
    hash_email,
)
from ...utils.alembic_check import capture_alembic_status
from ...utils.email_crypto import allow_email_decryption, mask_email, normalize_email


def _admin_email_access() -> Iterator[None]:
    with allow_email_decryption():
        yield


def _alert_permanent_admin_tamper_attempt(
    actor: Optional[User], target: User, action: str
) -> None:
    """SRS 1I.3.2 security alert: an attempt to modify the Permanent
    Administrator (1F.2.4). Category=security, so this is never
    suppressible by any recipient's mute/preferences."""

    from ...services.notification_service import notify_async

    notify_async(
        type="security.permanent_admin_tamper_attempt",
        title="Attempt to modify the Permanent Administrator",
        body=(
            f"User {getattr(actor, 'id', 'unknown')} attempted to {action} "
            f"the Permanent Administrator (user {target.id}). The action was "
            "blocked; the Permanent Administrator is immutable via this path."
        ),
        data={"actor_id": getattr(actor, "id", None), "target_id": target.id},
        target_type="user",
        target_id=target.id,
    )


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(_admin_email_access)],
)

logger = structlog.get_logger("backend_fastapi.admin")


@router.get(
    "/settings",
    dependencies=[Depends(require_admin_user)],
)
def get_admin_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Runtime feature toggles plus the editable site settings and branding."""

    from .site_admin import site_settings_payload

    return {
        "ALLOW_USER_OCR_API": bool_env("ALLOW_USER_OCR_API", default=False),
        "ALLOW_USER_TRANSLATION_API": bool_env(
            "ALLOW_USER_TRANSLATION_API", default=False
        ),
        **site_settings_payload(db),
    }


def _provider_registry_state(request: Request) -> ProviderRegistryState:
    state = getattr(request.app.state, "provider_registry", None)
    if isinstance(state, ProviderRegistryState):
        return state
    return ProviderRegistryState()


def _refresh_provider_registry(request: Request) -> ProviderRegistryState:
    vault = getattr(request.app.state, "integration_key_vault", None)
    state = check_configured_providers(vault=vault)
    request.app.state.provider_registry = state
    logger.info("Provider registry refreshed; OCR/translation handled client-side.")
    return state


_rescrape_limiter = resolve_rescrape_limit()


@router.post("/database/alembic-status", dependencies=[Depends(require_admin_user)])
def trigger_alembic_status(
    request: Request,
) -> dict[str, object | None]:
    """Run Alembic status commands on demand for administrators."""

    status = capture_alembic_status()
    request.app.state.alembic_status = status

    if status.config_missing:
        logger.info(
            "Alembic configuration unavailable; skipping schema drift detection"
        )
    else:
        for error in status.errors:
            logger.warning("Alembic command issue: %s", error)
        if status.schema_drift:
            logger.error("Schema drift detected – pending manual resolution")
        elif not status.determinate:
            logger.warning("Alembic schema check inconclusive; drift NOT verified")

    return status.to_dict()


@router.get("/validate-ocr-providers", dependencies=[Depends(require_admin_user)])
def validate_ocr_providers(
    request: Request,
) -> Dict[str, Any]:
    state = _provider_registry_state(request)

    try:
        from . import ocr as ocr_router

        ocr_service = getattr(ocr_router, "ocr_service", None)
    except Exception:  # pragma: no cover - defensive
        ocr_service = None

    local_enabled = False
    local_available = False
    local_engine = None
    if ocr_service is not None:
        local_enabled = bool(getattr(ocr_service, "local_enabled", False))
        local_engine = getattr(ocr_service, "tesseract_cmd", None)
        if local_enabled:
            try:
                local_available = bool(ocr_service.probe_local())
            except OCRServiceEngineError:
                local_available = False

    remote_status: Dict[str, Any] = {"configured": False, "reachable": None}
    runtime_ocr = state.provider_for("ocr")
    if runtime_ocr and runtime_ocr.get("api_url"):
        remote_status["configured"] = True
        remote_status["provider"] = runtime_ocr.get("provider")
        url = runtime_ocr.get("api_url")
        try:
            response = requests.head(url, timeout=5)
        except Exception as exc:  # pragma: no cover - network dependent
            remote_status["reachable"] = False
            remote_status["error"] = str(exc)
        else:
            status_code = response.status_code
            remote_status["status_code"] = status_code
            if status_code == 405:
                remote_status["reachable"] = True
            else:
                remote_status["reachable"] = status_code < 500

    return {
        "local": {
            "enabled": local_enabled,
            "available": local_available,
            "engine": local_engine,
        },
        "remote": remote_status,
    }


@router.get("/system-providers", dependencies=[Depends(require_main_admin_user)])
def get_system_providers(
    request: Request,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    settings = get_or_create_system_settings(db)

    state = _provider_registry_state(request)
    payload = state.to_public_payload()
    payload["system"]["localOcrEnabled"] = bool(settings.local_ocr_enabled)
    payload["system"]["localOcrEngine"] = settings.local_ocr_engine
    return payload


@router.get(
    "/system-providers/{service}/secret",
    dependencies=[Depends(require_main_admin_user)],
)
def get_system_provider_secret(
    request: Request,
    service: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    normalized = (service or "").strip().lower()
    if normalized not in {"ocr", "translation", "ai"}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invalid_service"
        )

    record = (
        db.query(ProviderCredentials)
        .filter_by(provider_name=normalized, is_system=True)
        .one_or_none()
    )
    if record is None or not record.api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="not_configured"
        )

    vault = getattr(request.app.state, "integration_key_vault", None)
    decrypt = getattr(vault, "decrypt", None)
    if callable(decrypt):
        secret = decrypt(record.api_key)
    else:
        secret = record.api_key

    if not secret:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no_secret")

    return {
        "service": normalized,
        "provider": record.provider,
        "apiKeyMasked": mask_api_key(secret),
        "apiKeyPlaintext": secret,
        "updatedAt": record.updated_at.isoformat() if record.updated_at else None,
    }


@router.put("/system-providers", dependencies=[Depends(require_main_admin_user)])
def update_system_provider(
    request: Request,
    payload: SystemProviderPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    service = (payload.service or "").strip().lower()
    # "scraper_ai" is the dedicated scraper-creation AI (SRS 1G.8.7) —
    # PA-only like every system provider, key encrypted at rest.
    if service not in {"ocr", "translation", "ai", "scraper_ai"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_service"
        )

    enabled = True if payload.enabled is None else bool(payload.enabled)

    normalized = None
    provided_api_key = False
    if payload.config is not None:
        if isinstance(payload.config, str):
            provided_api_key = True
        elif isinstance(payload.config, dict):
            provided_api_key = "apiKey" in payload.config or "api_key" in payload.config
        try:
            normalized = normalize_provider_payload(service, payload.config)
        except ProviderConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    record = (
        db.query(ProviderCredentials)
        .filter_by(provider_name=service, is_system=True)
        .one_or_none()
    )

    vault = getattr(request.app.state, "integration_key_vault", None)
    encrypt = getattr(vault, "encrypt", None)

    if normalized is None:
        if record is None:
            if enabled:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="config_required",
                )
            state = _refresh_provider_registry(request)
            return {"status": "ok", "providers": state.to_public_payload()["providers"]}

        record.provider_name = service
        record.enabled = enabled
        db.commit()
        state = _refresh_provider_registry(request)
        return {"status": "ok", "providers": state.to_public_payload()["providers"]}

    encrypted_key = None
    plain_key = normalized.get("api_key")
    if plain_key:
        encrypted_key = encrypt(plain_key) if callable(encrypt) else plain_key

    if record is None:
        record = ProviderCredentials(
            provider_name=service,
            provider=normalized["provider_id"],
            is_system=True,
        )
        db.add(record)

    record.provider_name = service
    record.provider = normalized["provider_id"]
    if provided_api_key or plain_key:
        record.api_key = encrypted_key
    record.config = normalized.get("config")
    record.enabled = enabled

    db.commit()

    state = _refresh_provider_registry(request)
    return {"status": "ok", "providers": state.to_public_payload()["providers"]}


class ScraperAiConfigPayload(BaseModel):
    apiKey: Optional[str] = Field(default=None, max_length=400)
    model: Optional[str] = Field(default=None, max_length=120)
    endpointUrl: Optional[str] = Field(default=None, max_length=500)
    enabled: bool = True


def _mask_secret_value(secret: Optional[str]) -> str:
    if not secret:
        return ""
    if len(secret) <= 10:
        return "••••••••"
    return f"{secret[:4]}••••••••{secret[-4:]}"


@router.get("/scraper/ai-config", dependencies=[Depends(require_main_admin_user)])
def get_scraper_ai_config(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """The dedicated scraper-generation AI as the Series page edits it. The
    key is never sent back in full -- only a masked form."""

    record = (
        db.query(ProviderCredentials)
        .filter_by(provider_name="scraper_ai", is_system=True)
        .one_or_none()
    )
    if record is None:
        return {"configured": False, "enabled": False, "apiKey": "", "model": "", "endpointUrl": ""}
    vault = getattr(request.app.state, "integration_key_vault", None)
    decrypt = getattr(vault, "decrypt", None)
    secret = None
    if record.api_key:
        try:
            secret = decrypt(record.api_key) if callable(decrypt) else record.api_key
        except Exception:
            secret = None
    config = record.config or {}
    return {
        "configured": bool(record.api_key),
        "enabled": bool(record.enabled),
        "provider": config.get("provider_id") or record.provider,
        "model": config.get("model") or "",
        "endpointUrl": config.get("api_url") or "",
        "apiKey": _mask_secret_value(secret),
    }


@router.post("/scraper/ai-config", dependencies=[Depends(require_main_admin_user)])
def save_scraper_ai_config(
    request: Request,
    payload: ScraperAiConfigPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    from ...services import scraper_ai_service
    from ...services.url_guard import validate_remote_image_url

    record = (
        db.query(ProviderCredentials)
        .filter_by(provider_name="scraper_ai", is_system=True)
        .one_or_none()
    )
    vault = getattr(request.app.state, "integration_key_vault", None)
    encrypt = getattr(vault, "encrypt", None)
    decrypt = getattr(vault, "decrypt", None)

    supplied = (payload.apiKey or "").strip()
    keep_existing = (not supplied or "•" in supplied) and record is not None and bool(record.api_key)
    if keep_existing:
        plain_key = decrypt(record.api_key) if callable(decrypt) else record.api_key
    else:
        plain_key = supplied
    if not plain_key:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Paste the AI provider's API key.", field="apiKey")

    try:
        built = scraper_ai_service.build_provider_config(
            plain_key, payload.model, payload.endpointUrl
        )
    except ValueError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), field="endpointUrl")
    if built["provider_id"] != "anthropic":
        problem = validate_remote_image_url(built["api_url"])
        if problem:
            raise ApiError(
                ErrorCode.VALIDATION_FAILED,
                f"That endpoint is not allowed: {problem}.",
                field="endpointUrl",
            )

    stored_key = encrypt(plain_key) if callable(encrypt) else plain_key
    if record is None:
        record = ProviderCredentials(
            provider_name="scraper_ai", provider=built["provider_id"], is_system=True, api_key=stored_key
        )
        db.add(record)
    record.provider = built["provider_id"]
    record.api_key = stored_key
    record.config = {k: v for k, v in built.items() if k != "provider_id"} | {
        "provider_id": built["provider_id"]
    }
    record.enabled = bool(payload.enabled)
    db.commit()
    _refresh_provider_registry(request)
    log_admin_action(db, request, current_user, "SCRAPER_AI_CONFIG", "provider", "scraper_ai", "success")

    test = scraper_ai_service.test_connection()
    if test.get("ok"):
        message = f"Scraper AI saved and verified ({built['provider_id']}, model {built['model'] or 'default'})."
    else:
        message = (
            "Scraper AI saved, but the connection test failed: "
            f"{test.get('error') or 'no response'}. Check the key, model and endpoint."
        )
    return {"success": bool(test.get("ok")), "saved": True, "message": message}


@router.post(
    "/system-providers/scraper-ai/test",
    dependencies=[Depends(require_main_admin_user)],
)
def test_scraper_ai() -> Dict[str, Any]:
    """The Test action for the scraper-creation AI (1G.8.8): verifies the
    configured key actually works before it is relied on. The key itself is
    never returned or logged."""
    from ...services import scraper_ai_service

    return scraper_ai_service.test_connection()


@router.patch("/system-settings", dependencies=[Depends(require_main_admin_user)])
def update_system_settings(
    request: Request,
    payload: SystemSettingsPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    settings = get_or_create_system_settings(db)

    if payload.local_ocr_enabled is not None:
        settings.local_ocr_enabled = bool(payload.local_ocr_enabled)
    if payload.local_ocr_engine is not None:
        engine = (payload.local_ocr_engine or "").strip()
        settings.local_ocr_engine = engine or None
    if payload.platform_default_daily_ceiling is not None:
        # SRS 2E.3: 0 clears the ceiling (unbounded); a positive value sets it.
        ceiling = int(payload.platform_default_daily_ceiling)
        settings.platform_default_daily_ceiling = ceiling if ceiling > 0 else None

    db.commit()
    db.refresh(settings)

    state = _refresh_provider_registry(request)
    return {
        "status": "ok",
        "system": {
            "localOcrEnabled": bool(settings.local_ocr_enabled),
            "localOcrEngine": settings.local_ocr_engine,
            "platformDefaultDailyCeiling": settings.platform_default_daily_ceiling,
        },
        "providers": state.to_public_payload()["providers"],
    }


class BulkDeletePayload(BaseModel):
    """Payload describing the manga IDs to delete."""

    ids: Sequence[int] = Field(
        default_factory=list, description="List of manga IDs to delete"
    )


class ChapterRescrapePayload(BaseModel):
    """Options for rescraping a chapter (the Fix button, 1G.12.2)."""

    delete_previous: bool = Field(
        default=False,
        description="Delete existing chapter pages before rescraping",
    )
    # 1G.12.2B: "Rescrape anyway" past the source-may-be-broken banner.
    force: bool = Field(default=False)


class UserLookupPayload(BaseModel):
    """Identify a user by ``user_id`` or ``email``."""

    user_id: int | None = Field(default=None)
    email: str | None = Field(default=None)


class RoleTogglePayload(BaseModel):
    """Request body for role toggles."""

    role: str


class SystemProviderPayload(BaseModel):
    """Payload to update a system-level provider configuration."""

    service: str = Field(..., description="Service name (ocr, translation, ai)")
    config: Optional[Dict[str, Any]] = Field(
        default=None, description="Provider configuration payload"
    )
    enabled: Optional[bool] = Field(default=True)


class SystemSettingsPayload(BaseModel):
    """Payload for updating global system settings."""

    local_ocr_enabled: Optional[bool] = Field(default=None)
    local_ocr_engine: Optional[str] = Field(default=None)
    # SRS 2E.3: pages/day ceiling on platform-default provider usage,
    # aggregate across every account not using its own key. 0 clears it.
    platform_default_daily_ceiling: Optional[int] = Field(default=None, ge=0)


class SeriesUrlPayload(BaseModel):
    """Payload containing a series URL to scrape."""

    # NOTE: intentionally not constrained with ``min_length`` here. An empty or
    # malformed URL is reported through ``_parse_series_url`` as a structured
    # error naming the field, url and reason (SRS 1G.5) instead of surfacing as
    # an opaque 422 validation array.
    url: str = Field(..., description="Direct URL to the manga series")
    provider: Optional[str] = Field(
        default=None,
        description="Optional provider hint forwarded from the client",
        max_length=100,
    )
    # Series-management form (all optional; a bare {"url": ...} still works).
    mangaupdates_url: Optional[str] = Field(default=None, max_length=500)
    base_url: Optional[str] = Field(default=None, max_length=500)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    title: Optional[str] = Field(default=None, max_length=300)
    type: Optional[str] = Field(default=None, max_length=16)
    scrape_frequency: Optional[str] = Field(default=None, max_length=32)
    scrape_interval_value: Optional[int] = Field(default=None, ge=1, le=720)
    scrape_interval_unit: Optional[str] = Field(default=None, max_length=8)
    auto_scrape_enabled: Optional[bool] = None
    chapters_to_scrape: Optional[int] = Field(default=None, ge=1, le=20000)
    custom_description: Optional[str] = Field(default=None, max_length=5000)
    custom_cover_image: Optional[str] = Field(default=None, max_length=1000)
    author: Optional[str] = Field(default=None, max_length=300)
    # How the source lays chapters/pages out (see services/chapter_grouping.py).
    chapter_group_size: Optional[int] = Field(default=None, ge=1, le=50)
    split_spreads: Optional[bool] = None
    spread_mode: Optional[str] = Field(default=None, max_length=8)
    # Manual override of what the scraper detects: auto | vertical | double | single.
    source_format: Optional[str] = Field(default=None, max_length=10)
    reading_direction: Optional[str] = Field(default=None, max_length=3)


class ApprovedDomainPayload(BaseModel):
    """Payload describing an approved scraping domain."""

    url: Optional[str] = Field(
        default=None,
        description="Full URL (or bare domain) that should be approved",
        max_length=512,
    )
    domain: Optional[str] = Field(
        default=None,
        description="Optional explicit domain value; used when URL is not provided",
        max_length=255,
    )
    label: Optional[str] = Field(
        default=None,
        description="Optional human-friendly label for this domain",
        max_length=255,
    )
    # SRS 1G.1.1: original language(s) of the site's content and its
    # politeness rate limit (requests/minute).
    original_languages: Optional[List[str]] = None
    request_rate_limit: Optional[int] = Field(default=None, ge=1, le=600)


def _normalise_provider(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalised = value.strip().lower()
    return normalised or None


def _series_url_error(*, message: str, url: Optional[str]) -> ApiError:
    """Structured validation error for series-URL problems (SRS 1B.4.2/1G.5).

    Names the ``manga_url`` field and carries a human message — never a bare
    422 with an empty body.
    """

    return ApiError(
        ErrorCode.VALIDATION_FAILED,
        message,
        field="manga_url",
        details={"url": url},
    )


def _parse_series_url(value: str) -> str:
    stripped = (value or "").strip()
    if not stripped:
        raise _series_url_error(message="A series URL is required.", url=None)

    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise _series_url_error(message="The series URL is malformed.", url=stripped)
    if parsed.path in {"", "/"}:
        raise _series_url_error(
            message="Provide a direct series URL, not just the homepage.",
            url=stripped,
        )
    return stripped


def _normalize_domain_payload(
    payload: ApprovedDomainPayload,
) -> tuple[str, str, Optional[str]]:
    raw_value = (payload.url or payload.domain or "").strip()
    if not raw_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "missing_url"}
        )

    candidate = raw_value if "://" in raw_value else f"https://{raw_value}"
    parsed = urlparse(candidate)
    hostname = parsed.hostname or ""
    hostname = hostname.strip().lower()
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail={"error": "invalid_domain"}
        )

    scheme = (parsed.scheme or "https").lower()
    base_url = f"{scheme}://{hostname}"
    label = (payload.label or "").strip() or None
    return base_url, hostname, label


@router.get(
    "/ads", response_model=AdsConfigResponse, dependencies=[Depends(require_admin_user)]
)
def get_ads_config() -> AdsConfigResponse:
    """Return the current ads configuration for admin editing."""
    return AdsConfigResponse(**ads_config_service.load_ads_config())


@router.post(
    "/ads",
    response_model=AdsConfigResponse,
    dependencies=[Depends(require_main_admin_user)],
)
def update_ads_config(
    payload: AdsConfigPayload,
) -> AdsConfigResponse:
    """Persist updates to the ads configuration."""
    # Using model_dump(by_alias=True) so it gets "global" and passes to ads_config_service
    saved_config = ads_config_service.save_ads_config(payload.model_dump(by_alias=True))
    return AdsConfigResponse(**saved_config)


@router.get(
    "/approved-domains",
    response_model=List[AdminDomainResponse],
    dependencies=[Depends(require_admin_user)],
)
def list_approved_domains(
    db: Session = Depends(get_db),
) -> List[AdminDomainResponse]:
    """Return all domains approved for scraping."""
    entries = (
        db.query(ApprovedSourceDomain).order_by(ApprovedSourceDomain.domain.asc()).all()
    )
    return [AdminDomainResponse(**entry.to_dict()) for entry in entries]


@router.post(
    "/approved-domains",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminDomainResponse,
    # SRS 1F.7/Req 8: website approval defaults to the Permanent Administrator
    # alone (approve_website default is off for everyone else) but is a
    # grantable per-person permission — no longer a hard role check.
    dependencies=[Depends(require_permission("approve_website"))],
)
def create_approved_domain(
    payload: ApprovedDomainPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("approve_website")),
) -> AdminDomainResponse:
    """Save a source website's homepage URL — this IS the approval (1G.6.0).

    What happens automatically on save (1G.6.0A): if a parser already exists
    for the domain the website becomes ACTIVE immediately and manga URL
    submission opens. If not, the website stays PENDING and the Permanent
    Administrator is notified that a parser is needed (a scraper-generation AI
    is invoked here when one is configured; otherwise the notification says a
    parser must be supplied manually — never silence).
    """
    from ...services import notification_service, parser_versions_service
    from ...scrapers.config import ConfigManager

    base_url, domain, label = _normalize_domain_payload(payload)

    existing = (
        db.query(ApprovedSourceDomain)
        .filter(ApprovedSourceDomain.domain == domain)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "duplicate_domain"},
        )

    has_parser = (
        parser_versions_service.active_for(db, domain) is not None
        or ConfigManager.get_config(domain) is not None
    )

    entry = ApprovedSourceDomain(
        base_url=base_url,
        domain=domain,
        label=label,
        status="active" if has_parser else "pending",
        original_languages=payload.original_languages,
        request_rate_limit=payload.request_rate_limit,
        approved_by=current_user.id,
        approved_at=datetime.utcnow(),
    )
    db.add(entry)

    if not has_parser:
        from ...services import scraper_ai_service

        if scraper_ai_service.is_configured():
            # 1G.6.0A: automatically invoke the scraper-creation AI. It runs
            # in the background; the outcome (candidate ready / honest
            # failure) lands on the PA's bell either way.
            db.commit()
            from ...tasks.scraper_tasks import generate_parser_task

            generate_parser_task.delay(domain, base_url, "website_saved")
        else:
            # 1G.8.8: never silently do nothing. With no scraper AI, the
            # website stays pending and the PA's bell says exactly what is
            # needed.
            notification_service.notify_async(
                type="parser.needed",
                title=f"{domain}: no parser available",
                body=(
                    f"The website {domain} was saved but has no parser, so it "
                    "is PENDING and cannot accept manga URLs yet. Supply a "
                    "parser manually, provide extraction rules, or configure "
                    "the scraper-generation AI and retry."
                ),
                data={"domain": domain},
                target_type="website",
                target_id=domain,
            )

    db.commit()
    db.refresh(entry)
    return AdminDomainResponse(**entry.to_dict())


@router.delete(
    "/approved-domains/{domain_id}",
    response_model=AdminDomainDeleteResponse,
    # SRS 1F.7: remove_website defaults to the Permanent Administrator alone
    # but is delegable per person via the permission engine.
    dependencies=[Depends(require_permission("remove_website"))],
)
def delete_approved_domain(
    domain_id: int,
    db: Session = Depends(get_db),
) -> AdminDomainDeleteResponse:
    """Remove an approved domain entry."""
    entry = db.get(ApprovedSourceDomain, domain_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )

    db.delete(entry)
    db.commit()
    return AdminDomainDeleteResponse(ok=True, deleted=domain_id)


# --------------------------------------------------------------------------
# Website lifecycle + parser versioning (SRS 1G.6.3 / 1G.8.5)
# --------------------------------------------------------------------------


class WebsiteStatusPayload(BaseModel):
    status: str = Field(..., pattern="^(pending|testing|active|degraded|disabled)$")


@router.put(
    "/approved-domains/{domain_id}/status",
    response_model=AdminDomainResponse,
    dependencies=[Depends(require_main_admin_user)],
)
def set_website_status(
    domain_id: int,
    payload: WebsiteStatusPayload,
    db: Session = Depends(get_db),
) -> AdminDomainResponse:
    """Move a website through its lifecycle (1G.6.3). Permanent Admin only."""
    entry = db.get(ApprovedSourceDomain, domain_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    entry.status = payload.status
    db.commit()
    db.refresh(entry)
    return AdminDomainResponse(**entry.to_dict())


class ParserCandidatePayload(BaseModel):
    """A parser definition submitted for review (manual or rules, 1G.10/1G.11)."""

    definition: Dict[str, Any]
    source: str = Field(default="manual", pattern="^(manual|rules)$")
    test_results: Optional[Dict[str, Any]] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


@router.get(
    "/parsers/{domain}",
    dependencies=[Depends(require_admin_user)],
)
def list_parser_versions(
    domain: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """All parser versions for a website, newest first (1G.8.5 audit trail)."""
    from ...services import parser_versions_service

    versions = parser_versions_service.list_for(db, domain.strip().lower())
    active = parser_versions_service.active_for(db, domain.strip().lower())
    return {
        "domain": domain.strip().lower(),
        "active_version": active.version if active else None,
        "versions": [v.to_dict() for v in versions],
    }


@router.post(
    "/parsers/{domain}/candidates",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_main_admin_user)],
)
def create_parser_candidate(
    domain: str,
    payload: ParserCandidatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Register a manual/rule-based parser as a CANDIDATE (1G.10 / 1G.11).

    Candidates never activate on their own (1G.8.3) — approval is a separate,
    explicit action.
    """
    from ...services import parser_versions_service

    candidate = parser_versions_service.create_candidate(
        db,
        domain=domain,
        definition=payload.definition,
        source=payload.source,
        created_by=current_user.id,
        test_results=payload.test_results,
        notes=payload.notes,
    )
    db.commit()
    return candidate.to_dict()


@router.post(
    "/parsers/versions/{version_id}/approve",
    dependencies=[Depends(require_main_admin_user)],
)
def approve_parser_version(
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Approve and activate a parser version (PA only, 1G.8.3/1G.8.4).

    Retires the previously active version (kept for rollback) and publishes
    the definition to the runtime scraper config.
    """
    from ...services import parser_versions_service

    version = parser_versions_service.activate(db, version_id, actor_id=current_user.id)
    log_admin_action(
        db,
        request,
        current_user,
        "parser.activate",
        "parser_version",
        str(version.id),
        "success",
        new_value=version.module_id,
    )
    return version.to_dict()


@router.post(
    "/parsers/versions/{version_id}/reject",
    dependencies=[Depends(require_main_admin_user)],
)
def reject_parser_version(
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Reject a candidate (1G.8.4): the website's state is unchanged."""
    from ...services import parser_versions_service

    version = parser_versions_service.reject(db, version_id, actor_id=current_user.id)
    log_admin_action(
        db,
        request,
        current_user,
        "parser.reject",
        "parser_version",
        str(version.id),
        "success",
        new_value=version.module_id,
    )
    return version.to_dict()


class ParserGenerationHints(BaseModel):
    """Optional operator-supplied sample pages for parser generation (1G.9.3).

    When homepage auto-discovery cannot find a series page, the honest-failure
    report asks the Permanent Administrator for a real series page and real
    chapter pages; this is how those get back into generation. All optional —
    an empty body preserves the original auto-discovery behaviour.
    """

    series_url: Optional[str] = Field(
        default=None, description="A sample series/manga page URL on this domain."
    )
    chapter_urls: Optional[List[str]] = Field(
        default=None,
        description="Two or more sample chapter page URLs on this domain.",
    )


@router.post(
    "/parsers/{domain}/generate",
    dependencies=[Depends(require_main_admin_user)],
)
def generate_parser(
    domain: str,
    hints: Optional[ParserGenerationHints] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """On-demand AI parser generation/repair — Path A of 1G.8.4 (PA only).

    F-20: dispatched to the same Celery task its auto-triggered twin
    (website-saved) already uses, rather than running
    ``attempt_generation``'s up-to-4-sequential-fetch,
    at-least-2-AI-provider-call chain inline inside the request handler.
    That chain can easily exceed a reverse proxy's read timeout, and unlike
    the async path there would be no ``parser.candidate_ready``/
    ``parser.generation_failed`` notification to fall back on if the
    response were lost. Never activates anything (1G.8.3); the outcome
    (CANDIDATE awaiting approval, or an honest-failure report per 1G.9)
    arrives via that notification instead of the response body.
    """
    from ...tasks.scraper_tasks import generate_parser_task

    domain = domain.strip().lower()
    entry = (
        db.query(ApprovedSourceDomain)
        .filter(ApprovedSourceDomain.domain == domain)
        .first()
    )
    base_url = entry.base_url if entry is not None else f"https://{domain}"
    series_url = hints.series_url if hints else None
    chapter_urls = hints.chapter_urls if hints else None
    task = generate_parser_task.delay(
        domain, base_url, "repair", series_url=series_url, chapter_urls=chapter_urls
    )
    return {
        "status": "queued",
        "domain": domain,
        "task_id": getattr(task, "id", None),
        "message": "Parser generation started; you'll be notified when it finishes.",
    }


@router.post(
    "/parsers/{domain}/rollback",
    dependencies=[Depends(require_main_admin_user)],
)
def rollback_parser(
    domain: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """One-action rollback to the previous working version (PA only, 1G.8.5)."""
    from ...services import parser_versions_service

    version = parser_versions_service.rollback(db, domain, actor_id=current_user.id)
    log_admin_action(
        db,
        request,
        current_user,
        "parser.rollback",
        "parser_version",
        str(version.id),
        "success",
        new_value=version.module_id,
    )
    return version.to_dict()


class WebsiteCheckSettingsPayload(BaseModel):
    """Per-website scheduled-check settings (SRS 1G.12A.4)."""

    interval_hours: Optional[int] = Field(default=None, ge=1, le=24 * 7)
    jitter_hours: Optional[float] = Field(default=None, ge=0, le=24)
    max_concurrent: Optional[int] = Field(default=None, ge=1, le=100)
    quiet_hours: Optional[List[int]] = Field(default=None, min_length=2, max_length=2)
    enabled: Optional[bool] = None


@router.put(
    "/approved-domains/{domain_id}/check-settings",
    response_model=AdminDomainResponse,
    # 1G.12A.4: Permanent Administrator and Secondary Administrators only.
    dependencies=[Depends(require_admin_user)],
)
def update_website_check_settings(
    domain_id: int,
    payload: WebsiteCheckSettingsPayload,
    db: Session = Depends(get_db),
) -> AdminDomainResponse:
    from ...services import scheduled_checks_service

    entry = db.get(ApprovedSourceDomain, domain_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    try:
        scheduled_checks_service.set_website_check_settings(
            db,
            entry,
            interval_hours=payload.interval_hours,
            jitter_hours=payload.jitter_hours,
            max_concurrent=payload.max_concurrent,
            quiet_hours=payload.quiet_hours,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, str(exc), field="interval_hours"
        ) from exc
    db.commit()
    db.refresh(entry)
    return AdminDomainResponse(**entry.to_dict())


class SeriesCheckOverridePayload(BaseModel):
    """Per-series scheduled-check override (SRS 1G.12A.5). ``null`` clears it."""

    interval_hours: Optional[int] = Field(default=None, ge=1, le=24 * 7)


@router.put(
    "/series/{manga_id}/check-override",
    dependencies=[Depends(require_admin_user)],
)
def set_series_check_override(
    manga_id: int,
    payload: SeriesCheckOverridePayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> Dict[str, Any]:
    """Per-series override, taking priority over the website default
    (1G.12A.5). Secondary + Permanent Administrators only; audited."""
    from ...services import scheduled_checks_service

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
        )
    try:
        scheduled_checks_service.set_series_check_override(
            db, manga, interval_hours=payload.interval_hours
        )
    except ValueError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, str(exc), field="interval_hours"
        ) from exc
    db.commit()
    log_admin_action(
        db,
        request,
        current_user,
        "SET_CHECK_OVERRIDE",
        "series",
        str(manga_id),
        "success",
        new_value=str(payload.interval_hours),
    )
    return {
        "series_id": manga.id,
        "check_interval_hours": manga.check_interval_hours,
        "next_check_at": (
            manga.next_check_at.isoformat() if manga.next_check_at else None
        ),
    }


@router.get(
    "/scrapers/scheduled-checks/dashboard",
    dependencies=[Depends(require_admin_user)],
)
def scheduled_checks_dashboard(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """1G.12A.8 visibility: checks run / new chapters / failures over the last
    24h and 7d, plus per-website last/next check."""
    from ...services import scheduled_checks_service

    websites = [
        scheduled_checks_service.website_check_summary(db, entry)
        for entry in db.query(ApprovedSourceDomain).order_by(
            ApprovedSourceDomain.domain
        )
    ]
    return {
        "last_24h": scheduled_checks_service.dashboard_stats(db, days=1),
        "last_7d": scheduled_checks_service.dashboard_stats(db, days=7),
        "websites": websites,
    }


@router.get("/scrapers/health", dependencies=[Depends(require_admin_user)])
def scrapers_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Website & Source Management dashboard rows (1G.7.5 / 1G.8.6): per-site
    status, health state, parser version, last success, and the Repair /
    Inspect action — a structure change is obvious without reading logs."""
    from ...services import scraper_health_service

    return {"websites": scraper_health_service.dashboard(db)}


@router.get(
    "/users/flagged",
    dependencies=[Depends(require_admin_user)],
)
def list_flagged_users(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Accounts flagged for review (SRS 1H.7.1 / D5) — currently only the
    disposable-email detector writes this flag. Flagging is never itself a
    ban; an administrator reviews and confirms one way or the other."""
    rows = (
        db.query(User)
        .filter(User.flagged_for_review.is_(True))
        .order_by(User.flagged_at.desc())
        .all()
    )
    with allow_email_decryption():
        users = [
            {
                "id": u.id,
                "email_masked": mask_email(u.email_plaintext),
                "flag_reason": u.flag_reason,
                "flagged_at": u.flagged_at.isoformat() if u.flagged_at else None,
                "is_active": bool(u.is_active),
            }
            for u in rows
        ]
    return {"users": users}


class FlagReviewPayload(BaseModel):
    # "clear" dismisses the flag (false positive); "ban" deactivates the
    # account (confirmed abuse) — the administrator-confirmation half of D5.
    decision: str = Field(..., pattern="^(clear|ban)$")


@router.post(
    "/users/{user_id}/flag-review",
    dependencies=[Depends(require_admin_user)],
)
def review_flagged_user(
    user_id: int,
    payload: FlagReviewPayload,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> Dict[str, Any]:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    if getattr(target, "permanent", False):
        _alert_permanent_admin_tamper_attempt(current_user, target, "flag/ban")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permanent_admin_immutable"},
        )

    target.flagged_for_review = False
    if payload.decision == "ban":
        target.is_active = False
        from ...services.notification_service import notify_async

        notify_async(
            type="disposable_email.banned",
            title=f"Account banned: user {target.id}",
            body=(
                f"User {target.id} was banned following disposable-email "
                f"review (reason: {target.flag_reason or 'flagged'})."
            ),
            data={"target_id": target.id, "reason": target.flag_reason},
            target_type="user",
            target_id=target.id,
        )

    log_admin_action(
        db,
        request,
        current_user,
        "FLAG_REVIEW",
        "user",
        str(user_id),
        payload.decision,
    )
    db.commit()
    return {
        "user_id": user_id,
        "decision": payload.decision,
        "is_active": bool(target.is_active),
    }


@router.post("/users/{user_id}/revoke-sessions")
def revoke_user_sessions(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    # SRS 1F.7: revoke_user_sessions defaults to admin + secondary, not
    # moderators. The permission existed in the catalogue with no endpoint
    # behind it, so an administrator had no way to end a compromised
    # account's sessions short of deactivating the account outright.
    current_user: User = Depends(require_permission("revoke_user_sessions")),
) -> Dict[str, Any]:
    """Invalidate every outstanding token for a user (SRS 1F.7).

    Used when an account is believed compromised. Unlike deactivating the
    account this leaves the user able to log in again immediately; it only
    ends the sessions that already exist.
    """

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    if getattr(target, "permanent", False) and target.id != getattr(
        current_user, "id", None
    ):
        _alert_permanent_admin_tamper_attempt(current_user, target, "revoke sessions")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "permanent_admin_immutable"},
        )

    from ...services import token_revocation

    token_revocation.revoke_all_for_user(db, target, reason="admin_revoke")

    log_admin_action(
        db,
        request,
        current_user,
        "REVOKE_SESSIONS",
        "user",
        str(user_id),
        "success",
    )

    return {"user_id": user_id, "sessions_revoked": True}


@router.get("/notifications", dependencies=[Depends(require_admin_user)])
def list_admin_notifications(
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> Dict[str, Any]:
    """Bell notifications for the current administrator (1G events, 1I UX)."""
    from ...services import notification_service

    notes = notification_service.notifications_for(
        db,
        user_id=current_user.id,
        is_permanent_admin=bool(getattr(current_user, "is_main_admin", False)),
        unread_only=unread_only,
    )
    return {"notifications": [n.to_dict() for n in notes]}


# --------------------------------------------------------------------------
# Content rights (SRS 1J)
# --------------------------------------------------------------------------


class DomainRightsPayload(BaseModel):
    """Website-level rights. ``may_host`` and ``may_translate`` are separate."""

    may_host: Optional[bool] = None
    may_translate: Optional[bool] = None
    attribution: Optional[str] = Field(default=None, max_length=512)
    license: Optional[str] = Field(default=None, max_length=128)


class SeriesRightsPayload(BaseModel):
    """Series-level rights overriding (but never exceeding) website defaults."""

    may_host: Optional[bool] = None
    may_translate: Optional[bool] = None
    attribution: Optional[str] = Field(default=None, max_length=512)
    rights_note: Optional[str] = None


class TakedownPayload(BaseModel):
    # none | requested | taken_down
    status: str = Field(..., pattern="^(none|requested|taken_down)$")
    reason: Optional[str] = None


@router.put(
    "/approved-domains/{domain_id}/rights",
    response_model=AdminDomainResponse,
    dependencies=[Depends(require_main_admin_user)],
)
def update_domain_rights(
    domain_id: int,
    payload: DomainRightsPayload,
    db: Session = Depends(get_db),
) -> AdminDomainResponse:
    """Set a website's hosting/translation rights (Permanent Admin only)."""
    entry = db.get(ApprovedSourceDomain, domain_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    if payload.may_host is not None:
        entry.may_host = payload.may_host
    if payload.may_translate is not None:
        entry.may_translate = payload.may_translate
    if payload.attribution is not None:
        entry.attribution = payload.attribution.strip() or None
    if payload.license is not None:
        entry.license = payload.license.strip() or None
    db.commit()
    db.refresh(entry)
    return AdminDomainResponse(**entry.to_dict())


@router.get(
    "/series/{manga_id}/rights",
    dependencies=[Depends(require_admin_user)],
)
def get_series_rights(
    manga_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Return the effective rights resolved for a series."""
    from ...services.content_rights import resolve_series_rights

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    return resolve_series_rights(db, manga)


@router.put(
    "/series/{manga_id}/rights",
    dependencies=[Depends(require_main_admin_user)],
)
def update_series_rights(
    manga_id: int,
    payload: SeriesRightsPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Set a series' hosting/translation rights (Permanent Admin only)."""
    from ...services.content_rights import resolve_series_rights

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    if payload.may_host is not None:
        manga.may_host = payload.may_host
    if payload.may_translate is not None:
        manga.may_translate = payload.may_translate
    if payload.attribution is not None:
        manga.attribution = payload.attribution.strip() or None
    if payload.rights_note is not None:
        manga.rights_note = payload.rights_note.strip() or None
    db.commit()
    db.refresh(manga)
    return resolve_series_rights(db, manga)


@router.post(
    "/series/{manga_id}/takedown",
    dependencies=[Depends(require_main_admin_user)],
)
def set_series_takedown(
    request: Request,
    manga_id: int,
    payload: TakedownPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Record a takedown decision for a series (Permanent Admin only).

    ``taken_down`` denies both hosting and translation regardless of the
    per-series flags.
    """
    from ...services.content_rights import resolve_series_rights

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    manga.takedown_status = payload.status
    manga.takedown_reason = (payload.reason or "").strip() or None
    db.commit()
    db.refresh(manga)

    # F-18: without this, a just-taken-down series could keep serving its
    # cached detail/chapter-list pages (up to the cache's TTL) regardless of
    # the read-path gate above, since that gate runs its own uncached query
    # -- but the cached payload itself would still reflect the pre-takedown
    # state to any admin bypassing the gate, and to every viewer once the
    # gate is satisfied again (e.g. a later "restore" action).
    from ...utils.cache_invalidation import invalidate_manga_caches_sync

    invalidate_manga_caches_sync(manga_id)

    return resolve_series_rights(db, manga)


# --------------------------------------------------------------------------
# Session policy (SRS 1D.5.1) — Permanent Administrator only
# --------------------------------------------------------------------------


class SessionPolicyPayload(BaseModel):
    """Admin-configurable session lifetime in days (1–30)."""

    session_expiry_days: Optional[int] = Field(default=None, ge=1, le=30)
    magic_link_ttl_minutes: Optional[int] = Field(default=None, ge=5, le=60)


def _session_policy_payload(row: SystemSettings) -> Dict[str, Any]:
    return {
        "session_expiry_days": getattr(row, "session_expiry_days", 14) or 14,
        "session_expiry_min_days": 1,
        "session_expiry_max_days": 30,
        "magic_link_ttl_minutes": getattr(row, "magic_link_ttl_minutes", 15) or 15,
    }


@router.get("/config/session", dependencies=[Depends(require_admin_user)])
def get_session_policy(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return the current session-expiry policy."""
    return _session_policy_payload(get_or_create_system_settings(db))


@router.put(
    "/config/session", dependencies=[Depends(require_permission("set_session_policy"))]
)
def update_session_policy(
    payload: SessionPolicyPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Set the session-expiry policy (Permanent Administrator only).

    ``session_expiry_days`` is bounded to 1–30 (SRS 1D.5.1). Out-of-range values
    are rejected by schema validation as VALIDATION_FAILED.
    """
    row = get_or_create_system_settings(db)
    if payload.session_expiry_days is not None:
        row.session_expiry_days = payload.session_expiry_days
    if payload.magic_link_ttl_minutes is not None:
        row.magic_link_ttl_minutes = payload.magic_link_ttl_minutes
    db.commit()
    db.refresh(row)
    return _session_policy_payload(row)


# --------------------------------------------------------------------------
# Granular permission overrides (SRS 1F.6–1F.10) — Permanent Administrator only
# --------------------------------------------------------------------------


class PermissionOverrideItem(BaseModel):
    permission: str
    state: str  # granted | revoked | inherited


class PermissionOverridesPayload(BaseModel):
    overrides: List[PermissionOverrideItem]


@router.get("/permissions/catalogue", dependencies=[Depends(require_admin_user)])
def get_permission_catalogue() -> Dict[str, Any]:
    """Full permission catalogue, grouped (SRS 1F.7/1F.9.2)."""
    from ...services.permissions_service import full_catalogue

    return {"permissions": full_catalogue()}


@router.get(
    "/users/{user_id}/permissions",
    dependencies=[Depends(require_main_admin_user)],
)
def get_user_permissions(
    user_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """A person's effective permission set with inherited/granted/revoked state."""
    from ...services.permissions_service import modified_count, resolve_effective

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    return {
        "user_id": user.id,
        "role": user.role.value if user.role else None,
        "modified_count": modified_count(db, user),
        "permissions": resolve_effective(db, user),
    }


@router.put(
    "/users/{user_id}/permissions",
    dependencies=[Depends(require_main_admin_user)],
)
def set_user_permissions(
    user_id: int,
    payload: PermissionOverridesPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Set per-person overrides (Permanent Administrator only, SRS 1F.6.3).

    Never-grantable permissions (1F.8) are refused with FORBIDDEN. The Permanent
    Administrator's own overrides cannot be edited (they hold everything).
    """
    from ...services.permissions_service import (
        modified_count,
        resolve_effective,
        set_override,
    )

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    if getattr(target, "permanent", False) or getattr(target, "is_main_admin", False):
        _alert_permanent_admin_tamper_attempt(
            current_user, target, "override permissions for"
        )
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "The Permanent Administrator's permissions cannot be overridden.",
            details={"reason": "permanent_admin_immutable"},
        )

    for item in payload.overrides:
        set_override(db, target, item.permission, item.state, current_user.id)

    # Audit the override change (SRS 1F.6.3).
    db.add(
        AdminAuditLog(
            user_id=current_user.id,
            operator=getattr(current_user, "email_plaintext", None),
            action="permissions.override",
            metadata_json={
                "target_user_id": user_id,
                "changes": [
                    {"permission": i.permission, "state": i.state}
                    for i in payload.overrides
                ],
            },
        )
    )
    db.commit()
    db.refresh(target)
    return {
        "user_id": target.id,
        "modified_count": modified_count(db, target),
        "permissions": resolve_effective(db, target),
    }


@router.post(
    "/users/{user_id}/permissions/reset",
    dependencies=[Depends(require_main_admin_user)],
)
def reset_user_permissions(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Reset a person to their role defaults (SRS 1F.9.2)."""
    from ...services.permissions_service import reset_to_default, resolve_effective

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    reset_to_default(db, target)
    db.add(
        AdminAuditLog(
            user_id=current_user.id,
            operator=getattr(current_user, "email_plaintext", None),
            action="permissions.reset",
            metadata_json={"target_user_id": user_id},
        )
    )
    db.commit()
    return {"user_id": target.id, "permissions": resolve_effective(db, target)}


class CreatePresetPayload(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=400)
    grant: List[str] = Field(default_factory=list)
    revoke: List[str] = Field(default_factory=list)


class ApplyPresetPayload(BaseModel):
    preset: str = Field(..., min_length=1, max_length=64)


@router.get("/permissions/presets", dependencies=[Depends(require_admin_user)])
def get_permission_presets(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Built-in + custom permission presets (SRS 1F.9.3)."""
    from ...services.permissions_service import list_presets

    return {"presets": list_presets(db)}


@router.post("/permissions/presets", dependencies=[Depends(require_main_admin_user)])
def create_permission_preset(
    payload: CreatePresetPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create/update a custom preset (Permanent Administrator only)."""
    from ...services.permissions_service import create_custom_preset

    preset = create_custom_preset(
        db,
        key=payload.key,
        label=payload.label,
        description=payload.description,
        grant=payload.grant,
        revoke=payload.revoke,
        actor_id=current_user.id,
    )
    db.commit()
    db.refresh(preset)
    return {"key": preset.key, "label": preset.label, "definition": preset.definition}


@router.post(
    "/users/{user_id}/permissions/apply-preset",
    dependencies=[Depends(require_main_admin_user)],
)
def apply_permission_preset(
    user_id: int,
    payload: ApplyPresetPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Apply a preset to a person (Permanent Administrator only, SRS 1F.9.3)."""
    from ...services.permissions_service import (
        apply_preset,
        modified_count,
        resolve_effective,
    )

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    if getattr(target, "permanent", False) or getattr(target, "is_main_admin", False):
        _alert_permanent_admin_tamper_attempt(
            current_user, target, "override permissions for"
        )
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "The Permanent Administrator's permissions cannot be overridden.",
            details={"reason": "permanent_admin_immutable"},
        )
    apply_preset(db, target, payload.preset, current_user.id)
    db.add(
        AdminAuditLog(
            user_id=current_user.id,
            operator=getattr(current_user, "email_plaintext", None),
            action="permissions.apply_preset",
            metadata_json={"target_user_id": user_id, "preset": payload.preset},
        )
    )
    db.commit()
    return {
        "user_id": target.id,
        "modified_count": modified_count(db, target),
        "permissions": resolve_effective(db, target),
    }


@router.get(
    "/permissions/managed",
    dependencies=[Depends(require_main_admin_user)],
)
def list_managed_permissions(
    modified_only: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Secondary Admins + Moderators with modified counts (SRS 1F.9.1).

    ``modified_only=true`` returns only people who deviate from their role
    default — the "Modified only" filter.
    """
    from ...services.permissions_service import list_managed_people

    return {"people": list_managed_people(db, modified_only=modified_only)}


# --------------------------------------------------------------------------
# Moderator role management + the 10-moderator limit (SRS 1F.3.3 / Req 6)
# --------------------------------------------------------------------------


class ModeratorPromotePayload(BaseModel):
    user_id: int


class ModeratorLimitPayload(BaseModel):
    moderator_limit: int = Field(..., ge=1, le=1000)


@router.post("/roles/moderators")
def promote_moderator_endpoint(
    payload: ModeratorPromotePayload,
    current_user: User = Depends(require_permission("promote_moderator")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Promote a user to moderator. Secondary admins are capped (SRS 1F.3.3)."""
    target = db.get(User, payload.user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    try:
        target = promote_to_moderator(db, target, current_user)
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return {
        "user_id": target.id,
        "role": target.role.value,
        "assigned_to_admin_id": target.assigned_to_admin_id,
    }


@router.delete("/roles/moderators/{user_id}")
def demote_moderator_endpoint(
    user_id: int,
    current_user: User = Depends(require_permission("demote_own_moderators")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Demote a moderator. The Permanent Administrator can demote any (1F.2.2)."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    try:
        target = demote_moderator(db, target, current_user)
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return {"user_id": target.id, "role": target.role.value}


@router.put(
    "/users/{user_id}/moderator-limit",
    dependencies=[Depends(require_main_admin_user)],
)
def set_moderator_limit(
    user_id: int,
    payload: ModeratorLimitPayload,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Set a Secondary Administrator's per-person moderator cap (PA only)."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    target.moderator_limit = payload.moderator_limit
    db.commit()
    db.refresh(target)
    return {
        "user_id": target.id,
        "moderator_limit": effective_moderator_limit(target),
        "current_moderators": count_moderators_for(db, target.id),
    }


@router.post("/series/scrape", dependencies=[Depends(require_admin_user)])
def preview_series_scrape(
    payload: SeriesUrlPayload,
) -> Dict[str, Any]:
    """Return a lightweight preview payload for a series scrape."""
    url = _parse_series_url(payload.url)
    provider = _normalise_provider(payload.provider)
    parsed = urlparse(url)
    preview: Dict[str, Any] = {
        "title": None,
        "alt_titles": [],
        "description": "",
        "author": [],
        "artist": [],
        "genres": [],
        "status": None,
        "source_url": url,
        "thumbnail": None,
        "chapters": [],
        "domain": parsed.netloc,
    }
    if provider:
        preview["provider"] = provider
    return {"series": preview}


@router.post(
    "/series",
    status_code=status.HTTP_201_CREATED,
    # SRS 1F.7: submitting a manga URL for an approved site is a catalogue
    # permission (moderators hold it by default).
    dependencies=[Depends(require_permission("submit_manga_url"))],
)
async def create_series_by_url(
    request: Request,
    payload: SeriesUrlPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Queue a background job that ingests a series: metadata from
    MangaUpdates (when a link is given) plus every chapter from the source."""
    await async_endpoint_limiter.check_limit(
        request, f"create_series:{current_user.id}", limit=20, window_seconds=3600
    )
    url = _parse_series_url(payload.source_url or payload.url or payload.base_url or "")
    provider = _normalise_provider(payload.provider)

    from ...utils.bounded_threadpool import run_in_db_threadpool

    submitter_id = current_user.id
    can_approve = has_permission(db, current_user, "approve_website")

    def _sync_schedule():
        from backend_fastapi.app.core.db import SessionLocal
        from ...services import series_import

        with SessionLocal() as db_session:
            actor = db_session.get(User, submitter_id)
            return series_import.queue_series_import(
                db_session, actor, url, payload, can_approve=can_approve
            )

    try:
        job = await run_in_db_threadpool(_sync_schedule)
    except ApiError:
        # Structured domain errors (unapproved website, duplicate URL, host
        # forbidden, no parser) render via the global handler.
        raise
    except Exception as exc:
        logger.exception("Failed to schedule series scrape", extra={"url": url})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Series scrape failed",
        ) from exc

    response: Dict[str, Any] = {
        "message": job.pop("message", "series_scrape_scheduled"),
        "job": job,
        "source_url": url,
    }
    if provider:
        response["provider"] = provider
    return response


@router.get(
    "/series/{manga_id}/ingestion",
    # Visible to everyone who can submit manga URLs (the submitter watches
    # their own submission progress — SRS 1G.2.3).
    dependencies=[Depends(require_permission("submit_manga_url"))],
)
def series_ingestion_progress(
    manga_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Chapter-by-chapter ingestion progress for a series (1G.2.3)."""
    from ...services.manga_service import ingestion_progress

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"error": "not_found"}
        )
    return ingestion_progress(db, manga)


class EmailRolePayload(BaseModel):
    email: str
    role: str | None = None


@router.get("/users/{user_id}/email", dependencies=[Depends(require_main_admin_user)])
def reveal_user_email(
    user_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Decrypt and return a standard user's email for authorized admin roles."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )

    with allow_email_decryption():
        email = user.email

    return {
        "user_id": user.id,
        "email": email,
    }


@router.get("/status", response_model=AdminStatusResponse)
def get_status(
    current_user: User = Depends(require_admin_user),
) -> AdminStatusResponse:
    """Return information about the authenticated admin user.

    Blind Spot #13: gated with ``require_admin_user`` so non-admins cannot probe
    admin role state.
    """

    return AdminStatusResponse(authenticated=True, user=user_to_dict(current_user))


@router.get(
    "/users",
    response_model=AdminUsersResponse,
    # SRS 1F.7: view_user_list defaults to admin + secondary (not moderators).
    dependencies=[Depends(require_permission("view_user_list"))],
)
def list_users(
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1, le=MAX_PAGE),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(default=None),
) -> AdminUsersResponse:
    """List users with optional pagination and search (admin access required)."""

    query = db.query(User)

    if search:
        term = search.strip()
        if term:
            pattern = f"%{term}%"
            query = query.filter(
                or_(User.username.ilike(pattern), User.name.ilike(pattern))
            )

    total = int(query.order_by(None).with_entities(func.count(User.id)).scalar() or 0)
    pages = int(math.ceil(total / per_page)) if total else 0

    if pages == 0:
        current_page = 1
    else:
        current_page = min(page, pages)

    offset = (current_page - 1) * per_page if total else 0
    items = (
        query.order_by(User.id.asc()).offset(offset).limit(per_page).all()
        if total
        else []
    )

    return AdminUsersResponse(
        items=[user_to_dict(user) for user in items],
        page=current_page,
        pages=pages,
        per_page=per_page,
        total=total,
        has_next=current_page < pages,
        has_prev=current_page > 1 and total > 0,
    )


@router.get(
    "/users/all", dependencies=[Depends(require_admin_user)]
)
def list_users_legacy_alias(
    db: Session = Depends(get_db),
) -> list[dict[str, object | None]]:
    """Compatibility alias for the legacy ``/admin/users/all`` endpoint."""
    users = db.query(User).order_by(User.id.asc()).all()
    return [user_to_dict(user) for user in users]


@router.post("/promote-secondary", response_model=RoleToggleResponse)
def promote_secondary_admin(
    payload: UserLookupPayload,
    db: Session = Depends(get_db),
    # SRS 1F.7: promoting a Secondary Administrator is the Permanent
    # Administrator's by default; enforced via the permission engine.
    current_user: User = Depends(require_permission("promote_secondary")),
) -> RoleToggleResponse:
    """Grant secondary admin rights to a user."""

    user = find_user(db, user_id=payload.user_id, email=payload.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    try:
        user = promote_user_to_secondary(db, user, current_user)
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    return RoleToggleResponse(success=True, user=user_to_dict(user))


@router.post("/demote-secondary", response_model=RoleToggleResponse)
def demote_secondary_admin(
    payload: UserLookupPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("demote_secondary")),
) -> RoleToggleResponse:
    """Remove secondary admin rights from a user."""

    user = find_user(db, user_id=payload.user_id, email=payload.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    try:
        user = demote_user_from_secondary(db, user, current_user)
    except AdminServiceError as exc:
        code = (
            status.HTTP_403_FORBIDDEN
            if str(exc) == "insufficient_privileges"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    return RoleToggleResponse(success=True, user=user_to_dict(user))


@router.post("/demote-main", response_model=RoleToggleResponse)
def demote_main_admin(
    payload: UserLookupPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> RoleToggleResponse:
    """Remove main admin privileges from a target user."""

    user = find_user(db, user_id=payload.user_id, email=payload.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    try:
        user = demote_user_from_main(db, user, current_user)
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return RoleToggleResponse(success=True, user=user_to_dict(user))


@router.post("/promote/{user_id}", response_model=RoleToggleResponse)
def promote_user(
    request: Request,
    user_id: int,
    payload: RoleTogglePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> RoleToggleResponse:
    requested_role = normalize_role(payload.role)
    if requested_role in {None, "admin", "permanent_admin"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_role"
        )
    if requested_role not in {"secondary_admin", "user"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_role"
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )

    previous = str(user.role)
    try:
        user = promote_user_role(db, user, requested_role, current_user)
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    # F-7: this handler already took `request` (the signature of one that
    # intends to audit) but never called log_admin_action, unlike its
    # demote_user sibling -- an auditor filtering admin_audit_logs for
    # action="PROMOTE" found nothing, even though this is exactly the
    # endpoint that grants Secondary Administrator.
    log_admin_action(
        db,
        request,
        current_user,
        "PROMOTE",
        "user",
        str(user_id),
        "success",
        previous_value=previous,
        new_value=str(user.role),
    )

    return RoleToggleResponse(
        message=f"User role set to {requested_role.upper()}", user=user_to_dict(user)
    )


@router.post("/demote/{user_id}", response_model=RoleToggleResponse)
def demote_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> RoleToggleResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )

    previous = str(user.role)
    try:
        user = demote_user_role(db, user, current_user)
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    log_admin_action(
        db,
        request,
        current_user,
        "DEMOTE",
        "user",
        str(user_id),
        "success",
        previous_value=previous,
        new_value=str(user.role),
    )

    return RoleToggleResponse(message="User demoted to USER", user=user_to_dict(user))


# NOTE (SRS 1F.2.4): there is intentionally NO endpoint that assigns the
# Permanent Administrator role. The role is bound exclusively from deployment
# configuration on first login (1F.2.3, admin_bootstrap); no in-application
# path exists — not admin-only, not hidden, not behind a flag. A former
# POST /admin/permanent/{user_id} endpoint was removed for this reason.


@router.post("/promote-by-email", response_model=RoleToggleResponse)
def promote_by_email(
    request: Request,
    payload: EmailRolePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> RoleToggleResponse:
    email = normalize_email(payload.email)
    requested_role = normalize_role(payload.role)

    if not email or requested_role in {None, "admin", "permanent_admin"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_payload"
        )

    email_hashed = hash_email(email)
    if not email_hashed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email"
        )

    user = db.query(User).filter(User.email_hash == email_hashed).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )

    previous = str(user.role)
    try:
        user = promote_user_role(
            db, user, requested_role, current_user, method="by_email"
        )
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    # F-7: same taxonomy gap as promote_user -- an "action=PROMOTE" audit
    # search must not miss promotions issued by email either.
    log_admin_action(
        db,
        request,
        current_user,
        "PROMOTE",
        "user",
        str(user.id),
        "success",
        previous_value=previous,
        new_value=str(user.role),
    )

    return RoleToggleResponse(
        message=f"{email} role set to {requested_role.upper()}",
        user=user_to_dict(user),
    )


@router.post("/demote-by-email", response_model=RoleToggleResponse)
def demote_by_email(
    request: Request,
    payload: EmailRolePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> RoleToggleResponse:
    email = normalize_email(payload.email)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_payload"
        )

    email_hashed = hash_email(email)
    if not email_hashed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email"
        )

    user = db.query(User).filter(User.email_hash == email_hashed).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found"
        )

    previous = str(user.role)
    try:
        user = demote_user_role(db, user, current_user, method="by_email")
    except AdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc

    # F-7: demote_user already logs; its by-email sibling did not.
    log_admin_action(
        db,
        request,
        current_user,
        "DEMOTE",
        "user",
        str(user.id),
        "success",
        previous_value=previous,
        new_value=str(user.role),
    )

    return RoleToggleResponse(
        message=f"{email} demoted to USER",
        user=user_to_dict(user),
    )


@router.get(
    "/audit/logs",
    response_model=List[AdminAuditLogEntry],
)
def list_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> List[AdminAuditLogEntry]:
    """Kept for existing callers; unfiltered, capped at 500. Prefer
    GET /audit/logs/search for filtering and true pagination (1H.7.2)."""
    rows = (
        db.query(AdminAuditLog)
        .order_by(AdminAuditLog.timestamp.desc(), AdminAuditLog.id.desc())
        .limit(limit)
        .all()
    )
    # F-SSS-01: plaintext user_email is main-admin-only, matching
    # reveal_user_email's gate -- a Secondary Admin (require_admin_user
    # already let them in) gets user_email_masked instead.
    viewer_is_main_admin = is_main_admin(current_user)
    return [
        AdminAuditLogEntry(
            **audit_entry_to_dict(entry, viewer_is_main_admin=viewer_is_main_admin)
        )
        for entry in rows
    ]


@router.get(
    "/audit/logs/search",
    response_model=AdminAuditLogPage,
)
def search_audit_logs(
    actor_id: Optional[int] = Query(default=None),
    action: Optional[str] = Query(default=None, max_length=64),
    target_id: Optional[str] = Query(default=None, max_length=64),
    outcome: Optional[str] = Query(default=None, max_length=32),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1, le=MAX_PAGE),
    per_page: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> AdminAuditLogPage:
    """Searchable, filterable, paginated audit log (SRS 1H.7.2): filter by
    actor, action type, target, date range, and outcome."""

    query = db.query(AdminAuditLog)
    if actor_id is not None:
        query = query.filter(AdminAuditLog.user_id == actor_id)
    if action:
        query = query.filter(AdminAuditLog.action.ilike(f"%{action}%"))
    if date_from is not None:
        query = query.filter(AdminAuditLog.timestamp >= date_from)
    if date_to is not None:
        query = query.filter(AdminAuditLog.timestamp <= date_to)
    # F-SSS-03: func.json_extract(...) emits a literal SQLite/MySQL function
    # call with no dialect translation -- PostgreSQL has no function of that
    # name, so this 500'd on every real (Postgres-backed) deployment.
    # metadata_json[...].as_string() is SQLAlchemy's dialect-aware JSON
    # accessor: JSON_EXTRACT on SQLite, ->> cast to text on Postgres.
    if target_id:
        query = query.filter(
            AdminAuditLog.metadata_json["target_id"].as_string() == target_id
        )
    if outcome:
        query = query.filter(
            or_(
                AdminAuditLog.metadata_json["result"].as_string() == outcome,
                AdminAuditLog.metadata_json["outcome"].as_string() == outcome,
            )
        )

    total = query.order_by(None).count()
    pages = max(1, (total + per_page - 1) // per_page)
    rows = (
        query.order_by(AdminAuditLog.timestamp.desc(), AdminAuditLog.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    # F-SSS-01: plaintext user_email is main-admin-only, matching
    # reveal_user_email's gate -- a Secondary Admin (require_admin_user
    # already let them in) gets user_email_masked instead.
    viewer_is_main_admin = is_main_admin(current_user)
    return AdminAuditLogPage(
        items=[
            AdminAuditLogEntry(
                **audit_entry_to_dict(
                    entry, viewer_is_main_admin=viewer_is_main_admin
                )
            )
            for entry in rows
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get(
    "/series",
    response_model=List[MangaBase],
    dependencies=[Depends(require_main_admin_user)],
)
def list_series(
    type_: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> List[MangaBase]:
    """List manga series for administrative purposes."""

    query = db.query(Manga)

    if type_:
        allowed_types = {"manga", "manhwa", "manhua"}
        if type_ not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid type filter"
            )
        query = query.filter(Manga.type == type_)

    if status_filter:
        allowed_status = {"ongoing", "hiatus", "dropped", "cancelled"}
        if status_filter not in allowed_status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status filter"
            )
        query = query.filter(Manga.status == status_filter)

    items = query.order_by(Manga.updated_at.desc()).all()
    return [MangaBase(**manga.to_dict()) for manga in items]


@router.delete(
    "/series/{manga_id}",
    response_model=AdminActionResponse,
    # SRS 1F.7: delete_series defaults to admin + secondary admin.
    dependencies=[Depends(require_permission("delete_series"))],
)
def delete_series(
    request: Request,
    manga_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdminActionResponse:
    """Delete a manga series and all of its chapters."""

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
        )

    deleted_chapters = db.query(Chapter).filter(Chapter.manga_id == manga.id).delete()
    db.delete(manga)
    db.commit()
    from ...services import page_image_service

    page_image_service.delete_series_files(manga_id)

    log_admin_action(
        db,
        request,
        current_user,
        "DELETE_SERIES",
        "series",
        str(manga_id),
        "success",
        new_value=str(deleted_chapters),
    )

    logger.info(
        "Series deleted",
        extra={"manga_id": manga_id, "deleted_chapters": deleted_chapters},
    )
    return AdminActionResponse(
        ok=True, deleted_chapters=deleted_chapters, manga_id=manga_id
    )


@router.post(
    "/series/bulk-delete",
    response_model=AdminActionResponse,
    dependencies=[Depends(require_main_admin_user)],
)
def bulk_delete_series(
    request: Request,
    payload: BulkDeletePayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdminActionResponse:
    """Bulk delete multiple manga series."""

    unique_ids = sorted(
        {int(manga_id) for manga_id in payload.ids if isinstance(manga_id, int)}
    )
    if not unique_ids:
        return AdminActionResponse(ok=True, count=0)

    from ...tasks.scraper_tasks import bulk_delete_series_task

    bulk_delete_series_task.delay(unique_ids)

    log_admin_action(
        db,
        request,
        current_user,
        "BULK_DELETE",
        "series",
        "multiple",
        "success",
        new_value=str(unique_ids),
    )

    logger.info(
        "Bulk series delete queued", extra={"count": len(unique_ids), "ids": unique_ids}
    )
    return AdminActionResponse(ok=True, count=len(unique_ids))


@router.get(
    "/scraping-jobs",
    response_model=List[AdminScrapingJobBase],
    dependencies=[Depends(require_admin_user)],
)
def list_scraping_jobs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> List[AdminScrapingJobBase]:
    """Return recent scraping job activity for monitoring."""

    jobs = (
        db.query(ScrapingJob)
        .order_by(ScrapingJob.created_at.desc(), ScrapingJob.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [AdminScrapingJobBase(**scraping_job_to_dict(job)) for job in jobs]


@router.get(
    "/admin-tokens",
    response_model=List[AdminTokenBase],
    dependencies=[Depends(require_admin_user)],
)
def list_admin_tokens(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> List[AdminTokenBase]:
    """Audit recently issued admin promotion tokens."""

    tokens = (
        db.query(AdminPromotionToken)
        .order_by(AdminPromotionToken.issued_at.desc(), AdminPromotionToken.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [AdminTokenBase(**token_to_dict(token)) for token in tokens]


class SeriesRescrapePayload(BaseModel):
    """Strong confirmation for a full-series rescrape (1G.12.3): the caller
    must type the series name, not just click."""

    confirm_title: str = Field(..., min_length=1, max_length=512)


@router.post(
    "/series/{manga_id}/rescrape",
    response_model=RescrapeResponse,
)
def rescrape_series(
    manga_id: int,
    payload: SeriesRescrapePayload,
    request: Request,
    db: Session = Depends(get_db),
    # SRS Req 29 / 1F.7 / 1G.12.3: entire-series rescrape is Secondary +
    # Permanent Administrators (not moderators) — via the permission engine.
    current_user: User = Depends(require_permission("rescrape_series")),
) -> RescrapeResponse:
    """Queue a staged full rescrape for a manga series (1G.12.3/1G.12.4)."""

    key = (
        f"user:{current_user.id}"
        if current_user
        # F-72: resolve_client_ip checks the immediate peer against the
        # trusted-proxy allowlist before honouring X-Forwarded-For, so behind
        # a proxy this buckets by the real client instead of collapsing every
        # anonymous caller into the proxy's single IP.
        else f"ip:{resolve_client_ip(request)}"
    )
    try:
        _rescrape_limiter.consume(key)
    except RateLimitExceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many rescrape requests; please wait before retrying.",
        ) from None

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
        )

    # F-18: a taken-down/not-hostable series must not have its stored pages
    # overwritten by a freshly re-fetched copy from the still-approved
    # source. Absolute -- unlike the read-path gate, no admin bypass: the
    # same rule assert_series_translatable already applies to every role.
    from ...services.content_rights import assert_series_hostable

    assert_series_hostable(db, manga)

    # 1G.12.3: typed-name confirmation, not a single click.
    if (payload.confirm_title or "").strip() != (manga.title or "").strip():
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Type the series name exactly to confirm a full rescrape.",
            field="confirm_title",
            details={"expected_title": manga.title},
        )

    from ...tasks.scraper_tasks import staged_series_rescrape

    task = staged_series_rescrape.delay(manga_id, current_user.id)
    log_admin_action(
        db,
        request,
        current_user,
        "RESCRAPE_SERIES",
        "series",
        str(manga_id),
        "queued",
        new_value=f"chapters={db.query(Chapter).filter(Chapter.manga_id == manga_id).count()}",  # noqa: E501
    )
    result = {"status": "queued", "task_id": getattr(task, "id", None)}
    return RescrapeResponse(ok=True, result=result, manga_id=manga_id)


@router.post(
    "/series/{manga_id}/rescrape/rollback",
    response_model=RescrapeResponse,
    dependencies=[Depends(require_main_admin_user)],
)
def rollback_series_rescrape(
    manga_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_main_admin_user),
) -> RescrapeResponse:
    """Restore the prior snapshot after a bad rescrape (PA only, 1G.12.4)."""
    from ...services.rescrape_service import rollback_series

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
        )
    result = rollback_series(db, manga)
    log_admin_action(
        db,
        request,
        current_user,
        "RESCRAPE_ROLLBACK",
        "series",
        str(manga_id),
        "success",
        new_value=str(result.get("restored_chapters")),
    )
    return RescrapeResponse(ok=True, result=result, manga_id=manga_id)


@router.post(
    "/chapters/{chapter_id}/rescrape",
    response_model=RescrapeResponse,
)
def rescrape_chapter(
    chapter_id: int,
    payload: ChapterRescrapePayload,
    request: Request,
    db: Session = Depends(get_db),
    # SRS Req 28 / 1F.7: single-chapter rescrape is Moderator and above.
    current_user: User = Depends(require_permission("rescrape_chapter")),
) -> RescrapeResponse:
    """Rescrape a single chapter, optionally deleting existing assets first."""

    key = (
        f"user:{current_user.id}"
        if current_user
        # F-72: resolve_client_ip checks the immediate peer against the
        # trusted-proxy allowlist before honouring X-Forwarded-For, so behind
        # a proxy this buckets by the real client instead of collapsing every
        # anonymous caller into the proxy's single IP.
        else f"ip:{resolve_client_ip(request)}"
    )
    try:
        _rescrape_limiter.consume(key)
    except RateLimitExceeded:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many rescrape requests; please wait before retrying.",
        ) from None

    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found"
        )

    # F-18: same absolute gate as rescrape_series -- a taken-down/
    # not-hostable series' chapters must not be refreshed from source either.
    if chapter.manga is not None:
        from ...services.content_rights import assert_series_hostable

        assert_series_hostable(db, chapter.manga)

    from ...services.rescrape_service import fix_chapter

    try:
        if payload.delete_previous:
            delete_chapter_pages_only(chapter, db_session=db)
        # The Fix flow (1G.12.2): atomic dedupe, subscriber notifications,
        # and the "source may be broken" banner window (payload.force is the
        # Rescrape-anyway choice).
        result = fix_chapter(db, chapter, actor_id=current_user.id, force=payload.force)
    except ApiError:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except (RuntimeError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scraper service unavailable",
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to rescrape chapter", extra={"chapter_id": chapter_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Rescrape failed"
        ) from exc

    # Every Fix action is audited with actor, chapter, and outcome (1G.13).
    log_admin_action(
        db,
        request,
        current_user,
        "FIX_CHAPTER",
        "chapter",
        str(chapter_id),
        result.get("status", "unknown"),
    )

    return RescrapeResponse(
        ok=True,
        chapter_id=chapter_id,
        delete_previous=payload.delete_previous,
        result=result,
        message=result.get("message")
        or "Re-scrape queued. The chapter's pages will refresh shortly.",
    )
