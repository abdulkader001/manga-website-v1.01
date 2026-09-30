from __future__ import annotations

import json

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import (
    AdClick,
    AdSlot,
    Setting,
    User,
    UserRole,
)
from backend_fastapi.app.core.security import create_access_token
from _support.db_reset import clear_users


def _create_admin_user() -> tuple[int, str]:
    session = SessionLocal()
    try:
        clear_users(session)
        admin = User(
            email="admin@example.com",
            is_active=True,
            name="Admin",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        return admin.id, "password123"
    finally:
        session.close()


def test_translation_text_endpoint(monkeypatch, fastapi_client, auth_headers):
    from backend_fastapi.app.api.routers import translation as translation_router

    class DummyService:
        def translate(
            self,
            text: str,
            source_lang: str,
            target_lang: str,
            provider_config=None,
            *,
            outcome=None,
        ):  # noqa: ARG002
            assert source_lang == "auto"
            assert target_lang == "es"
            return "hola"

    monkeypatch.setattr(translation_router, "translation_service", DummyService())

    resp = fastapi_client.post(
        "/api/translation/text",
        json={"text": "hello", "target": "es"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["translated"] == "hola"


def test_translation_unavailable_when_no_provider(
    monkeypatch, fastapi_client, auth_headers
):
    from backend_fastapi.app.api.routers import translation as translation_router

    monkeypatch.setattr(translation_router, "translation_service", None)

    resp = fastapi_client.post(
        "/api/translation/text",
        json={"text": "hello", "target": "es"},
        headers=auth_headers,
    )
    assert resp.status_code == 503
    payload = resp.json()
    assert payload["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert payload["error"]["details"]["reason"] == "translation_unavailable"


def test_config_endpoint_redacts_sensitive_values(
    tmp_path, monkeypatch, fastapi_client
):
    config_path = tmp_path / "admin_config.json"
    config_data = {
        "api_key": "secret",
        "nested": {"token": "abc", "url": "https://example.com"},
    }
    config_path.write_text(json.dumps(config_data))
    monkeypatch.setenv("ADMIN_CONFIG_PATH", str(config_path))

    admin_id, _ = _create_admin_user()
    token = create_access_token(str(admin_id))
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.get("/api/config", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["api_key"] == "***redacted***"
    assert payload["nested"]["token"] == "***redacted***"
    assert payload["nested"]["url"] == "https://example.com"


def test_ads_public_endpoints(fastapi_client):
    session = SessionLocal()
    try:
        session.query(AdClick).delete()
        session.query(AdSlot).delete()
        slot = AdSlot(name="Banner", slot_key="home_top", type="image", enabled=True)
        session.add(slot)
        session.commit()
        slot_id = slot.id
    finally:
        session.close()

    listings = fastapi_client.get("/api/ads/")
    assert listings.status_code == 200
    assert len(listings.json()) == 1

    config = fastapi_client.get("/api/ads/config")
    assert config.status_code == 200
    assert "global" in config.json()

    click_resp = fastapi_client.post(f"/api/ads/click/{slot_id}")
    assert click_resp.status_code == 201
    assert click_resp.json()["message"] == "click_recorded"

    session = SessionLocal()
    try:
        clicks = session.query(AdClick).count()
    finally:
        session.close()
    assert clicks == 1


def test_ads_config_defaults_loaded(fastapi_client):
    session = SessionLocal()
    try:
        session.query(Setting).filter(Setting.key == "ads_config").delete()
        session.commit()
    finally:
        session.close()

    resp = fastapi_client.get("/api/ads/config")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["global"]["network"] == ""
    assert len(payload["header_rows"]) == 2
