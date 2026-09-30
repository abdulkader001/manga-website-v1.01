"""Tests for OCR/translation submit-and-poll job flow (item 39).

Tasks run inline (CELERY_TASK_ALWAYS_EAGER is set in the test env), so a submit
completes synchronously and the job store holds a terminal result immediately.
"""

from __future__ import annotations

import uuid

from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.tasks import translation_tasks
from backend_fastapi.app.utils import job_store


def _other_auth_headers():
    """Bearer headers for a second, distinct registered user."""
    with SessionLocal() as session:
        user = User(
            email=f"user-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Other Test User",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def test_submit_translation_job_returns_job_id(fastapi_client, auth_headers):
    resp = fastapi_client.post(
        "/api/translation/jobs",
        json={"text": "hello", "target": "es"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    # The eager task has already run to a terminal state.
    status_resp = fastapi_client.get(
        f"/api/translation/jobs/{job_id}", headers=auth_headers
    )
    assert status_resp.status_code == 200
    doc = status_resp.json()
    assert doc["status"] in job_store.TERMINAL_STATUSES


def test_translation_job_status_requires_auth(fastapi_client, auth_headers):
    resp = fastapi_client.post(
        "/api/translation/jobs",
        json={"text": "hello", "target": "es"},
        headers=auth_headers,
    )
    job_id = resp.json()["job_id"]

    # Anonymous request: no credentials at all.
    anon_resp = fastapi_client.get(f"/api/translation/jobs/{job_id}")
    assert anon_resp.status_code == 401

    # A different authenticated user must not see someone else's job.
    other_resp = fastapi_client.get(
        f"/api/translation/jobs/{job_id}", headers=_other_auth_headers()
    )
    assert other_resp.status_code == 403

    # The owner can still fetch their own job.
    own_resp = fastapi_client.get(
        f"/api/translation/jobs/{job_id}", headers=auth_headers
    )
    assert own_resp.status_code == 200


def test_ocr_job_status_requires_auth(fastapi_client, auth_headers):
    resp = fastapi_client.post(
        "/api/ocr/overlay-jobs",
        json={
            "items": [{"text": "hola"}],
            "page": {"width": 100, "height": 100},
            "target": "en",
        },
        headers=auth_headers,
    )
    job_id = resp.json()["job_id"]

    anon_resp = fastapi_client.get(f"/api/ocr/jobs/{job_id}")
    assert anon_resp.status_code == 401

    other_resp = fastapi_client.get(
        f"/api/ocr/jobs/{job_id}", headers=_other_auth_headers()
    )
    assert other_resp.status_code == 403

    own_resp = fastapi_client.get(f"/api/ocr/jobs/{job_id}", headers=auth_headers)
    assert own_resp.status_code == 200


def test_translation_job_happy_path(fastapi_client, monkeypatch, auth_headers):
    class _FakeService:
        def translate(self, text, source_lang, target_lang, provider_config=None):
            return f"[{target_lang}]{text}"

    monkeypatch.setattr(translation_tasks, "_build_service", lambda cfg: _FakeService())

    resp = fastapi_client.post(
        "/api/translation/jobs",
        json={"text": "hi", "target": "fr"},
        headers=auth_headers,
    )
    job_id = resp.json()["job_id"]
    doc = fastapi_client.get(
        f"/api/translation/jobs/{job_id}", headers=auth_headers
    ).json()
    assert doc["status"] == "done"
    assert doc["result"]["translated"] == "[fr]hi"


def test_translation_job_without_provider_marks_failed(fastapi_client, auth_headers):
    # No provider configured -> service is None -> terminal failed state.
    resp = fastapi_client.post(
        "/api/translation/jobs",
        json={"text": "hi", "target": "de"},
        headers=auth_headers,
    )
    job_id = resp.json()["job_id"]
    doc = fastapi_client.get(
        f"/api/translation/jobs/{job_id}", headers=auth_headers
    ).json()
    assert doc["status"] == "failed"
    assert doc["error"] == "translation_unavailable"


def test_get_unknown_job_returns_404(fastapi_client, auth_headers):
    assert (
        fastapi_client.get(
            "/api/translation/jobs/does-not-exist", headers=auth_headers
        ).status_code
        == 404
    )
    assert (
        fastapi_client.get(
            "/api/ocr/jobs/does-not-exist", headers=auth_headers
        ).status_code
        == 404
    )


def test_get_unknown_job_requires_auth(fastapi_client):
    assert fastapi_client.get("/api/translation/jobs/does-not-exist").status_code == 401
    assert fastapi_client.get("/api/ocr/jobs/does-not-exist").status_code == 401


def test_submit_overlay_translation_job(fastapi_client, auth_headers):
    resp = fastapi_client.post(
        "/api/ocr/overlay-jobs",
        json={
            "items": [{"text": "hola"}],
            "page": {"width": 100, "height": 100},
            "target": "en",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    doc = fastapi_client.get(f"/api/ocr/jobs/{job_id}", headers=auth_headers).json()
    # No translation provider in tests -> job completes with boxes + an error note.
    assert doc["status"] == job_store.STATUS_DONE
    assert "boxes" in doc["result"]
