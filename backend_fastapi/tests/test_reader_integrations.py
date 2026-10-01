"""Reader-owned OCR/translation/AI providers (/integrations) and Gemini wiring."""

from __future__ import annotations

import uuid
from unittest import mock

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserAPIKey
from backend_fastapi.app.services.translation_service import TranslationService

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def _reader() -> tuple[int, dict[str, str]]:
    with SessionLocal() as session:
        user = User(email=f"reader-{uuid.uuid4().hex}@example.com", is_active=True, provider="magic_link")
        session.add(user)
        session.commit()
        uid = user.id
    return uid, {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def _add(client, headers, **config):
    return client.post(
        "/api/integrations/add", json={"service": "ai", "config": config}, headers=headers
    )


def test_resave_without_key_keeps_the_stored_key(fastapi_client):
    uid, headers = _reader()
    resp = _add(fastapi_client, headers, provider="google_gemini", apiKey="AIza-secret-1234")
    assert resp.status_code == 200, resp.text
    assert "secret" not in resp.json()["integration"]["apiKey"]

    # The form only ever shows a masked key, so a re-save sends none.
    resp = _add(fastapi_client, headers, provider="google_gemini", apiUrl=GEMINI_URL)
    assert resp.status_code == 200, resp.text

    with SessionLocal() as session:
        record = session.query(UserAPIKey).filter_by(user_id=uid, provider="ai").one()
        assert record.api_key and "AIza" not in record.api_key  # still there, still encrypted


def test_switching_provider_requires_a_new_key(fastapi_client):
    _, headers = _reader()
    _add(fastapi_client, headers, provider="google_gemini", apiKey="AIza-secret-1234")
    resp = _add(
        fastapi_client, headers, provider="openai_gpt_3_5", apiUrl="https://api.openai.com/v1/chat/completions"
    )
    assert resp.status_code == 400


def test_test_endpoint_needs_a_saved_provider(fastapi_client):
    _, headers = _reader()
    resp = fastapi_client.post("/api/integrations/test", json={"service": "ai"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_test_endpoint_reports_a_rejected_key(fastapi_client):
    _, headers = _reader()
    _add(fastapi_client, headers, provider="google_gemini", apiKey="AIza-bad")

    import requests

    response = requests.Response()
    response.status_code = 403
    with mock.patch(
        "backend_fastapi.app.services.translation_service.requests.post",
        return_value=response,
    ):
        resp = fastapi_client.post("/api/integrations/test", json={"service": "ai"}, headers=headers)
    body = resp.json()
    assert body["success"] is False
    assert "rejected" in body["message"]


def test_gemini_single_region_uses_generate_content_shape():
    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": " Hello \n"}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers)
        return _Resp()

    service = TranslationService(default_api_url=None)
    with mock.patch("backend_fastapi.app.services.translation_service.requests.post", fake_post):
        # "custom" provider id with a Gemini URL and no model: the URL decides.
        out = service._perform_translation(
            text="안녕하세요",
            source_lang="ko",
            target_lang="en",
            provider_config={"provider": "custom", "api_url": GEMINI_URL, "api_key": "k"},
        )
    assert out == "Hello"
    assert "contents" in captured["json"] and "messages" not in captured["json"]
    assert captured["headers"]["X-Goog-Api-Key"] == "k"
