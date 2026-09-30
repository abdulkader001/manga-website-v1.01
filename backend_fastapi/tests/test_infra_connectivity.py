"""Infrastructure connectivity checks for production readiness."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from sqlalchemy import create_engine, text

from backend_fastapi.app.core.celery_app import celery_app
from backend_fastapi.app.core.settings import get_settings

pytestmark = pytest.mark.infrastructure


def _get_setting(*names: str) -> str | None:
    """Return the first configured environment variable or settings attribute."""

    settings = get_settings()
    for name in names:
        env_value = os.getenv(name.upper())
        if env_value:
            return env_value
        settings_value = getattr(settings, name.lower(), None)
        if settings_value:
            return settings_value
    return None


def test_postgresql_connectivity() -> None:
    """Ensure that the configured PostgreSQL database is reachable."""

    database_url = _get_setting("DATABASE_URL", "database_url")
    if not database_url or not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL database is not configured")

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_redis_ping() -> None:
    """Confirm that Redis responds to PING commands."""

    redis_url = _get_setting("REDIS_URL", "redis_url")
    if not redis_url:
        pytest.skip("Redis URL is not configured")

    try:
        import redis
    except ImportError as exc:  # pragma: no cover - dependency missing scenario
        pytest.skip(f"redis package not installed: {exc}")

    client = redis.Redis.from_url(redis_url)
    assert client.ping() is True


def test_celery_broker_connection() -> None:
    """Verify that Celery can establish a broker connection."""

    broker_url = _get_setting("CELERY_BROKER_URL", "celery_broker_url")
    if not broker_url:
        pytest.skip("Celery broker URL is not configured")

    with celery_app.connection() as connection:
        connection.connect()
        assert connection.connected


def test_tesseract_binary_available() -> None:
    """Ensure that the OCR binary (tesseract) is present in PATH when enabled."""

    if shutil.which("tesseract") is None:
        pytest.skip("Tesseract binary not installed; local OCR features disabled")

    result = subprocess.run(
        ["which", "tesseract"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "tesseract path not reported"
