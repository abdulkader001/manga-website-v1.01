"""Lightweight management endpoints (version info, etc.)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends

from ...dependencies.powers import require_power
from ...services.config_manager import load_config

router = APIRouter(tags=["management"])

SENSITIVE_PATTERNS = (
    "api_key",
    "default_api_key",
    "client_secret",
    "secret",
    "token",
    "password",
    "private_key",
    "access_key",
)

SENSITIVE_PLACEHOLDER = "***redacted***"


def _is_sensitive_key(key: Any) -> bool:
    key_str = str(key).lower()
    return any(pattern in key_str for pattern in SENSITIVE_PATTERNS)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (SENSITIVE_PLACEHOLDER if _is_sensitive_key(k) else _sanitize_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)
    return value


@router.get("/version")
def get_version() -> dict[str, str]:
    """Return the backend version string."""

    version = os.getenv("APP_VERSION", "dev")
    return {"version": version}


@router.get("/config")
def get_config(_: Any = Depends(require_power("manage_admin_settings"))) -> dict[str, Any]:
    """Return a sanitized snapshot of the admin configuration.

    Nothing in this application ever calls ``config_manager.save_config``/
    ``update_config`` to populate the backing ``admin_config.json`` file (the
    only other ``save_config`` in the codebase belongs to the unrelated
    ``ConfigManager`` in ``app/scrapers/config.py``, which persists scraper
    selectors via the ``Setting`` table, not this file). No frontend code
    calls this endpoint either. As a result this always returns ``{}`` in
    every real deployment unless something manually creates the file at
    ``ADMIN_CONFIG_PATH`` (or ``admin_config.json``) out of band. This is
    expected, not a bug — treat it as a placeholder for a write path that
    was never built rather than evidence of a misconfiguration.
    """

    cfg = load_config()
    return _sanitize_value(cfg)


__all__ = ["router"]
