"""Chapter/page processing endpoint (SRS 2F.1): the reader-facing path
tying together cache short-circuiting, provider priority (2A), the
normalized OCR shape (2B), whole-chapter context (2C.1), and usage limits
(2E). Distinct from the legacy ad hoc ``/ocr/*`` endpoints (arbitrary
image URL in, boxes out) -- this one is keyed on chapter+page, which is
what the shared cache (1H.14) is keyed on, so caching is actually possible.
"""

from __future__ import annotations

import io
from typing import Any, Dict, Optional

import httpx
import requests
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import require_processing_user
from ...models import Chapter, User
from ...services import chapter_processing_service as cps
from ...services import platform_ceiling_service
from ...services import processing_settings_service
from ...services.content_rights import assert_series_translatable
from ...services.processing_plan import (
    CASE_USER_AI_ONLY,
    CASE_USER_OCR_TRANSLATION,
    resolve_plan,
)
from ...services.provider_resolver import (
    env_translation_config,
    integration_vault,
    provider_registry_state,
    user_provider_config,
)
from ...services import provider_management_service as pms
from ...services.translation_service import TranslationService
from ...services.ocr_service import MAX_FILE_BYTES as OCR_MAX_FILE_BYTES
from ...services.pinned_fetch import ResponseTooLarge, get_pinned_following_redirects
from ...services.url_guard import (
    validate_remote_image_url,
    validate_remote_image_url_resolved,
)
from ...utils.cdn import build_cdn_url

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

logger = structlog.get_logger("backend_fastapi.processing")

router = APIRouter(prefix="/processing", tags=["processing"])


def _platform_default(
    request: Request, db: Session, service: str
) -> Optional[Dict[str, Any]]:
    """Prefer the multi-provider priority system (2D); fall back to the
    legacy single-slot system (1H.14) when no multi-provider entries have
    been configured for this service yet."""

    chosen = pms.select_provider(db, service)
    if chosen is not None:
        vault = integration_vault(request)
        decrypt = getattr(vault, "decrypt", None)
        api_key = (
            decrypt(chosen.api_key)
            if callable(decrypt) and chosen.api_key
            else chosen.api_key
        )
        cfg = dict(chosen.config or {})
        cfg["provider"] = chosen.provider_id
        cfg["api_url"] = chosen.api_url
        cfg["api_key"] = api_key
        cfg["_provider_pk"] = chosen.id  # used to record success/failure below
        return cfg

    state = provider_registry_state(request)
    configured = state.provider_for(service)
    if configured is None and service == "translation":
        # The site's default translator (LibreTranslate etc.) set in the
        # Secret Vault / .env. Without this, a configured default was never
        # used by the reader and pages came back untranslated.
        return env_translation_config()
    return configured


def _build_translation_service(
    plan, *, primary: Optional[Dict[str, Any]], fallback: Optional[Dict[str, Any]]
) -> TranslationService:
    fallback = fallback or {}
    return TranslationService(
        default_api_url=fallback.get("api_url"),
        default_api_key=fallback.get("api_key"),
        default_provider_config=fallback,
    )


def _fetch_image_bytes_sync(url: str) -> bytes:
    # Our own compressed copies live on disk: read them directly (no network,
    # no SSRF surface, no dependence on the source site being up).
    from ...services import page_image_service

    local = page_image_service.path_from_url(url)
    if local is not None:
        return local.read_bytes()
    # Synchronous call: process_page's callables are plain sync functions so
    # the orchestrator stays trivially testable.
    #
    # This goes through the pinned fetcher rather than a bare client: the
    # earlier validate_remote_image_url call and the fetch would otherwise be
    # two separate DNS lookups, and a low-TTL host can answer the second one
    # with a link-local address. get_pinned_following_redirects re-runs the
    # SSRF check here and connects to an address it validated itself.
    #
    # max_bytes reuses OCRService's own upload ceiling -- this is the same
    # class of page image, just sourced from a URL instead of an upload, so it
    # shouldn't be allowed to buffer more into memory than an upload could.
    response = get_pinned_following_redirects(
        url,
        validate_remote_image_url_resolved,
        timeout=15.0,
        max_bytes=OCR_MAX_FILE_BYTES,
    )
    response.raise_for_status()
    return response.content


def _load_image_for_vision(image_bytes: bytes):
    if Image is None:
        return None
    try:
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None


def _series_source_language(manga) -> str:
    """Language of the text on the scraped pages, so OCR loads the right script.

    Deliberately not derived from the series *type*: a Chinese manhua scraped
    from a Korean site carries Korean lettering. Unset means "auto", which
    reads Korean, Japanese, Chinese and English together.
    """

    explicit = (getattr(manga, "language", None) or "").strip().lower() if manga else ""
    return explicit[:2] if explicit else "auto"


@router.get("/chapter/{chapter_id}/page/{page_index}")
async def process_chapter_page(
    request: Request,
    chapter_id: int,
    page_index: int,
    target: str = Query(..., min_length=1, max_length=16),
    view_cached: bool = Query(
        default=False,
        description="2C.4.3: explicitly view a cached version even if platform cache priority is off",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_processing_user),
) -> Dict[str, Any]:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="chapter_not_found"
        )

    pages = chapter.pages or []
    if page_index < 0 or page_index >= len(pages):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="page_not_found"
        )

    if chapter.manga is not None:
        assert_series_translatable(db, chapter.manga)  # SRS 1J rights gate

    vault = integration_vault(request)
    ocr_cfg = user_provider_config(db, current_user, "ocr", vault=vault)
    translation_cfg = user_provider_config(db, current_user, "translation", vault=vault)
    ai_cfg = user_provider_config(db, current_user, "ai", vault=vault)

    plan = resolve_plan(
        has_user_ocr=bool(ocr_cfg),
        has_user_translation=bool(translation_cfg),
        has_user_ai=bool(ai_cfg),
    )

    platform_ocr_cfg = _platform_default(request, db, "ocr")
    platform_translation_cfg = _platform_default(request, db, "translation")
    platform_ai_cfg = _platform_default(request, db, "ai")

    ocr_provider_config = ocr_cfg if plan.ocr_source == "user" else platform_ocr_cfg
    ai_provider_config = ai_cfg if plan.ai_source == "user" else platform_ai_cfg

    # 2E.3: a global ceiling on the platform's OWN default providers,
    # independent of each account's own limit (2E.1). Only applies when
    # this request would actually lean on a platform-default provider.
    if plan.ocr_source == "platform_default":
        await platform_ceiling_service.check_and_increment(request, db, "ocr")
    if plan.translation_source == "platform_default":
        await platform_ceiling_service.check_and_increment(request, db, "translation")

    # 2A.2's per-case translation fallback, reusing TranslationService's
    # existing primary->default fallback mechanism (also gives us the
    # 1H.8.2 used_fallback/notice disclosure for free).
    if plan.case == CASE_USER_OCR_TRANSLATION:
        primary_translation = translation_cfg
        fallback_translation = ai_provider_config  # "AI as fallback only"
    elif plan.case == CASE_USER_AI_ONLY:
        primary_translation = ai_cfg
        fallback_translation = platform_translation_cfg
    else:  # CASE_PLATFORM_DEFAULT
        primary_translation = platform_translation_cfg
        fallback_translation = platform_ai_cfg

    translation_service = _build_translation_service(
        plan, primary=primary_translation, fallback=fallback_translation
    )

    from ...services import page_image_service

    if page_image_service.is_local_url(pages[page_index]):
        if page_image_service.path_from_url(pages[page_index]) is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="missing_page_image"
            )
    else:
        image_url = build_cdn_url(pages[page_index])
        if not image_url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="missing_page_image"
            )
        guard_error = validate_remote_image_url(image_url)
        if guard_error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=guard_error)

    def ocr_runner(image_bytes: bytes, language_hint: Optional[str]) -> Dict[str, Any]:
        from .ocr import ocr_service as shared_ocr_service

        provider_pk = (ocr_provider_config or {}).get("_provider_pk")
        try:
            normalized = shared_ocr_service.extract_normalized(
                image_bytes,
                provider_config=ocr_provider_config,
                language_hint=language_hint,
            )
        except Exception as exc:
            # 2D.3/2D.4: feed the multi-provider priority system's failure
            # tracking so a genuinely broken provider is actually removed
            # from rotation, not just theoretically capable of being.
            if provider_pk:
                pms.record_failure(db, provider_pk, str(exc)[:300])
            raise
        if provider_pk:
            pms.record_success(db, provider_pk)
        return normalized

    settings = processing_settings_service.get_or_create(db, current_user.id)
    series_title = chapter.manga.title if chapter.manga else None
    genres = chapter.manga.genres if chapter.manga else None

    # 1H.8.2: disclose a fallback rather than substituting silently. A thin
    # adapter (not a monkeypatch of the shared service) captures the
    # outcome dict without changing TranslationService's own contract.
    outcome: Dict[str, Any] = {}

    class _OutcomeCapturingTranslator:
        def translate(self, text, source_lang, target_lang, provider_config=None, **kw):
            return translation_service.translate(
                text,
                source_lang,
                target_lang,
                provider_config=provider_config,
                outcome=outcome,
                **kw,
            )

        def coherence_pass(self, regions, **kw):
            # 2C.1 Stage B. Passed through rather than reimplemented so the
            # adapter never becomes the reason context is dropped.
            delegate = getattr(translation_service, "coherence_pass", None)
            if not callable(delegate):
                pass_outcome = kw.get("outcome")
                if pass_outcome is not None:
                    pass_outcome["applied"] = False
                    pass_outcome["reason"] = "service_has_no_coherence_pass"
                return None
            return delegate(regions, **kw)

    try:
        result = cps.process_page(
            db,
            chapter=chapter,
            page_index=page_index,
            target_lang=target,
            user_id=current_user.id,
            plan=plan,
            processing_settings=settings,
            fetch_image_bytes=_fetch_image_bytes_sync,
            ocr_runner=ocr_runner,
            translation_service=_OutcomeCapturingTranslator(),
            translation_provider_config=primary_translation,
            ai_provider_config=ai_provider_config,
            load_image_for_vision=_load_image_for_vision,
            reader_requested_cached=view_cached,
            series_title=series_title,
            genres=genres,
            source_lang_hint=_series_source_language(chapter.manga),
        )
    except requests.exceptions.InvalidURL as exc:
        # The page image failed re-validation at fetch time (e.g. its host now
        # resolves to a private address). Surface it as a request error, not a
        # gateway failure.
        logger.warning("processing_image_url_rejected", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_image_url"
        ) from exc
    except ResponseTooLarge as exc:
        logger.warning("processing_image_too_large", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="image_too_large",
        ) from exc
    except (httpx.HTTPError, requests.exceptions.RequestException) as exc:
        logger.error("processing_image_fetch_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="image_fetch_failed"
        ) from exc

    payload: Dict[str, Any] = {
        "chapter_id": result.chapter_id,
        "page_index": result.page_index,
        "target_lang": result.target_lang,
        "regions": result.regions,
        "cached": result.cached,
        "ocr_cached": result.ocr_cached,
        "detected_language": result.detected_language,
        "detected_script": result.detected_script,
        "reading_order_mode": result.reading_order_mode,
        "engine_tier": result.engine_tier,
        "ai_assisted_regions": result.ai_assisted_regions,
        "coherence_applied": result.coherence_applied,
    }
    if outcome.get("used_fallback"):
        # 1H.8.2: silent substitution is not acceptable.
        payload["used_fallback"] = True
        payload["notice"] = (
            "Your configured provider didn't respond, so the next option in "
            "line was used."
        )
        primary_pk = (primary_translation or {}).get("_provider_pk")
        fallback_pk = (fallback_translation or {}).get("_provider_pk")
        if primary_pk:
            pms.record_failure(db, primary_pk, "translation_fallback_used")
        if fallback_pk:
            pms.record_success(db, fallback_pk)
    else:
        primary_pk = (primary_translation or {}).get("_provider_pk")
        if primary_pk:
            pms.record_success(db, primary_pk)
    return payload


__all__ = ["router"]
