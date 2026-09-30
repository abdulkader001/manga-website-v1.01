"""Helpers for resolving provider configurations and runtime services."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, Optional, Tuple

from fastapi import Request
from sqlalchemy.orm import Session

from ..models import User, UserAPIKey
from .integration_key_vault import IntegrationKeyVault
from .provider_config import record_to_service_config
from .provider_registry import ProviderRegistryState
from .translation_service import TranslationService

__all__ = [
    "integration_vault",
    "provider_registry_state",
    "user_provider_config",
    "resolve_translation_service",
]


def integration_vault(request: Request) -> IntegrationKeyVault | None:
    vault = getattr(request.app.state, "integration_key_vault", None)
    if isinstance(vault, IntegrationKeyVault):
        return vault
    return None


def provider_registry_state(request: Request) -> ProviderRegistryState:
    state = getattr(request.app.state, "provider_registry", None)
    if isinstance(state, ProviderRegistryState):
        return state
    return ProviderRegistryState()


def _decryptor(vault: IntegrationKeyVault | None):
    if vault is None:
        return lambda value: value
    return vault.decrypt


def user_provider_config(
    db: Session,
    user: User | None,
    service: str,
    *,
    vault: IntegrationKeyVault | None = None,
) -> Optional[Dict[str, Any]]:
    if user is None:
        return None
    record = (
        db.query(UserAPIKey)
        .filter(UserAPIKey.user_id == user.id, UserAPIKey.provider == service)
        .one_or_none()
    )
    if record is None:
        return None
    decrypt = _decryptor(vault)
    return record_to_service_config(record, decrypt=decrypt)


def _env_translation_config() -> Optional[Dict[str, Any]]:
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


def _build_translation_service(
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


def resolve_translation_service(
    request: Request,
    user_translation_config: Optional[Dict[str, Any]],
    ai_provider_config: Optional[Dict[str, Any]],
) -> Tuple[TranslationService | None, Optional[Dict[str, Any]], bool]:
    """Resolve a translation service and provider configuration for OCR flows."""

    from ..api.routers import translation as translation_routes

    provider_config = (
        copy.deepcopy(user_translation_config) if user_translation_config else None
    )
    service = translation_routes.translation_service
    used_ai_fallback = False

    if service is None:
        candidate_config = provider_config
        if candidate_config is None:
            state_config = provider_registry_state(request).provider_for("translation")
            if state_config:
                candidate_config = copy.deepcopy(state_config)
        if candidate_config is None:
            env_config = _env_translation_config()
            if env_config:
                candidate_config = copy.deepcopy(env_config)

        if candidate_config:
            service = translation_routes.build_translation_service(candidate_config)
            if provider_config is None and candidate_config:
                provider_config = candidate_config

    if service is None and ai_provider_config and ai_provider_config.get("api_url"):
        ai_config = copy.deepcopy(ai_provider_config)
        service = TranslationService(
            default_api_url=ai_config.get("api_url"),
            default_api_key=ai_config.get("api_key"),
            default_provider_config=ai_config,
        )
        provider_config = ai_config
        used_ai_fallback = True

    return service, provider_config, used_ai_fallback
