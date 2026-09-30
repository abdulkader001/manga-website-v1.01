"""Provider and integration bootstrap helpers."""

from __future__ import annotations

import structlog
import os

from fastapi import FastAPI

from ..api.routers import ocr_router, translation_router
from ..services.integration_key_vault import IntegrationKeyVault
from ..services.provider_registry import (
    ProviderRegistryState,
    check_configured_providers,
)

logger = structlog.get_logger("backend_fastapi.app")


def initialize_integration_vault(app: FastAPI) -> None:
    """Create and attach the integration vault from environment secret."""

    integration_secret = os.getenv("INTEGRATIONS_SECRET")
    if not integration_secret:
        raise RuntimeError(
            "INTEGRATIONS_SECRET environment variable is required for encrypted integration storage."
        )

    try:
        vault = IntegrationKeyVault.from_secret(integration_secret)
    except ValueError as exc:  # pragma: no cover - validated preflight
        raise RuntimeError("INTEGRATIONS_SECRET is invalid") from exc

    app.state.integration_key_vault = vault
    logger.info("Integration key vault initialised for encrypted credential storage")


def initialize_provider_state(app: FastAPI, settings) -> dict[str, bool]:
    """Configure OCR/translation providers and return feature flags."""

    server_ocr_enabled = bool(settings.ocr_enabled)
    server_translation_enabled = bool(settings.translation_enabled)

    if server_ocr_enabled or server_translation_enabled:
        provider_state: ProviderRegistryState = check_configured_providers(
            vault=getattr(app.state, "integration_key_vault", None)
        )
    else:
        provider_state = ProviderRegistryState()
        logger.info(
            "✅ Client-side OCR/Translation mode enabled — no server OCR initialized."
        )

    app.state.provider_registry = provider_state
    translation_router.configure_translation_service(provider_state)
    try:
        ocr_router.configure_ocr_service(provider_state)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to configure OCR service from provider state")

    return {"ocr": server_ocr_enabled, "translation": server_translation_enabled}
