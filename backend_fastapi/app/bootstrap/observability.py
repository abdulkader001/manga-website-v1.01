"""Observability initialization helpers."""

from __future__ import annotations

import structlog
import os

logger = structlog.get_logger("backend_fastapi.app")

_sentry_initialized = False


def get_bool_env(name: str, *, default: bool = False) -> bool:
    """Return a boolean from the environment variable ``name``."""

    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def init_sentry(settings) -> None:
    """Initialize Sentry once per process when enabled."""

    global _sentry_initialized
    if _sentry_initialized:
        return

    if not get_bool_env("ENABLE_SENTRY", default=True):
        logger.info("Sentry SDK disabled via ENABLE_SENTRY")
        _sentry_initialized = True
        return

    dsn = settings.sentry_dsn
    if not dsn:
        logger.info(
            "ENABLE_SENTRY is true but SENTRY_DSN is missing; skipping Sentry initialization."
        )
        _sentry_initialized = True
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.sentry_environment,
            release=settings.release,
            integrations=[FastApiIntegration()],
        )
        logger.info(
            "Sentry SDK initialized (environment=%s)", settings.sentry_environment
        )
    except Exception:  # pragma: no cover - defensive logging helper
        logger.exception("Failed to initialize Sentry SDK")
    finally:
        _sentry_initialized = True
