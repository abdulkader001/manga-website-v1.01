"""OCR API endpoints backed by the shared OCR and translation services."""

from __future__ import annotations

import structlog
from typing import Any, Dict, List, Optional

import requests
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from ...utils.bounded_threadpool import run_in_db_threadpool, run_in_heavy_threadpool
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user, require_processing_user
from ...models import User
from ...services.ocr_service import (
    MAX_FILE_BYTES,
    OCRService,
    OCRServiceError,
    OCRServiceValidationError,
)
from ...services.ocr_workflow import (
    combine_translated_text,
    normalize_overlay_boxes,
    translate_overlay_items,
)
from ...services.provider_resolver import (
    integration_vault,
    provider_registry_state,
    resolve_translation_service,
    user_provider_config,
)
from ...services.pinned_fetch import ResponseTooLarge, get_pinned_following_redirects
from ...services.url_guard import (
    validate_remote_image_url,
    validate_remote_image_url_resolved,
)
from ...core.api_errors import ApiError, ErrorCode
from ...schemas.ocr import (
    OCROverlayResponse,
    OCRTranslateOverlayRequest,
)
from ...utils.circuit_breaker import cloud_circuit_breaker
from ...utils.daily_limiter import daily_user_limiter
from ...utils import job_store
from ...tasks.ocr_tasks import translate_overlay_job

logger = structlog.get_logger("backend_fastapi.ocr")

router = APIRouter(prefix="/ocr", tags=["ocr"])

IMAGE_FETCH_TIMEOUT = 10

ocr_service = OCRService()


def configure_ocr_service(state=None) -> None:
    """Configure the shared OCR service from provider state."""

    if state is None:
        return

    try:
        provider_config = state.provider_for("ocr") if state else None
    except Exception:  # pragma: no cover - safety guard
        provider_config = None

    try:
        ocr_service.update_system_config(
            provider_config,
            local_enabled=getattr(state, "local_ocr_enabled", False),
            local_engine=getattr(state, "local_ocr_engine", None),
        )
    except OCRServiceError:
        logger.exception("Failed to apply OCR system configuration")


def _resolve_state(request: Request):
    return provider_registry_state(request)


def _resolved_provider_config(
    request: Request,
    db: Session,
    user: User | None,
    service: str,
) -> Optional[Dict[str, Any]]:
    vault = integration_vault(request)
    config = user_provider_config(db, user, service, vault=vault)
    if config:
        return config
    state = _resolve_state(request)
    runtime = state.provider_for(service)
    return runtime


async def _read_upload(file: UploadFile | None) -> bytes:
    """Read an upload, refusing it as soon as it passes the OCR size limit."""

    if file is None:
        return b""
    try:
        data = await file.read(MAX_FILE_BYTES + 1)
    finally:
        await file.close()
    if len(data) > MAX_FILE_BYTES:
        raise ApiError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            "That picture is too large.",
            details={"reason": "file_too_large", "max_bytes": MAX_FILE_BYTES},
        )
    return data


def _raise_ocr_error(detail: str) -> None:
    raise ApiError(
        ErrorCode.INTERNAL_ERROR, detail, details={"reason": "ocr_failed"}
    )


@router.post("/image")
async def extract_text(
    request: Request,
    file: UploadFile | None = File(default=None),
    lang: Optional[str] = Form(default=None),
    lang_alt: Optional[str] = Form(default=None, alias="ocrLang"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_processing_user),
) -> JSONResponse:
    if file is None:
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "No file uploaded",
            details={"reason": "file_required"},
        )

    if current_user:
        await daily_user_limiter.check_limit(request, "ocr", current_user.id, limit=10)

    image_bytes = await _read_upload(file)
    if not image_bytes:
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "No file uploaded",
            details={"reason": "file_required"},
        )

    ocr_lang = (lang_alt or lang or "").strip() or None
    provider_config = await run_in_db_threadpool(_resolved_provider_config, request, db, current_user, "ocr")
    provider_type = "ocr"
    provider_name = (
        provider_config.get("name", "default") if provider_config else "default"
    )

    if not await cloud_circuit_breaker.is_allowed(
        request, provider_type, provider_name
    ):
        raise ApiError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "Provider is temporarily unavailable",
            details={"reason": "circuit_open"},
        )

    try:
        result = await run_in_heavy_threadpool(
            ocr_service.extract,
            image_bytes,
            psm=None,
            lang=ocr_lang,
            provider_config=provider_config,
        )
        await cloud_circuit_breaker.record_success(
            request, provider_type, provider_name
        )
    except OCRServiceValidationError as exc:
        raise ApiError(
            ErrorCode.BAD_REQUEST, str(exc), details={"reason": "invalid_image"}
        ) from exc
    except OCRServiceError as exc:
        logger.exception("OCR extract failed: %s", exc)
        await cloud_circuit_breaker.record_failure(
            request, provider_type, provider_name
        )
        _raise_ocr_error(str(exc))

    items = result.get("items", []) if isinstance(result, dict) else []
    page = result.get("page", {}) if isinstance(result, dict) else {}
    text_parts = [
        item.get("text", "")
        for item in items
        if isinstance(item, dict) and item.get("text")
    ]
    text = " ".join(
        part.strip() for part in text_parts if isinstance(part, str)
    ).strip()

    payload: Dict[str, Any] = {"text": text, "items": items, "page": page}
    return JSONResponse(payload, status_code=status.HTTP_200_OK)


def _validate_image_url(image_url: str) -> None:
    if not image_url:
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "imageUrl is required",
            details={"reason": "imageUrl_required"},
        )
    error = validate_remote_image_url(image_url)
    if error:
        raise ApiError(
            ErrorCode.BAD_REQUEST, error, details={"reason": "invalid_image_url"}
        )


def _fetch_remote_image_sync(image_url: str) -> bytes:
    """Fetch a user-supplied image URL over an SSRF-pinned connection.

    The shared ``app.state.http_client`` cannot be used for this: it resolves
    the hostname itself, independently of the ``validate_remote_image_url``
    check that ran a moment earlier, which leaves a DNS-rebinding window on a
    URL any authenticated user can supply. ``get_pinned_following_redirects``
    re-validates and then connects to an address it resolved itself, per
    redirect hop.

    ``max_bytes`` matches ``OCRService``'s own upload limit so a URL-sourced
    image can't buffer far more into memory than an uploaded one ever could --
    and the ceiling is enforced while the body streams in, not after.
    """

    response = get_pinned_following_redirects(
        image_url,
        validate_remote_image_url_resolved,
        timeout=15,
        max_bytes=MAX_FILE_BYTES,
    )
    response.raise_for_status()
    return response.content


async def _fetch_remote_image(image_url: str, request: Request) -> bytes:
    try:
        # Sync under the hood (the pinning adapter is a requests transport), so
        # keep it off the event loop.
        return await run_in_threadpool(_fetch_remote_image_sync, image_url)
    except requests.exceptions.InvalidURL as exc:
        # Re-validation at fetch time rejected the URL -- e.g. the host now
        # resolves somewhere private. Report it as a bad request, matching
        # _validate_image_url.
        logger.warning("Rejected image URL at fetch time: %s", exc)
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "Image URL is not permitted",
            details={"reason": "invalid_image_url"},
        ) from exc
    except ResponseTooLarge as exc:
        logger.warning("Rejected oversized remote image: %s", exc)
        raise ApiError(
            ErrorCode.PAYLOAD_TOO_LARGE,
            "Image exceeds the maximum allowed size",
            details={"reason": "image_too_large"},
        ) from exc
    except requests.exceptions.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "?"
        logger.error("HTTP error fetching image: %s", exc)
        raise ApiError(
            ErrorCode.BAD_GATEWAY,
            f"HTTP {status_code} error",
            details={"reason": "image_fetch_failed"},
        ) from exc
    except requests.exceptions.RequestException as exc:
        logger.error("Request error fetching image: %s", exc)
        raise ApiError(
            ErrorCode.BAD_GATEWAY,
            "Connection error",
            details={"reason": "image_fetch_failed"},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch image: %s", exc)
        raise ApiError(
            ErrorCode.BAD_GATEWAY, str(exc), details={"reason": "image_fetch_failed"}
        ) from exc


def _ocr_overlay_response(result: Dict[str, Any]) -> Dict[str, Any]:
    items = result.get("items", []) if isinstance(result, dict) else []
    page = result.get("page", {}) if isinstance(result, dict) else {}
    metadata = result.get("metadata") if isinstance(result, dict) else None
    boxes = normalize_overlay_boxes(items, page)
    payload: Dict[str, Any] = {"boxes": boxes}
    if isinstance(metadata, dict):
        payload["metadata"] = metadata
    return payload


@router.get("/overlay", response_model=OCROverlayResponse)
async def overlay_boxes(
    request: Request,
    image_url_param: str | None = Query(default=None, alias="imageUrl"),
    image_url_alt: str | None = Query(default=None, alias="image_url"),
    lang: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_processing_user),
):
    image_url = (image_url_param or image_url_alt or "").strip()
    _validate_image_url(image_url)

    image_bytes = await _fetch_remote_image(image_url, request)

    provider_config = await run_in_db_threadpool(_resolved_provider_config, request, db, current_user, "ocr")
    ocr_lang = (lang or "").strip() or None

    try:
        result = await run_in_heavy_threadpool(
            ocr_service.extract,
            image_bytes,
            psm=None,
            lang=ocr_lang,
            provider_config=provider_config,
        )
    except OCRServiceValidationError as exc:
        raise ApiError(
            ErrorCode.BAD_REQUEST, str(exc), details={"reason": "invalid_image"}
        ) from exc
    except OCRServiceError as exc:
        logger.exception("OCR overlay failed: %s", exc)
        _raise_ocr_error(str(exc))

    return OCROverlayResponse(**_ocr_overlay_response(result))


def _translate_payload_defaults(data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {
        "image_url": (data.get("imageUrl") or data.get("image_url") or "").strip(),
        "target_lang": (data.get("target") or data.get("targetLang") or "en").strip()
        or "en",
        "source_lang": (data.get("source") or data.get("sourceLang") or "").strip()
        or None,
        "ocr_lang": (data.get("lang") or data.get("ocrLang") or "").strip() or None,
    }


def _extract_language_metadata(metadata: Dict[str, Any]) -> Optional[str]:
    detected = metadata.get("detected_language") if isinstance(metadata, dict) else None
    if isinstance(detected, dict):
        code = detected.get("code")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return None


async def _run_ocr_via_breaker(
    request: Request, provider_name: str, ocr_func, *, context: str
) -> Dict[str, Any]:
    try:
        return await cloud_circuit_breaker.execute(
            request, "ocr", provider_name, ocr_func, timeout_seconds=15.0
        )
    except Exception as exc:
        if str(exc) == "Circuit breaker is open":
            raise ApiError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Provider is temporarily unavailable",
                details={"reason": "circuit_open"},
            ) from exc
        if isinstance(exc, OCRServiceValidationError):
            raise ApiError(
                ErrorCode.BAD_REQUEST, str(exc), details={"reason": "invalid_image"}
            ) from exc
        if isinstance(exc, OCRServiceError):
            logger.exception("OCR %s failed: %s", context, exc)
            raise ApiError(
                ErrorCode.INTERNAL_ERROR, str(exc), details={"reason": "ocr_failed"}
            ) from exc
        logger.exception("OCR %s failed with unexpected error: %s", context, exc)
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            "An unexpected error occurred during OCR extraction.",
            details={"reason": "ocr_failed"},
        ) from exc


async def _translate_response(
    items: List[Dict[str, Any]],
    page: Dict[str, Any],
    metadata: Dict[str, Any],
    *,
    translation_service,
    provider_config,
    target_lang: str,
    source_lang: Optional[str],
    used_ai: bool,
) -> Dict[str, Any]:
    boxes, metadata, errors = await run_in_heavy_threadpool(
        translate_overlay_items,
        items,
        page,
        metadata,
        translation_service=translation_service,
        provider_config=provider_config,
        target_lang=target_lang,
        source_lang=source_lang,
        used_ai_fallback=used_ai,
    )
    return {"boxes": boxes, "metadata": metadata, "errors": errors}


@router.post("/translate-overlay", response_model=OCROverlayResponse)
async def translate_overlay(
    request: Request,
    payload: OCRTranslateOverlayRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_processing_user),
):
    data = payload.model_dump(exclude_none=True)
    defaults = _translate_payload_defaults(data)
    image_url = defaults["image_url"] or ""

    _validate_image_url(image_url)

    image_bytes = await _fetch_remote_image(image_url, request)

    ocr_config = await run_in_db_threadpool(_resolved_provider_config, request, db, current_user, "ocr")
    ocr_lang = defaults["ocr_lang"]
    provider_name = ocr_config.get("name", "default") if ocr_config else "default"

    async def ocr_func():
        return await run_in_heavy_threadpool(
            ocr_service.extract,
            image_bytes,
            psm=None,
            lang=ocr_lang,
            provider_config=ocr_config,
        )

    ocr_result = await _run_ocr_via_breaker(
        request, provider_name, ocr_func, context="translate-overlay"
    )

    items = ocr_result.get("items", []) if isinstance(ocr_result, dict) else []
    page = ocr_result.get("page", {}) if isinstance(ocr_result, dict) else {}
    metadata = ocr_result.get("metadata") if isinstance(ocr_result, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}

    translation_config = await run_in_db_threadpool(
        user_provider_config, db, current_user, "translation", vault=integration_vault(request)
    )
    ai_config = await run_in_db_threadpool(
        user_provider_config, db, current_user, "ai", vault=integration_vault(request)
    )
    translation_service, provider_config, used_ai = resolve_translation_service(
        request,
        translation_config,
        ai_config,
    )

    detected_code = _extract_language_metadata(metadata)
    source_lang = defaults["source_lang"] or detected_code or "auto"
    target_lang = defaults["target_lang"] or "en"

    response_payload = await _translate_response(
        items,
        page,
        metadata,
        translation_service=translation_service,
        provider_config=provider_config,
        target_lang=target_lang,
        source_lang=source_lang,
        used_ai=used_ai,
    )

    return OCROverlayResponse(**response_payload)


@router.post("/translate-upload", response_model=OCROverlayResponse)
async def translate_upload(
    request: Request,
    file: UploadFile | None = File(default=None),
    target: Optional[str] = Form(default=None),
    target_lang_alt: Optional[str] = Form(default=None, alias="targetLang"),
    lang: Optional[str] = Form(default=None),
    lang_alt: Optional[str] = Form(default=None, alias="ocrLang"),
    source: Optional[str] = Form(default=None),
    source_alt: Optional[str] = Form(default=None, alias="sourceLang"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_processing_user),
):
    if file is None:
        raise ApiError(
            ErrorCode.BAD_REQUEST, "No file uploaded", details={"reason": "file_required"}
        )

    image_bytes = await _read_upload(file)
    if not image_bytes:
        raise ApiError(
            ErrorCode.BAD_REQUEST, "No file uploaded", details={"reason": "file_required"}
        )

    target_lang = (target_lang_alt or target or "en").strip() or "en"
    ocr_lang = (lang_alt or lang or "").strip() or None
    source_override = (source_alt or source or "").strip() or None

    provider_config = await run_in_db_threadpool(_resolved_provider_config, request, db, current_user, "ocr")
    provider_name = (
        provider_config.get("name", "default") if provider_config else "default"
    )

    async def ocr_func():
        return await run_in_heavy_threadpool(
            ocr_service.extract,
            image_bytes,
            psm=None,
            lang=ocr_lang,
            provider_config=provider_config,
        )

    ocr_result = await _run_ocr_via_breaker(
        request, provider_name, ocr_func, context="translate-upload"
    )

    items = ocr_result.get("items", []) if isinstance(ocr_result, dict) else []
    page = ocr_result.get("page", {}) if isinstance(ocr_result, dict) else {}
    metadata = ocr_result.get("metadata") if isinstance(ocr_result, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}

    detected_code = _extract_language_metadata(metadata)
    source_lang = source_override or detected_code or "auto"

    vault = integration_vault(request)
    translation_config = await run_in_db_threadpool(
        user_provider_config, db, current_user, "translation", vault=vault
    )
    ai_config = await run_in_db_threadpool(
        user_provider_config, db, current_user, "ai", vault=vault
    )
    translation_service, provider_config, used_ai = resolve_translation_service(
        request,
        translation_config,
        ai_config,
    )

    response_payload = await _translate_response(
        items,
        page,
        metadata,
        translation_service=translation_service,
        provider_config=provider_config,
        target_lang=target_lang,
        source_lang=source_lang,
        used_ai=used_ai,
    )
    response_payload["text"] = combine_translated_text(response_payload["boxes"])

    return OCROverlayResponse(**response_payload)


class OverlayTranslateJobRequest(BaseModel):
    items: List[Dict[str, Any]]
    page: Dict[str, Any] = {}
    target: str
    source: Optional[str] = None
    provider_config: Optional[Dict[str, Any]] = None


class OverlayJobSubmitResponse(BaseModel):
    job_id: str
    status: str


@router.post("/overlay-jobs", response_model=OverlayJobSubmitResponse)
async def submit_overlay_translation_job(
    request: Request,
    payload: OverlayTranslateJobRequest,
    current_user: User = Depends(require_processing_user),
) -> OverlayJobSubmitResponse:
    """Item 39: translate already-extracted overlay boxes as a background job.

    Returns a job id immediately (the provider work runs on the ``ocr`` Celery
    queue). The synchronous ``/ocr/translate-overlay`` endpoint is unchanged.
    """

    if current_user:
        await daily_user_limiter.check_limit(request, "ocr", current_user.id, limit=20)
    if not payload.items:
        raise HTTPException(status_code=400, detail="items_required")
    if not payload.target.strip():
        raise HTTPException(status_code=400, detail="missing_target")

    job_id = job_store.create_job("ocr_overlay", user_id=current_user.id)
    translate_overlay_job.delay(
        job_id,
        payload.items,
        payload.page,
        payload.target,
        payload.source,
        payload.provider_config,
    )
    return OverlayJobSubmitResponse(job_id=job_id, status=job_store.STATUS_QUEUED)


@router.get("/jobs/{job_id}")
async def get_ocr_job(
    job_id: str, current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Return the status/result of an OCR-overlay translation job.

    Requires the requesting user to be the one who submitted the job.
    """

    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    if job.get("user_id") != current_user.id:
        raise HTTPException(status_code=403, detail="forbidden")
    return job


router.configure_ocr_service = configure_ocr_service  # type: ignore[attr-defined]

__all__ = ["router", "ocr_service", "configure_ocr_service"]
