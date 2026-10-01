"""Provider configuration helpers without Flask dependencies."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Optional
from urllib.parse import urlparse

from ..models import UserAPIKey

PROVIDER_DEFAULTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    "ocr": {
        "ocr_space_free": {"api_url": "https://api.ocr.space/parse/image"},
        "google_cloud_vision": {
            "api_url": "https://vision.googleapis.com/v1/images:annotate"
        },
        "azure_computer_vision": {
            "api_url": "https://api.cognitive.microsoft.com/vision/v3.2/ocr"
        },
        "amazon_textract": {"api_url": "https://textract.us-east-1.amazonaws.com"},
        "ibm_watson_vision": {
            "api_url": "https://api.us-south.visual-recognition.watson.cloud.ibm.com/v3/detect_text"
        },
        "tesseract_local": {},
        "system": {},
        "custom": {},
    },
    "translation": {
        "libretranslate_demo": {"api_url": "https://libretranslate.de/translate"},
        "google_cloud_translate": {
            "api_url": "https://translation.googleapis.com/language/translate/v2"
        },
        "azure_translator": {
            "api_url": "https://api.cognitive.microsofttranslator.com/translate"
        },
        "amazon_translate": {"api_url": "https://translate.amazonaws.com/"},
        "ibm_watson_translate": {
            "api_url": "https://api.us-south.language-translator.watson.cloud.ibm.com/v3/translate"
        },
        "argos_translate_local": {},
        "system": {},
        "custom": {},
    },
    "ai": {
        "openrouter_free": {"api_url": "https://openrouter.ai/api/v1/chat/completions"},
        "openai_gpt_3_5": {
            "api_url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-3.5-turbo",
        },
        "google_gemini": {
            "api_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            "model": "gemini-2.5-flash",
            "headers": {"Content-Type": "application/json"},
        },
        "deepseek_chat": {
            "api_url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-chat",
            "headers": {"Content-Type": "application/json"},
        },
        "qwen_plus": {
            "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "model": "qwen-plus",
            "headers": {"Content-Type": "application/json"},
        },
        "system": {},
        "custom": {},
    },
    # The scraper-creation AI (SRS 1G.8.7): a dedicated, single-purpose AI
    # configured only by the Permanent Administrator. Provider-neutral — any
    # capable provider plugs in via configuration.
    "scraper_ai": {
        "google_gemini": {
            "api_url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            "model": "gemini-2.5-flash",
            "headers": {"Content-Type": "application/json"},
        },
        "openai": {
            "api_url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
        },
        "anthropic_compatible": {},
        "custom": {},
        "system": {},
    },
}

_PROVIDER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ProviderConfigError(ValueError):
    """Raised when provider payload fails validation."""


def _clean_str(
    value: Any, *, allow_empty: bool = False, max_length: int = 255
) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderConfigError("value must be a string")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        return None
    if len(cleaned) > max_length:
        raise ProviderConfigError("value too long")
    return cleaned


def _validate_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderConfigError("apiUrl must be an absolute http(s) URL")
    return url


def _clean_headers(headers: Any) -> Optional[Dict[str, str]]:
    if headers is None:
        return None
    if not isinstance(headers, dict):
        raise ProviderConfigError("headers must be an object")
    cleaned: Dict[str, str] = {}
    for key, value in headers.items():
        if value is None:
            continue
        key_clean = _clean_str(key, allow_empty=False, max_length=60)
        if not key_clean:
            raise ProviderConfigError("header keys must be non-empty strings")
        if not isinstance(value, str):
            raise ProviderConfigError("header values must be strings")
        val_clean = value.strip()
        cleaned[key_clean] = val_clean
    return cleaned or None


def normalize_provider_payload(service: str, payload: Any) -> Optional[Dict[str, Any]]:
    """Validate incoming payload for a provider selection."""

    if payload is None or payload == "":
        return None

    if isinstance(payload, str):
        payload = {"apiKey": payload}

    if not isinstance(payload, dict):
        raise ProviderConfigError("provider payload must be an object")

    provider_id_raw = payload.get("provider") or payload.get("provider_id") or "custom"
    if not isinstance(provider_id_raw, str):
        raise ProviderConfigError("provider must be a string")
    provider_id = provider_id_raw.strip().lower()
    if not provider_id:
        raise ProviderConfigError("provider is required")
    if not _PROVIDER_ID_RE.match(provider_id):
        raise ProviderConfigError("provider contains invalid characters")

    api_key = payload.get("apiKey")
    if api_key is None:
        api_key = payload.get("api_key")
    api_key_clean = _clean_str(api_key, allow_empty=False, max_length=255)

    api_url = payload.get("apiUrl")
    if api_url is None:
        api_url = payload.get("api_url")
    api_url_clean = _clean_str(api_url, allow_empty=False, max_length=500)
    api_url_valid = _validate_url(api_url_clean)

    model = payload.get("model")
    model_clean = _clean_str(model, allow_empty=False, max_length=120)

    headers = payload.get("headers")
    headers_clean = _clean_headers(headers)

    defaults = PROVIDER_DEFAULTS.get(service, {}).get(provider_id, {})

    config: Dict[str, Any] = {"provider_id": provider_id}
    effective_url = api_url_valid or defaults.get("api_url")
    if effective_url:
        config["api_url"] = effective_url
    effective_model = model_clean or defaults.get("model")
    if effective_model:
        config["model"] = effective_model
    if headers_clean:
        config["headers"] = headers_clean
    else:
        default_headers = defaults.get("headers")
        if isinstance(default_headers, dict) and default_headers:
            config["headers"] = default_headers

    if provider_id == "system" and not api_key_clean and len(config) == 1:
        return None

    return {
        "provider_id": provider_id,
        "api_key": api_key_clean,
        "config": config,
    }


def _resolve_decryptor(
    decrypt: Optional[Callable[[Optional[str]], Optional[str]]],
) -> Callable[[Optional[str]], Optional[str]]:
    if decrypt is not None:
        return decrypt
    return lambda value: value


def mask_api_key(value: Optional[str], *, show_last: int = 4) -> Optional[str]:
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) <= show_last:
        return "*" * len(trimmed)
    visible = trimmed[-show_last:]
    return "*" * (len(trimmed) - len(visible)) + visible


def record_to_response(
    record: UserAPIKey,
    *,
    decrypt: Optional[Callable[[Optional[str]], Optional[str]]] = None,
) -> Dict[str, Any]:
    cfg = record.config or {}
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else None
    decryptor = _resolve_decryptor(decrypt)
    api_key = mask_api_key(decryptor(record.api_key))
    return {
        "provider": cfg.get("provider_id", "custom"),
        "apiKey": api_key,
        "apiUrl": cfg.get("api_url"),
        "model": cfg.get("model"),
        "headers": headers,
    }


def record_to_service_config(
    record: UserAPIKey,
    *,
    decrypt: Optional[Callable[[Optional[str]], Optional[str]]] = None,
) -> Dict[str, Any]:
    cfg = record.config or {}
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else None
    decryptor = _resolve_decryptor(decrypt)
    return {
        "provider": cfg.get("provider_id"),
        "api_key": decryptor(record.api_key),
        "api_url": cfg.get("api_url"),
        "model": cfg.get("model"),
        "headers": headers,
    }


def serialize_provider_records(
    records: Iterable[UserAPIKey],
    *,
    decrypt: Optional[Callable[[Optional[str]], Optional[str]]] = None,
) -> Dict[str, Dict[str, Any]]:
    payload: Dict[str, Dict[str, Any]] = {}
    decryptor = _resolve_decryptor(decrypt)
    for record in records:
        info = record_to_response(record, decrypt=decryptor)
        payload[record.provider] = info
    return payload


def record_secret(
    record: UserAPIKey,
    *,
    decrypt: Optional[Callable[[Optional[str]], Optional[str]]] = None,
) -> Optional[str]:
    decryptor = _resolve_decryptor(decrypt)
    return decryptor(record.api_key)


def default_response_payload(service: str) -> Dict[str, Any]:
    defaults = PROVIDER_DEFAULTS.get(service, {})
    default_provider = "system" if "system" in defaults else "system"
    default_cfg = defaults.get(default_provider, {})
    return {
        "provider": default_provider,
        "apiKey": None,
        "apiUrl": default_cfg.get("api_url"),
        "model": default_cfg.get("model"),
        "headers": default_cfg.get("headers"),
    }


__all__ = [
    "PROVIDER_DEFAULTS",
    "ProviderConfigError",
    "mask_api_key",
    "default_response_payload",
    "normalize_provider_payload",
    "record_to_response",
    "record_to_service_config",
    "serialize_provider_records",
    "record_secret",
]
