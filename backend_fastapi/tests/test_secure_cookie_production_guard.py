"""Guard against F-84: production must never issue auth cookies without ``Secure``.

``force_https_redirects`` is a single switch that decides three things at once:
whether HTTP is redirected to HTTPS, whether HSTS is emitted, and whether the
session, refresh and CSRF cookies carry the ``Secure`` attribute (see
``api/routers/auth.py`` and ``utils/csrf_middleware.py``).

The field default is ``True``, but ``.env.example`` shipped
``FORCE_HTTPS_REDIRECTS=false`` — the value only appropriate for plaintext-HTTP
local development — and ``docker-compose.yml`` substitutes that file into
``${FORCE_HTTPS_REDIRECTS:-true}``. So the *documented* setup path produced a
production deployment that handed out the long-lived refresh token over
plaintext HTTP, with HSTS suppressed, and nothing refused to start or warned.

These tests pin the invariant: in production the flag must be on, unless an
operator explicitly accepts plaintext credential transport.
"""

from __future__ import annotations

import pytest


def _settings_kwargs(**overrides):
    """Minimum viable Settings payload; the guard under test is the subject."""

    base = {
        "secret_key": "x" * 32,
        "jwt_secret_key": "y" * 32,
        "access_token_expire_minutes": 60,
        "algorithm": "HS256",
    }
    base.update(overrides)
    return base


def test_production_refuses_to_start_without_https_enforcement(monkeypatch) -> None:
    """The refusal is what stops a silent plaintext-credential deployment."""

    from backend_fastapi.app.core.settings import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CELERY_TASK_ALWAYS_EAGER", raising=False)
    monkeypatch.delenv("ALLOW_INSECURE_COOKIES", raising=False)

    with pytest.raises(Exception) as exc:
        Settings(**_settings_kwargs(force_https_redirects=False))

    message = str(exc.value)
    assert "FORCE_HTTPS_REDIRECTS" in message
    assert "Secure" in message


def test_production_starts_when_https_enforcement_is_on(monkeypatch) -> None:
    from backend_fastapi.app.core.settings import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CELERY_TASK_ALWAYS_EAGER", raising=False)

    settings = Settings(**_settings_kwargs(force_https_redirects=True))
    assert settings.force_https_redirects is True


def test_explicit_override_is_honoured(monkeypatch) -> None:
    """An operator who knowingly accepts plaintext transport is not blocked."""

    from backend_fastapi.app.core.settings import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CELERY_TASK_ALWAYS_EAGER", raising=False)
    monkeypatch.setenv("ALLOW_INSECURE_COOKIES", "true")

    settings = Settings(**_settings_kwargs(force_https_redirects=False))
    assert settings.force_https_redirects is False


def test_non_production_is_unaffected(monkeypatch) -> None:
    """Local plaintext-HTTP development keeps working."""

    from backend_fastapi.app.core.settings import Settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ALLOW_INSECURE_COOKIES", raising=False)

    settings = Settings(**_settings_kwargs(force_https_redirects=False))
    assert settings.force_https_redirects is False


def test_field_default_is_secure() -> None:
    """Omitting the variable entirely must land on the safe value."""

    from backend_fastapi.app.core.settings import Settings

    assert Settings.model_fields["force_https_redirects"].default is True


def test_env_example_does_not_ship_the_insecure_value() -> None:
    """`.env.example` is copied to `.env` and read by docker-compose, so the
    value it ships *is* the effective production default."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    env_example = (root / ".env.example").read_text(encoding="utf-8")

    assigned = [
        line.strip()
        for line in env_example.splitlines()
        if line.strip().startswith("FORCE_HTTPS_REDIRECTS=")
    ]
    assert assigned == ["FORCE_HTTPS_REDIRECTS=true"], assigned
