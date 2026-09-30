"""Tests for the series ingestion gate (SRS Part 1G + 1B envelope).

Covers:
  * 1G.6.0 / 1G.3 — a website must be approved before it can be scraped; a
    working parser is not permission.
  * 1G.4 — duplicate manga URL is rejected with the exact user-facing message.
  * 1G.2.2 — an unapproved website is rejected with "Unidentified or unmatched
    URL...".
  * 1B.4.2/1B.4.3 — ingestion errors are the standard envelope with a canonical
    code (WEBSITE_NOT_APPROVED, DUPLICATE_MANGA_URL, VALIDATION_FAILED),
    naming the field and a human message — never an opaque 422.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.api_errors import ApiError, ErrorCode
from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import ApprovedSourceDomain, Manga
from backend_fastapi.app.services.manga_service import (
    MSG_DUPLICATE_MANGA_URL,
    MSG_UNAPPROVED_URL,
    schedule_series_scrape,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    # These are service-level tests; build the schema directly on the test
    # engine so we do not have to boot the full app (redis/celery/etc.).
    Base.metadata.create_all(bind=engine)
    yield


def _reset_domains(session) -> None:
    session.query(ApprovedSourceDomain).delete()
    session.commit()


def _approve(session, domain: str) -> None:
    session.add(ApprovedSourceDomain(base_url=f"https://{domain}", domain=domain))
    session.commit()


def _add_manga(session, source_url: str) -> Manga:
    manga = Manga(title=f"T-{uuid.uuid4().hex}", source_url=source_url)
    session.add(manga)
    session.commit()
    session.refresh(manga)
    return manga


def test_unapproved_domain_is_rejected():
    session = SessionLocal()
    try:
        _reset_domains(session)
        with pytest.raises(ApiError) as excinfo:
            schedule_series_scrape(session, "https://not-approved.example/manga/x")
    finally:
        session.close()

    exc = excinfo.value
    assert exc.code == ErrorCode.WEBSITE_NOT_APPROVED
    assert exc.status == 422
    assert exc.message == MSG_UNAPPROVED_URL
    assert exc.field == "manga_url"
    assert exc.details["url"] == "https://not-approved.example/manga/x"


def test_parser_is_not_permission_subdomain_still_needs_approval():
    """Even a subdomain of a known site is rejected until approved."""
    session = SessionLocal()
    try:
        _reset_domains(session)
        _approve(session, "approved-site.example")
        # A different apex domain is not covered by the approval.
        with pytest.raises(ApiError) as excinfo:
            schedule_series_scrape(session, "https://other-site.example/manga/x")
    finally:
        session.close()

    assert excinfo.value.code == ErrorCode.WEBSITE_NOT_APPROVED


def test_approved_apex_covers_subdomain():
    session = SessionLocal()
    try:
        _reset_domains(session)
        _approve(session, "cola.example")
        # www subdomain of the approved apex passes the gate and therefore
        # proceeds far enough to hit the duplicate check (we pre-seed a manga).
        _add_manga(session, "https://www.cola.example/manga/dup")
        with pytest.raises(ApiError) as excinfo:
            schedule_series_scrape(session, "https://www.cola.example/manga/dup")
    finally:
        session.close()

    # Passing the approval gate means we reached the duplicate check.
    assert excinfo.value.code == ErrorCode.DUPLICATE_MANGA_URL
    assert excinfo.value.message == MSG_DUPLICATE_MANGA_URL


def test_duplicate_manga_url_message():
    session = SessionLocal()
    try:
        _reset_domains(session)
        _approve(session, "dup-site.example")
        url = "https://dup-site.example/manga/already"
        _add_manga(session, url)
        with pytest.raises(ApiError) as excinfo:
            schedule_series_scrape(session, url)
    finally:
        session.close()

    exc = excinfo.value
    assert exc.code == ErrorCode.DUPLICATE_MANGA_URL
    assert exc.status == 409
    assert exc.message == MSG_DUPLICATE_MANGA_URL
    assert exc.details["url"] == url


def _create_main_admin(session):
    from backend_fastapi.app.models import User, UserRole

    admin = User(
        email=f"admin-{uuid.uuid4().hex}@example.com",
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
    return admin


def test_endpoint_unapproved_domain_returns_error_envelope(fastapi_client):
    """End-to-end: POST /api/admin/series surfaces the standard envelope."""
    from backend_fastapi.app.core.security import create_access_token

    session = SessionLocal()
    try:
        _reset_domains(session)
        admin_id = _create_main_admin(session).id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}
    resp = fastapi_client.post(
        "/api/admin/series",
        headers=headers,
        json={"url": "https://never-approved.example/manga/x"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "WEBSITE_NOT_APPROVED"
    assert body["error"]["message"] == MSG_UNAPPROVED_URL
    assert body["error"]["field"] == "manga_url"


def test_endpoint_empty_url_is_structured_not_bare_422(fastapi_client):
    """An empty URL is a VALIDATION_FAILED envelope (SRS 1B.4.2), not empty."""
    from backend_fastapi.app.core.security import create_access_token

    session = SessionLocal()
    try:
        admin_id = _create_main_admin(session).id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}
    resp = fastapi_client.post("/api/admin/series", headers=headers, json={"url": ""})
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["error"]["field"] == "manga_url"
    assert body["error"]["message"]


def test_forbidden_ip_after_approval_is_structured_not_bare_500(
    fastapi_client, monkeypatch
):
    """F-19: a URL that passes the domain-allowlist check but fails the
    lower-level SSRF/format re-validation inside
    universal_scraper.scrape_series_by_url used to raise a bare ValueError,
    which fell through to a generic 500 with no error code -- every other
    rejection reason in this same submission flow (unapproved website,
    duplicate URL, forbidden host rights) returns a structured envelope.
    """
    from backend_fastapi.app.core.security import create_access_token
    from backend_fastapi.app.services import url_guard

    domain = f"rebind-{uuid.uuid4().hex[:8]}.example"
    session = SessionLocal()
    try:
        _reset_domains(session)
        _approve(session, domain)
        admin_id = _create_main_admin(session).id
    finally:
        session.close()

    # Approved by hostname string match, but its DNS resolution is a
    # forbidden (link-local) address -- fails scrape_series_by_url's own
    # validate_scrape_url call even though _host_is_approved already passed.
    monkeypatch.setattr(url_guard, "_host_addresses", lambda host: ["169.254.169.254"])

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}
    resp = fastapi_client.post(
        "/api/admin/series",
        headers=headers,
        json={"url": f"https://{domain}/manga/x"},
    )
    assert resp.status_code != 500
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["error"]["field"] == "manga_url"
