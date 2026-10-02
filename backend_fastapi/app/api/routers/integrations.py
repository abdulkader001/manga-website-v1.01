"""Routes for managing third-party integration API keys."""

from __future__ import annotations

import time
from typing import Any, Dict

import structlog

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import User, UserAPIKey
from ...schemas.integrations import (
    IntegrationAddRequest,
    IntegrationRemoveRequest,
    IntegrationTestRequest,
)
from ...services.provider_resolver import user_provider_config
from ...services.provider_config import (
    ProviderConfigError,
    default_response_payload,
    normalize_provider_payload,
    record_to_response,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])

logger = structlog.get_logger("backend_fastapi.routers.integrations")

SUPPORTED_SERVICES = {"ocr", "translation", "ai"}


def _vault(request: Request):
    return getattr(request.app.state, "integration_key_vault", None)


def _serialize(request: Request, records) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {
        service: default_response_payload(service) for service in SUPPORTED_SERVICES
    }
    decryptor = getattr(_vault(request), "decrypt", None)
    for record in records:
        if record.provider not in SUPPORTED_SERVICES:
            continue
        result[record.provider] = record_to_response(record, decrypt=decryptor)
    return result


def _validate_runtime_requirements(service: str, payload: Dict[str, Any]) -> None:
    provider_id = payload.get("provider_id")
    api_key = payload.get("api_key")
    config = payload.get("config") or {}

    if not provider_id:
        raise ValueError("Provider ID is required.")

    requires_key = provider_id not in {"system", "tesseract_local"}
    if requires_key and not api_key:
        raise ValueError("An API key is required for this provider.")

    if provider_id in {
        "custom",
        "openai_gpt_3_5",
        "openrouter_free",
        "google_gemini",
        "deepseek_chat",
        "qwen_plus",
    }:
        api_url = config.get("api_url") if isinstance(config, dict) else None
        if not api_url:
            raise ValueError("An API URL is required for this provider.")

    if service == "ai" and provider_id == "tesseract_local":
        raise ValueError("Tesseract cannot be used for AI providers.")


@router.get("/list")
def list_integrations(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Dict[str, Any]]:
    """Return integration configuration for the current user."""

    records = db.query(UserAPIKey).filter_by(user_id=current_user.id).all()
    return {"integrations": _serialize(request, records)}


@router.post("/add")
def add_integration(
    request: Request,
    payload: IntegrationAddRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create or update an integration provider for the user."""

    service = str(payload.service or "").strip().lower()
    provider_payload = payload.config or payload.payload or {}

    if service not in SUPPORTED_SERVICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_service"
        )

    try:
        normalized = normalize_provider_payload(service, provider_payload)
    except ProviderConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="empty_payload"
        )

    existing = (
        db.query(UserAPIKey)
        .filter_by(user_id=current_user.id, provider=service)
        .one_or_none()
    )
    # Re-saving the same provider without retyping the key (the form only
    # ever shows a masked key) keeps the stored one instead of wiping it.
    if (
        not normalized.get("api_key")
        and existing is not None
        and existing.api_key
        and (existing.config or {}).get("provider_id") == normalized.get("provider_id")
    ):
        decrypt = getattr(_vault(request), "decrypt", None)
        normalized["api_key"] = decrypt(existing.api_key) if callable(decrypt) else existing.api_key

    try:
        _validate_runtime_requirements(service, normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    vault = _vault(request)
    plain_key = normalized.get("api_key")
    if vault and plain_key:
        encrypted_key = vault.encrypt(plain_key)
    else:
        encrypted_key = plain_key

    record = existing
    if not record:
        record = UserAPIKey(user_id=current_user.id, provider=service)
        db.add(record)

    record.api_key = encrypted_key
    record.config = normalized.get("config")
    db.commit()
    db.refresh(record)

    response = record_to_response(record, decrypt=getattr(vault, "decrypt", None))
    logger.info(
        "User %s updated %s integration with provider=%s",
        current_user.id,
        service,
        response.get("provider"),
    )
    return {"integration": response}


@router.delete("/remove")
def remove_integration(
    request: Request,
    payload: IntegrationRemoveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete an integration provider for the user."""

    service = str(payload.service or "").strip().lower()
    if service not in SUPPORTED_SERVICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_service"
        )

    record = (
        db.query(UserAPIKey)
        .filter_by(user_id=current_user.id, provider=service)
        .one_or_none()
    )
    if not record:
        return {"status": "ok", "removed": False}

    db.delete(record)
    db.commit()

    logger.info("User %s removed %s integration provider", current_user.id, service)
    return {"status": "ok", "removed": True}


def _test_translation(config: Dict[str, Any]) -> str:
    from ...services.translation_service import TranslationService

    service = TranslationService(default_api_url=None, timeout_s=15)
    # _perform_translation raises with the HTTP status instead of silently
    # returning the source text, which is what a connection test needs.
    return service._perform_translation(
        text="안녕하세요", source_lang="ko", target_lang="en", provider_config=config
    )


def _test_ocr(config: Dict[str, Any]) -> str:
    from .ocr import ocr_service

    provider = (config.get("provider") or "").lower()
    if provider in {"tesseract_local", "system", ""} and not config.get("api_url"):
        if ocr_service.probe_local():
            return "Built-in Tesseract engine is installed and enabled."
        raise RuntimeError(
            "The built-in OCR engine is not available on this server. "
            "Ask the admin to enable local OCR, or add your own OCR API."
        )
    import requests

    response = requests.get(config["api_url"], timeout=10)
    if response.status_code >= 500:
        raise RuntimeError(f"OCR endpoint answered HTTP {response.status_code}.")
    return f"OCR endpoint reachable (HTTP {response.status_code})."


@router.post("/test")
async def test_integration(
    request: Request,
    payload: IntegrationTestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Run one real request against the reader's *saved* provider."""

    from starlette.concurrency import run_in_threadpool

    from ...utils.endpoint_limiter import async_endpoint_limiter

    await async_endpoint_limiter.check_limit(
        request, f"integration_test:{current_user.id}", limit=20, window_seconds=600
    )
    service = str(payload.service or "").strip().lower()
    if service not in SUPPORTED_SERVICES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_service")

    from ...utils.bounded_threadpool import run_in_db_threadpool

    config = await run_in_db_threadpool(
        user_provider_config, db, current_user, service, vault=_vault(request)
    )
    if not config:
        return {"success": False, "message": "Save this provider first, then test it."}

    started = time.monotonic()
    try:
        if service == "ocr":
            detail = await run_in_threadpool(_test_ocr, config)
        else:
            translated = await run_in_threadpool(_test_translation, config)
            detail = f'Translated "안녕하세요" -> "{translated}".'
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        if status_code in (401, 403):
            message = "The provider rejected the API key (HTTP %s)." % status_code
        elif status_code == 404:
            message = "The endpoint URL or model name was not found (HTTP 404)."
        elif status_code == 429:
            message = "The provider is rate-limiting this key (HTTP 429). Try again later."
        else:
            message = f"Connection failed: {str(exc)[:200]}"
        return {"success": False, "message": message}
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        return {
            "success": True,
            "message": detail,
            "latencyMs": int((time.monotonic() - started) * 1000),
        }

    return await run_in_db_threadpool(_work)
