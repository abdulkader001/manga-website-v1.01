"""Roadmap item 5: production must refuse to start with ALLOW_PLAINTEXT_SECRETS."""

from __future__ import annotations

import pytest


def _kwargs():
    return {
        "secret_key": "x" * 32,
        "jwt_secret_key": "y" * 32,
        "access_token_expire_minutes": 60,
        "algorithm": "HS256",
        "force_https_redirects": True,
        "email_encryption_key": None,
    }


def _production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CELERY_TASK_ALWAYS_EAGER", raising=False)
    monkeypatch.delenv("FORCE_ENCRYPTED_SECRETS", raising=False)


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_production_refuses_plaintext_secrets(monkeypatch, value):
    from backend_fastapi.app.core.settings import Settings

    _production(monkeypatch)
    monkeypatch.setenv("ALLOW_PLAINTEXT_SECRETS", value)

    with pytest.raises(Exception) as exc:
        Settings(**_kwargs())
    assert "ALLOW_PLAINTEXT_SECRETS" in str(exc.value)


def test_development_still_allows_plaintext_secrets(monkeypatch):
    from backend_fastapi.app.core.settings import Settings

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_PLAINTEXT_SECRETS", "1")

    assert Settings(**_kwargs()).secret_key == "x" * 32
