"""Routes for managing third-party integration API keys."""

from __future__ import annotations

import structlog
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import User, UserAPIKey
from ...schemas.integrations import IntegrationAddRequest, IntegrationRemoveRequest
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

    record = (
        db.query(UserAPIKey)
        .filter_by(user_id=current_user.id, provider=service)
        .one_or_none()
    )
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
