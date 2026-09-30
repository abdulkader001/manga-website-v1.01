"""Runtime registry for OCR/translation/AI provider configuration."""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models import ProviderCredentials
from .provider_config import mask_api_key
from .system_settings_service import get_or_create_system_settings

logger = structlog.get_logger(__name__)


@dataclass
class ProviderRegistryState:
    """In-memory snapshot of configured provider credentials."""

    runtime: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    masked: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    system_settings: Dict[str, Any] = field(default_factory=dict)

    def provider_for(self, service: str) -> Optional[Dict[str, Any]]:
        return self.runtime.get(service)

    def masked_provider_for(self, service: str) -> Dict[str, Any]:
        return self.masked.get(service, {})

    @property
    def local_ocr_enabled(self) -> bool:
        return bool(self.system_settings.get("local_ocr_enabled"))

    @property
    def local_ocr_engine(self) -> Optional[str]:
        engine = self.system_settings.get("local_ocr_engine")
        if isinstance(engine, str) and engine.strip():
            return engine.strip()
        return None

    def to_public_payload(self) -> Dict[str, Any]:
        return {
            "providers": self.masked,
            "system": {
                "localOcrEnabled": self.local_ocr_enabled,
                "localOcrEngine": self.local_ocr_engine,
            },
        }

    def system_provider_snapshot(self) -> Dict[str, Dict[str, Any]]:
        summary: Dict[str, Dict[str, Any]] = {}
        for service, config in self.runtime.items():
            if not isinstance(config, dict):
                continue
            provider_id = config.get("provider") or config.get("provider_id")
            api_url = config.get("api_url")
            model = config.get("model")
            headers = (
                config.get("headers")
                if isinstance(config.get("headers"), dict)
                else None
            )

            entry: Dict[str, Any] = {
                "configured": bool(api_url or provider_id or model),
            }
            if isinstance(provider_id, str) and provider_id.strip():
                entry["provider"] = provider_id.strip()
            if isinstance(api_url, str) and api_url.strip():
                entry["apiUrl"] = api_url.strip()
            if isinstance(model, str) and model.strip():
                entry["model"] = model.strip()
            if config.get("api_key"):
                entry["hasApiKey"] = True
            if headers:
                entry["headers"] = sorted(str(key) for key in headers.keys())

            summary[service] = entry

        return summary


def _decrypt(api_key: Optional[str], vault) -> Optional[str]:
    if not api_key:
        return None
    if vault is None:
        return api_key
    decrypt = getattr(vault, "decrypt", None)
    if callable(decrypt):
        return decrypt(api_key)
    return api_key


def _normalize_config(raw: Dict[str, Any], api_key: Optional[str]) -> Dict[str, Any]:
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else None
    config = {
        "provider": raw.get("provider_id") or raw.get("provider") or "custom",
        "api_key": api_key,
        "api_url": raw.get("api_url"),
        "model": raw.get("model"),
        "headers": headers,
    }
    return config


def _masked_payload(raw: Dict[str, Any], api_key: Optional[str]) -> Dict[str, Any]:
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else None
    return {
        "provider": raw.get("provider_id") or raw.get("provider") or "custom",
        "apiKey": mask_api_key(api_key),
        "apiUrl": raw.get("api_url"),
        "model": raw.get("model"),
        "headers": headers,
    }


def _load_provider_records(session: Session, vault) -> ProviderRegistryState:
    records = (
        session.query(ProviderCredentials)
        .filter(ProviderCredentials.is_system.is_(True))
        .all()
    )

    runtime: Dict[str, Dict[str, Any]] = {}
    masked: Dict[str, Dict[str, Any]] = {}

    for record in records:
        if not record.enabled:
            continue
        provider_name = (record.provider_name or "").strip().lower()
        if not provider_name:
            continue
        raw_cfg = record.config or {}
        if "provider_id" not in raw_cfg:
            raw_cfg["provider_id"] = record.provider
        decrypted_key = _decrypt(record.api_key, vault)
        runtime[provider_name] = _normalize_config(raw_cfg, decrypted_key)
        masked[provider_name] = _masked_payload(raw_cfg, decrypted_key)

    return ProviderRegistryState(runtime=runtime, masked=masked)


def check_configured_providers(*, vault=None) -> ProviderRegistryState:
    """Load system provider credentials into memory and log status."""

    with SessionLocal() as session:
        settings = get_or_create_system_settings(session)
        state = _load_provider_records(session, vault)
        state.system_settings = {
            "local_ocr_enabled": bool(settings.local_ocr_enabled),
            "local_ocr_engine": settings.local_ocr_engine,
        }

    if not state.runtime:
        logger.info(
            "OCR/Translation services will be initialized dynamically by admin/user configuration."
        )
    else:
        logger.info("System providers configured: %s", sorted(state.runtime.keys()))

    return state


__all__ = ["ProviderRegistryState", "check_configured_providers"]
