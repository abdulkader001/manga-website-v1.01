"""Translation endpoints backed by the FastAPI services."""

from __future__ import annotations

import copy
import structlog
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from ...utils.bounded_threadpool import run_in_heavy_threadpool
from ...utils import job_store
from ...tasks.translation_tasks import translate_text_job

from ...core.api_errors import ApiError, ErrorCode
from ...services.provider_registry import ProviderRegistryState
from ...services.translation_service import TranslationService
from ...schemas.translation import (
    TranslationRequest,
    TranslationResponse,
    TranslationErrorResponse,
)
from fastapi import Depends
from ...dependencies.auth import get_current_user, require_processing_user
from ...core.db import SessionLocal
from ...models import User, Manga
from ...services.content_rights import assert_series_translatable
from ...utils.circuit_breaker import cloud_circuit_breaker
from ...utils.daily_limiter import daily_user_limiter

logger = structlog.get_logger("backend_fastapi.translation")

router = APIRouter(prefix="/translation", tags=["translation"])

MAX_TEXT_LENGTH = int(os.getenv("TRANSLATION_MAX_TEXT_LENGTH", "5000"))
DEFAULT_TARGET = os.getenv("TRANSLATION_DEFAULT_TARGET_LANGUAGE")

translation_service: TranslationService | None = None


def _provider_state(request: Request) -> ProviderRegistryState:
    state = getattr(request.app.state, "provider_registry", None)
    if isinstance(state, ProviderRegistryState):
        return state
    return ProviderRegistryState()


def _env_provider_config() -> Optional[Dict[str, Any]]:
    url = (
        os.getenv("TRANSLATION_API_URL")
        or os.getenv("LIBRETRANSLATE_URL")
        or os.getenv("DEFAULT_TRANSLATION_API_URL")
    )
    if not url:
        return None

    config: Dict[str, Any] = {"api_url": url}
    api_key = (
        os.getenv("TRANSLATION_API_KEY")
        or os.getenv("LIBRETRANSLATE_API_KEY")
        or os.getenv("DEFAULT_TRANSLATION_API_KEY")
    )
    if api_key:
        config["api_key"] = api_key
    provider = os.getenv("TRANSLATION_PROVIDER") or os.getenv(
        "DEFAULT_TRANSLATION_PROVIDER"
    )
    if provider:
        config["provider"] = provider
    return config


def build_translation_service(
    config: Optional[Dict[str, Any]],
) -> TranslationService | None:
    if not config:
        return None
    api_url = config.get("api_url")
    if not api_url:
        return None
    api_key = config.get("api_key")
    return TranslationService(
        default_api_url=api_url,
        default_api_key=api_key,
        default_provider_config=config,
    )


def configure_translation_service(state: ProviderRegistryState | None = None) -> None:
    """Initialise the shared translation service from state or environment."""

    config: Optional[Dict[str, Any]] = None
    if state is not None:
        runtime = state.provider_for("translation")
        if runtime:
            config = runtime
    if config is None:
        config = _env_provider_config()

    service = build_translation_service(config)
    if service:
        logger.info(
            "Translation service initialised for %s",
            config.get("provider") or config.get("api_url"),
        )
    else:
        logger.info(
            "Translation service not configured; /api/translation/text requires admin setup."
        )

    global translation_service
    translation_service = service


# Attach helper for callers importing only the router symbol.
router.configure_translation_service = configure_translation_service  # type: ignore[attr-defined]


def _payload_override(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    override = payload.get("provider_config") or payload.get("providerConfig")
    if isinstance(override, dict):
        return copy.deepcopy(override)
    return None


def _runtime_provider(
    request: Request, payload: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    state = _provider_state(request)
    provider_key: Optional[str] = None

    raw_provider = (
        payload.get("provider")
        or payload.get("provider_id")
        or payload.get("providerId")
    )
    if isinstance(raw_provider, str) and raw_provider.strip():
        provider_key = raw_provider.strip().lower()

    if provider_key:
        candidate = state.runtime.get(provider_key)
        if candidate:
            return copy.deepcopy(candidate)

    runtime = state.provider_for("translation")
    if runtime:
        return copy.deepcopy(runtime)
    return None


def _resolve_provider_config(
    request: Request, payload: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    override = _payload_override(payload)
    if override:
        return override

    runtime = _runtime_provider(request, payload)
    if runtime:
        return runtime

    env_cfg = _env_provider_config()
    if env_cfg:
        return env_cfg

    return None


def _ensure_service(
    provider_config: Optional[Dict[str, Any]],
) -> TranslationService | None:
    if translation_service is not None:
        return translation_service
    return build_translation_service(provider_config)


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _enforce_series_translatable(payload: TranslationRequest) -> None:
    """Rights gate (SRS 1J) shared by every translation path.

    When a series context is supplied, a series marked not translatable is
    rejected outright — no path or role may bypass this. Raises ``ApiError``,
    which the global handler renders as the standard error envelope.

    Uses a short-lived session scoped to just the rights lookup rather than a
    request-scoped ``Depends(get_db)``: the translation work can occupy the
    heavy threadpool for up to ~10s, and holding a connection from the small DB
    pool for that whole time (on every request, most of which carry no
    manga_id) would starve the pool under load.
    """

    manga_id = payload.manga_id or payload.mangaId
    if manga_id is None:
        return
    with SessionLocal() as db:
        manga = db.get(Manga, manga_id)
        if manga is not None:
            assert_series_translatable(db, manga)


@router.post(
    "/text",
    response_model=TranslationResponse,
    responses={
        400: {"model": TranslationErrorResponse},
        502: {"model": TranslationErrorResponse},
        503: {"model": TranslationErrorResponse},
    },
)
async def translate_text(
    request: Request,
    payload: TranslationRequest,
    current_user: User = Depends(require_processing_user),
):
    """Translate plain text using the configured provider."""

    if current_user:
        await daily_user_limiter.check_limit(
            request, "translation", current_user.id, limit=10
        )

    text = _normalize_text(payload.text)
    if not text.strip():
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "Text to translate is required.",
            details={"reason": "missing_text"},
        )

    # Rights gate (SRS 1J) — raises ApiError, rendered by the global handler.
    _enforce_series_translatable(payload)

    if MAX_TEXT_LENGTH and len(text) > MAX_TEXT_LENGTH:
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            f"Text exceeds the {MAX_TEXT_LENGTH} character limit.",
            details={"reason": "text_too_long", "limit": MAX_TEXT_LENGTH},
        )

    target_raw = (
        payload.target or payload.target_lang or payload.targetLang or DEFAULT_TARGET
    )
    target_lang = _normalize_text(target_raw).strip()
    if not target_lang:
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "Target language is required.",
            details={"reason": "missing_target"},
        )

    source_raw = payload.source or payload.source_lang or payload.sourceLang
    source_lang = _normalize_text(source_raw).strip() or "auto"

    data = payload.model_dump(exclude_none=True)
    provider_config = _resolve_provider_config(request, data)
    service = _ensure_service(provider_config)
    if service is None:
        logger.info("Translation request rejected because no provider is configured.")
        raise ApiError(
            ErrorCode.SERVICE_UNAVAILABLE,
            # SRS 1H.8.2 exact wording.
            "No translation provider is configured. Add your own in "
            "Settings, or contact an administrator.",
            details={"reason": "translation_unavailable"},
        )

    provider_type = "translation"
    provider_name = (
        provider_config.get("provider")
        if provider_config
        else getattr(service, "provider", "default")
    )
    if not provider_name:
        provider_name = "default"

    outcome: Dict[str, Any] = {}

    async def translation_func():
        return await run_in_heavy_threadpool(
            service.translate,
            text,
            source_lang,
            target_lang,
            provider_config=provider_config,
            outcome=outcome,
        )

    try:
        translated = await cloud_circuit_breaker.execute(
            request,
            provider_type,
            provider_name,
            translation_func,
            timeout_seconds=10.0,
        )
    except Exception as exc:  # pragma: no cover - depends on external services
        if str(exc) == "Circuit breaker is open":
            raise ApiError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Provider is temporarily unavailable",
                details={"reason": "circuit_open"},
            ) from exc
        logger.exception("Translation provider raised an unexpected error")
        raise ApiError(
            ErrorCode.BAD_GATEWAY,
            "Translation provider call failed.",
            details={"reason": "translation_failed"},
        ) from exc

    # SRS 1H.8.2: when NOTHING produced a translation (no fallback bailed it
    # out) and the reason was a rejected credential, say so plainly rather
    # than silently handing back the untranslated original — 1H.8.1 "fail
    # visibly, not silently". If a fallback DID succeed, the reader still
    # gets a working translation (1H.8.1 "preserve the read path" /
    # "fail contained"); the notice below covers that case instead.
    nothing_translated = translated == text
    if nothing_translated and outcome.get("credential_rejected"):
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "Your provider rejected the request. Check your API key in Settings.",
            details={"reason": "provider_credential_rejected"},
        )

    used_fallback = bool(outcome.get("used_fallback"))
    return TranslationResponse(
        translated=translated,
        used_fallback=used_fallback,
        notice=(
            (
                "Your translation provider didn't respond, so the platform "
                "default was used."
            )
            if used_fallback
            else None
        ),
    )


class TranslationJobSubmitResponse(BaseModel):
    job_id: str
    status: str


@router.post("/jobs", response_model=TranslationJobSubmitResponse)
async def submit_translation_job(
    request: Request,
    payload: TranslationRequest,
    current_user: User = Depends(require_processing_user),
) -> TranslationJobSubmitResponse:
    """Item 39: enqueue a translation and return a job id immediately.

    The synchronous ``/translation/text`` endpoint remains available; this is the
    scalable submit-and-poll path (heavy provider work runs on the translation
    Celery queue instead of blocking the request).
    """

    if current_user:
        await daily_user_limiter.check_limit(
            request, "translation", current_user.id, limit=10
        )

    text = _normalize_text(payload.text)
    if not text.strip():
        raise HTTPException(status_code=400, detail="missing_text")
    if MAX_TEXT_LENGTH and len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail="text_too_long")

    # Rights gate (SRS 1J) — applies to the async path too. Raises ApiError,
    # rendered by the global handler.
    _enforce_series_translatable(payload)

    target_raw = (
        payload.target or payload.target_lang or payload.targetLang or DEFAULT_TARGET
    )
    target_lang = _normalize_text(target_raw).strip()
    if not target_lang:
        raise HTTPException(status_code=400, detail="missing_target")

    source_raw = payload.source or payload.source_lang or payload.sourceLang
    source_lang = _normalize_text(source_raw).strip() or "auto"

    data = payload.model_dump(exclude_none=True)
    provider_config = _resolve_provider_config(request, data)

    job_id = job_store.create_job("translation", user_id=current_user.id)
    translate_text_job.delay(job_id, text, source_lang, target_lang, provider_config)
    return TranslationJobSubmitResponse(job_id=job_id, status=job_store.STATUS_QUEUED)


@router.get("/jobs/{job_id}")
async def get_translation_job(
    job_id: str, current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Return the status/result of a translation job.

    Requires the requesting user to be the one who submitted the job.
    """

    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    if job.get("user_id") != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    return job


__all__ = [
    "router",
    "translation_service",
    "build_translation_service",
    "configure_translation_service",
]
