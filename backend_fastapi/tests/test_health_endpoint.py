from __future__ import annotations

from typing import Iterator
from uuid import uuid4

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.core.settings import settings
from backend_fastapi.app.models import User, UserRole


def _admin_headers() -> dict[str, str]:
    session = SessionLocal()
    try:
        admin = User(
            email=f"health-admin-{uuid4().hex}@example.com",
            is_active=True,
            name="Health Admin",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        token = create_access_token(str(admin.id))
        return {"Authorization": f"Bearer {token}"}
    finally:
        session.close()


def _plain_user_headers() -> dict[str, str]:
    session = SessionLocal()
    try:
        user = User(
            email=f"health-user-{uuid4().hex}@example.com",
            is_active=True,
            name="Health Plain User",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_access_token(str(user.id))
        return {"Authorization": f"Bearer {token}"}
    finally:
        session.close()


@pytest.fixture
def _restore_settings() -> Iterator[None]:
    original = {
        "google_oauth_client_id": settings.google_oauth_client_id,
        "google_oauth_client_secret": settings.google_oauth_client_secret,
        "default_translation_provider": settings.default_translation_provider,
    }
    try:
        yield
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def _prepare_common_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://localhost:3000")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_fastapi.db")
    monkeypatch.delenv("GOOGLE_PROJECT_ID", raising=False)
    monkeypatch.delenv("REQUIRE_GOOGLE_PROJECT_ID", raising=False)
    settings.force_https_redirects = False


def test_health_allows_missing_google_project_when_optional(
    fastapi_client,
    monkeypatch: pytest.MonkeyPatch,
    _restore_settings: None,
) -> None:
    _prepare_common_env(monkeypatch)

    settings.google_oauth_client_id = None
    settings.google_oauth_client_secret = None
    settings.default_translation_provider = None

    response = fastapi_client.get("/api/health", headers=_admin_headers())
    payload = response.json()

    assert payload["env_ok"]["GOOGLE_PROJECT_ID"] is True
    assert (
        "GOOGLE_PROJECT_ID environment variable is missing." not in payload["warnings"]
    )


def test_health_requires_google_project_when_oauth_configured(
    fastapi_client,
    monkeypatch: pytest.MonkeyPatch,
    _restore_settings: None,
) -> None:
    _prepare_common_env(monkeypatch)

    settings.google_oauth_client_id = "test-client"
    settings.google_oauth_client_secret = "test-secret"
    settings.default_translation_provider = None

    response = fastapi_client.get("/api/health", headers=_admin_headers())
    payload = response.json()

    assert payload["env_ok"]["GOOGLE_PROJECT_ID"] is False
    assert "GOOGLE_PROJECT_ID environment variable is missing." in payload["warnings"]
    assert payload["status"] == "degraded"


def test_health_rejects_unauthenticated_requests(fastapi_client) -> None:
    response = fastapi_client.get("/api/health")
    assert response.status_code == 401


def test_health_rejects_non_admin_user(fastapi_client) -> None:
    response = fastapi_client.get("/api/health", headers=_plain_user_headers())
    assert response.status_code == 403


def test_health_security_rejects_unauthenticated_requests(fastapi_client) -> None:
    response = fastapi_client.get("/api/health/security")
    assert response.status_code == 401


def test_health_security_rejects_non_admin_user(fastapi_client) -> None:
    response = fastapi_client.get("/api/health/security", headers=_plain_user_headers())
    assert response.status_code == 403


def test_health_security_allows_main_admin(fastapi_client) -> None:
    response = fastapi_client.get("/api/health/security", headers=_admin_headers())
    assert response.status_code == 200
    payload = response.json()
    assert "checks" in payload
    assert "warnings" in payload
