from __future__ import annotations

import uuid

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import (
    AdminAuditLog,
    AdminPromotionToken,
    ApprovedSourceDomain,
    Chapter,
    Manga,
    ScrapingJob,
    User,
    UserRole,
)
from backend_fastapi.app.core.security import create_access_token
from _support.db_reset import clear_content


def _create_admin(session: SessionLocal) -> User:
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


def _create_secondary_admin(session: SessionLocal) -> User:
    secondary = User(
        email=f"secondary-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Secondary Admin",
        role=UserRole.SECONDARY,
        is_main_admin=False,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(secondary)
    session.commit()
    session.refresh(secondary)
    return secondary


def test_rescrape_rate_limiter_blocks_excess_requests(fastapi_client, monkeypatch):
    from backend_fastapi.app.api.routers import admin as admin_router
    from backend_fastapi.app.services.admin_service import RescrapeRateLimiter

    monkeypatch.setattr(
        admin_router, "delete_chapter_pages_only", lambda *args, **kwargs: None
    )
    admin_router._rescrape_limiter = RescrapeRateLimiter(limit=1, window_seconds=60)

    session = SessionLocal()
    try:
        clear_content(session, commit=False)
        session.commit()

        admin = _create_admin(session)
        admin_id = admin.id
        manga = Manga(
            title="Rate Test",
            slug="rate-test",
            source_url="https://example.com/rate",
        )
        session.add(manga)
        session.commit()
        manga_id = manga.id
    finally:
        session.close()

    token = create_access_token(str(admin_id))
    headers = {"Authorization": f"Bearer {token}"}

    from unittest import mock

    body = {"confirm_title": "Rate Test"}
    with mock.patch(
        "backend_fastapi.app.tasks.scraper_tasks.staged_series_rescrape"
    ) as task:
        task.delay.return_value = mock.Mock(id="t1")
        ok = fastapi_client.post(
            f"/api/admin/series/{manga_id}/rescrape", headers=headers, json=body
        )
        assert ok.status_code == 200

        limited = fastapi_client.post(
            f"/api/admin/series/{manga_id}/rescrape", headers=headers, json=body
        )
    assert limited.status_code == 429
    assert limited.json()["error"]["message"].startswith("Too many rescrape requests")


def test_admin_token_listing(fastapi_client):
    session = SessionLocal()
    try:
        admin = _create_admin(session)
        admin_id = admin.id

        token_a = AdminPromotionToken(token_hash="hash-a", issued_to_user_id=admin_id)
        token_b = AdminPromotionToken(token_hash="hash-b", issued_to_user_id=None)
        session.add_all([token_a, token_b])
        session.commit()
    finally:
        session.close()

    token = create_access_token(str(admin_id))
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.get("/api/admin/admin-tokens", headers=headers)
    assert resp.status_code == 200
    tokens = resp.json()
    assert len(tokens) == 2
    assert {entry["token_hash"] for entry in tokens} == {"hash-a", "hash-b"}


def test_scraping_jobs_listing(fastapi_client):
    session = SessionLocal()
    try:
        session.query(ScrapingJob).delete()
        clear_content(session, commit=False)
        session.commit()

        admin = _create_admin(session)
        admin_id = admin.id
        manga = Manga(
            title="Job Test",
            slug="job-test",
            source_url="https://example.com/job",
        )
        session.add(manga)
        session.commit()
        manga_id = manga.id

        job = ScrapingJob(
            manga_id=manga_id, status="running", source_url="https://example.com"
        )
        session.add(job)
        session.commit()
    finally:
        session.close()

    token = create_access_token(str(admin_id))
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.get("/api/admin/scraping-jobs", headers=headers)
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["manga_id"] == manga_id
    assert jobs[0]["status"] == "running"


def test_approved_domain_crud_flow(fastapi_client):
    session = SessionLocal()
    try:
        session.query(ApprovedSourceDomain).delete()
        session.commit()

        admin = _create_admin(session)
        admin_id = admin.id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    empty = fastapi_client.get("/api/admin/approved-domains", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == []

    created = fastapi_client.post(
        "/api/admin/approved-domains",
        headers=headers,
        json={"url": "https://example.com/manga/series", "label": "Example"},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["domain"] == "example.com"
    assert payload["base_url"] == "https://example.com"
    assert payload["label"] == "Example"

    listed = fastapi_client.get("/api/admin/approved-domains", headers=headers)
    assert listed.status_code == 200
    entries = listed.json()
    assert len(entries) == 1
    assert entries[0]["domain"] == "example.com"

    deleted = fastapi_client.delete(
        f"/api/admin/approved-domains/{payload['id']}", headers=headers
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == payload["id"]

    final = fastapi_client.get("/api/admin/approved-domains", headers=headers)
    assert final.status_code == 200
    assert final.json() == []


def test_approved_domain_requires_main_admin_for_mutation(fastapi_client):
    session = SessionLocal()
    try:
        session.query(ApprovedSourceDomain).delete()
        session.commit()

        secondary = _create_secondary_admin(session)
        domain = ApprovedSourceDomain(
            base_url="https://allowed.com", domain="allowed.com"
        )
        session.add(domain)
        session.commit()
        domain_id = domain.id
        secondary_id = secondary.id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(secondary_id))}"}

    listing = fastapi_client.get("/api/admin/approved-domains", headers=headers)
    assert listing.status_code == 200

    create_attempt = fastapi_client.post(
        "/api/admin/approved-domains",
        headers=headers,
        json={"url": "https://blocked.com"},
    )
    assert create_attempt.status_code == 403

    delete_attempt = fastapi_client.delete(
        f"/api/admin/approved-domains/{domain_id}", headers=headers
    )
    assert delete_attempt.status_code == 403


def test_delete_series_writes_admin_audit_log(fastapi_client):
    """#14: DELETE /admin/series/{manga_id} used to write only a structlog
    line, never an admin_audit_logs row -- unlike its bulk-delete sibling.

    admin_audit_logs is append-only (F-3), so this leaves prior rows in
    place and instead identifies its own row by the manga_id it deleted,
    which is unique to this test.
    """
    session = SessionLocal()
    try:
        admin = _create_admin(session)
        admin_id = admin.id
        manga = Manga(
            title="Delete Audit Test",
            slug=f"delete-audit-test-{uuid.uuid4().hex}",
            source_url=f"https://example.com/delete-audit-{uuid.uuid4().hex}",
        )
        session.add(manga)
        session.commit()
        manga_id = manga.id
        session.add(
            Chapter(
                manga_id=manga_id,
                chapter_number=1,
                chapter_url=f"https://example.com/delete-audit/{uuid.uuid4().hex}",
            )
        )
        session.commit()
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    resp = fastapi_client.delete(f"/api/admin/series/{manga_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_chapters"] == 1

    with SessionLocal() as verify:
        entry = (
            verify.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "DELETE_SERIES")
            .filter(AdminAuditLog.metadata_json["target_id"].as_string() == str(manga_id))
            .one()
        )
        assert entry.user_id == admin_id
        assert entry.metadata_json["result"] == "success"


def test_bulk_delete_series_writes_admin_audit_log(fastapi_client):
    """Sibling of the #14 regression test above: confirms the already-fixed
    bulk-delete path still writes its BULK_DELETE row (the pattern
    delete_series was missing).

    admin_audit_logs is append-only (F-3), so this identifies its own row
    by the unique manga ids it "deleted" rather than clearing the table.
    """
    from unittest import mock

    session = SessionLocal()
    try:
        admin = _create_admin(session)
        admin_id = admin.id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}
    bulk_ids = [1_000_000_001, 1_000_000_002]

    with mock.patch(
        "backend_fastapi.app.tasks.scraper_tasks.bulk_delete_series_task"
    ) as task:
        task.delay.return_value = mock.Mock(id="bulk-1")
        resp = fastapi_client.post(
            "/api/admin/series/bulk-delete",
            headers=headers,
            json={"ids": bulk_ids},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 2

    with SessionLocal() as verify:
        entry = (
            verify.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "BULK_DELETE")
            .filter(
                AdminAuditLog.metadata_json["new_value"].as_string()
                == str(bulk_ids)
            )
            .one()
        )
        assert entry.user_id == admin_id
        assert entry.metadata_json["target_id"] == "multiple"
