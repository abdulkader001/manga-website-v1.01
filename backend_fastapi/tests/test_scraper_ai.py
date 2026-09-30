"""The scraper-creation AI configuration (SRS 1G.8.7 / 1G.8.8 / 1G.9).

Covers: PA-only configuration with the key encrypted at rest; the Test
action; provider neutrality by configuration; single entry point (parser
generation only); and the exact honest-failure statement of 1G.9.2 with the
1G.9.3 required-inputs list.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import ProviderCredentials, User, UserRole
from backend_fastapi.app.services import scraper_ai_service


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"sai-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="SAI",
        role=role,
        is_main_admin=main,
        is_secondary_admin=secondary,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def _clear_record():
    session = SessionLocal()
    try:
        session.query(ProviderCredentials).filter_by(
            provider_name="scraper_ai", is_system=True
        ).delete()
        session.commit()
    finally:
        session.close()


def test_pa_configures_scraper_ai_key_encrypted(fastapi_client):
    _clear_record()
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    payload = {
        "service": "scraper_ai",
        "config": {
            "provider": "google_gemini",
            "apiKey": "super-secret-gemini-key",
        },
    }

    # Secondary admins cannot configure it (1G.8.8: PA only).
    denied = fastapi_client.put(
        "/api/admin/system-providers", headers=_h(sec_id), json=payload
    )
    assert denied.status_code == 403

    saved = fastapi_client.put(
        "/api/admin/system-providers", headers=_h(pa_id), json=payload
    )
    assert saved.status_code == 200

    # Key is encrypted at rest — the stored value is not the plaintext.
    session = SessionLocal()
    try:
        record = (
            session.query(ProviderCredentials)
            .filter_by(provider_name="scraper_ai", is_system=True)
            .one()
        )
        assert record.api_key
        assert record.api_key != "super-secret-gemini-key"
        # Provider-neutral defaults filled in from configuration alone.
        assert "generativelanguage" in record.config["api_url"]
    finally:
        session.close()

    # get_config decrypts it back for the generation path only.
    config = scraper_ai_service.get_config()
    assert config is not None
    assert config["api_key"] == "super-secret-gemini-key"
    assert config["provider"] == "google_gemini"

    # The masked provider payload never exposes the full key.
    listing = fastapi_client.get("/api/admin/system-providers", headers=_h(pa_id))
    assert "super-secret-gemini-key" not in listing.text

    _clear_record()


def test_scraper_ai_test_action(fastapi_client):
    _clear_record()
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    # Unconfigured: the Test action says so instead of pretending.
    resp = fastapi_client.post(
        "/api/admin/system-providers/scraper-ai/test", headers=_h(pa_id)
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "error": "not_configured"}

    fastapi_client.put(
        "/api/admin/system-providers",
        headers=_h(pa_id),
        json={
            "service": "scraper_ai",
            "config": {"provider": "openai", "apiKey": "sk-test"},
        },
    )

    with mock.patch.object(scraper_ai_service, "_chat_request", return_value="ok"):
        resp = fastapi_client.post(
            "/api/admin/system-providers/scraper-ai/test", headers=_h(pa_id)
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "openai"
    # The key is never in the response.
    assert "sk-test" not in resp.text

    _clear_record()


def test_generation_uses_configured_provider():
    _clear_record()
    with mock.patch.object(
        scraper_ai_service,
        "get_config",
        return_value={
            "provider": "custom",
            "api_key": "k",
            "api_url": "https://ai.example/v1/chat/completions",
            "model": "m",
            "headers": None,
        },
    ):
        with mock.patch.object(
            scraper_ai_service,
            "_chat_request",
            return_value='{"page_images": ".pages img"}',
        ) as chat:
            out = scraper_ai_service.generate_selectors("<html></html>", "chapter")
    assert out == {"page_images": ".pages img"}
    assert chat.called


def test_ai_fallback_routes_through_scraper_ai_only():
    """1G.8.8: the scraper AI has exactly one entry point — parser
    generation/repair. Nothing else in the app imports it."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    consumers = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "generate_selectors" in text or "scraper_ai_service" in text:
            consumers.append(path.relative_to(app_dir).as_posix())
    allowed = {
        "services/scraper_ai_service.py",  # the service itself
        "services/parser_generation_service.py",  # parser generation/repair
        "scrapers/ai_fallback.py",  # parser generation/repair
        "api/routers/admin.py",  # the PA Test action + generation trigger
    }
    assert set(consumers) <= allowed, f"Unexpected scraper-AI consumers: {consumers}"


def test_honest_failure_statement_exact():
    """1G.9.2 verbatim + 1G.9.3 required inputs."""
    report = scraper_ai_service.honest_failure_report("unscrapable.example")
    assert report["possible"] is False
    assert report["message"] == (
        "Automatic scraper generation cannot reliably create a scraper for "
        "this website from only its homepage URL. It is not theoretically "
        "possible to derive the extraction rules from this URL alone. A "
        "website-specific parser is required."
    )
    assert "A sample series/manga page URL" in report["required_inputs"]
    assert "A sample chapter page URL" in report["required_inputs"]
    assert "Example raw image URLs" in report["required_inputs"]
    assert len(report["required_inputs"]) == 5
