"""Headless API test harness (SRS 1B.5.2 / 1A.1.6).

A second API client with no UI must be able to perform Part 1 operations and,
critically, permission rules must hold when the UI is bypassed entirely — a
direct API call, not a hidden button, is the proof (1A.1.6).

This harness drives the *versioned* ``/api/v1`` surface (1B.4.1) with a small
reusable client, and asserts:
  * the versioned surface is reachable,
  * catalogue browsing works for a guest (no auth),
  * privileged operations are rejected without/with insufficient authority,
  * the standard error envelope (1B.4.2) is returned with canonical codes.

It is intentionally extensible: add operations as later sub-parts land.
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    ApprovedSourceDomain,
    Manga,
    ScrapingJob,
    User,
    UserRole,
)

API = "/api/v1"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


class ApiHarness:
    """A UI-less API client for Part 1 operations against ``/api/v1``."""

    def __init__(self, client, token: str | None = None):
        self._client = client
        self._token = token

    def as_token(self, token: str | None) -> "ApiHarness":
        return ApiHarness(self._client, token)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def get(self, path: str, **kw):
        return self._client.get(f"{API}{path}", headers=self._headers(), **kw)

    def post(self, path: str, json=None, **kw):
        return self._client.post(
            f"{API}{path}", json=json, headers=self._headers(), **kw
        )


def _make_admin(session, *, main: bool) -> int:
    admin = User(
        email=f"admin-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Admin",
        role=UserRole.ADMIN if main else UserRole.SECONDARY,
        is_main_admin=main,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin.id


def test_versioned_surface_is_reachable(fastapi_client):
    harness = ApiHarness(fastapi_client)
    resp = harness.get("/manga/?per_page=5")
    assert resp.status_code == 200


def test_guest_cannot_submit_series(fastapi_client):
    """Permission is enforced server-side even with no UI (1A.1.6)."""
    harness = ApiHarness(fastapi_client)  # no token = guest
    resp = harness.post("/admin/series", json={"url": "https://x.example/m/1"})
    assert resp.status_code in (401, 403)


def test_unapproved_website_envelope_via_v1(fastapi_client):
    session = SessionLocal()
    try:
        session.query(ApprovedSourceDomain).delete()
        session.commit()
        admin_id = _make_admin(session, main=True)
    finally:
        session.close()

    harness = ApiHarness(fastapi_client, create_access_token(str(admin_id)))
    resp = harness.post("/admin/series", json={"url": "https://unapproved.example/m/1"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "WEBSITE_NOT_APPROVED"


def test_permanent_admin_approve_then_submit(fastapi_client):
    """Governed flow through the API: approve a website, then submit a series."""
    new_url = "https://harness.example/series/new"
    session = SessionLocal()
    try:
        session.query(ScrapingJob).delete()
        session.query(Manga).filter(Manga.source_url == new_url).delete()
        session.query(ApprovedSourceDomain).filter_by(domain="harness.example").delete()
        session.commit()
        admin_id = _make_admin(session, main=True)
    finally:
        session.close()

    harness = ApiHarness(fastapi_client, create_access_token(str(admin_id)))

    # Register + approve a parser first, so the on-save flow (1G.6.0A) takes
    # the "parser exists -> ACTIVE" branch and submission opens immediately.
    candidate = harness.post(
        "/admin/parsers/harness.example/candidates",
        json={"definition": {"manga_title": "h1", "page_images": "img"}},
    )
    assert candidate.status_code == 201
    harness.post(f"/admin/parsers/versions/{candidate.json()['id']}/approve")

    # Approve the website (Permanent Administrator only).
    approved = harness.post(
        "/admin/approved-domains", json={"url": "https://harness.example"}
    )
    assert approved.status_code == 201
    assert approved.json()["status"] == "active"

    with mock.patch(
        "backend_fastapi.app.services.universal_scraper.scrape_series_by_url"
    ) as scrape:
        scrape.return_value = {
            "job_id": 1,
            "source_url": new_url,
            "status": "queued",
            "job": {"id": 1},
        }
        created = harness.post("/admin/series", json={"url": new_url})
        assert created.status_code == 201
        assert scrape.called


def test_duplicate_series_returns_conflict_envelope(fastapi_client):
    """A URL whose series already exists duplicates with a 409 envelope."""
    dup_url = "https://harness.example/series/dup"
    session = SessionLocal()
    try:
        session.query(ApprovedSourceDomain).filter_by(domain="harness.example").delete()
        session.query(Manga).filter(Manga.source_url == dup_url).delete()
        session.add(
            ApprovedSourceDomain(
                base_url="https://harness.example", domain="harness.example"
            )
        )
        session.add(Manga(title=f"T-{uuid.uuid4().hex}", source_url=dup_url))
        session.commit()
        admin_id = _make_admin(session, main=True)
    finally:
        session.close()

    harness = ApiHarness(fastapi_client, create_access_token(str(admin_id)))
    dup = harness.post("/admin/series", json={"url": dup_url})
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DUPLICATE_MANGA_URL"


def test_guests_rejected_from_every_processing_endpoint(fastapi_client):
    """SRS 1D.3.4 acceptance: every processing endpoint rejects a guest.

    Verified by direct API call (no UI), returning LOGIN_REQUIRED_FOR_PROCESSING.
    """
    processing_calls = [
        ("post", "/api/v1/translation/text", {"text": "hi", "target": "en"}),
        ("post", "/api/v1/translation/jobs", {"text": "hi", "target": "en"}),
        (
            "post",
            "/api/v1/ocr/translate-overlay",
            {"imageUrl": "https://example.com/i.png", "target": "en"},
        ),
        (
            "post",
            "/api/v1/ocr/overlay-jobs",
            {"items": [{"text": "x"}], "page": {"width": 1, "height": 1}},
        ),
    ]
    for method, path, body in processing_calls:
        resp = getattr(fastapi_client, method)(path, json=body)  # no auth header
        assert resp.status_code == 403, f"{path} did not reject guest"
        assert resp.json()["error"]["code"] == "LOGIN_REQUIRED_FOR_PROCESSING", path
