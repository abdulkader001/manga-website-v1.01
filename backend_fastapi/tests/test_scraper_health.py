"""Scraper health + structure-change detection (SRS 1G.7.5 / 1G.7.7 / 1G.7.8).

Covers: the degraded -> confirmation -> failing progression (transient blips
recover); auto-disable + PA alert with evidence on confirmed failure;
ingestion halted for the broken website ONLY while other websites continue;
existing data untouched; the dashboard rows of 1G.8.6.
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    ApprovedSourceDomain,
    Chapter,
    Manga,
    Notification,
    User,
    UserRole,
)
from backend_fastapi.app.scrapers.errors import ExtractionError
from backend_fastapi.app.services import scraper_health_service as health


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _approve(session, domain: str) -> int:
    entry = ApprovedSourceDomain(
        base_url=f"https://{domain}", domain=domain, status="active"
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry.id


def _fail_once(session, domain: str) -> str:
    return health.record_failure(
        session,
        domain,
        ExtractionError(
            "Selector returned no elements.",
            url=f"https://{domain}/manga/x",
            missing_field="chapter_list",
            selector_used=".chapters li",
            scraper_module=f"{domain}_v1",
        ),
    )


def test_degraded_confirmation_failing_progression():
    domain = f"prog-{uuid.uuid4().hex[:6]}.com"
    session = SessionLocal()
    try:
        _approve(session, domain)

        # Below the degrade threshold: still healthy (transient tolerance).
        for _ in range(health.DEGRADE_AFTER - 1):
            state = _fail_once(session, domain)
        assert state == "healthy"

        # Threshold crossed: DEGRADED, not failed — it may be transient.
        state = _fail_once(session, domain)
        assert state == "degraded"
        entry = session.query(ApprovedSourceDomain).filter_by(domain=domain).one()
        assert entry.status == "degraded"

        # A success is the confirmation check passing: back to healthy.
        health.record_success(session, domain)
        session.expire_all()
        entry = session.query(ApprovedSourceDomain).filter_by(domain=domain).one()
        assert entry.status == "active"
        assert health.health_for(session, domain)["state"] == "healthy"
    finally:
        session.close()


def test_confirmed_failure_disables_and_alerts_with_evidence():
    domain = f"conf-{uuid.uuid4().hex[:6]}.com"
    session = SessionLocal()
    try:
        _approve(session, domain)
        state = "healthy"
        for _ in range(health.FAIL_AFTER):
            state = _fail_once(session, domain)
        assert state == "failing"

        session.expire_all()
        entry = session.query(ApprovedSourceDomain).filter_by(domain=domain).one()
        # Auto-disabled: ingestion for THIS website halts.
        assert entry.status == "disabled"
        assert health.is_halted(session, domain) is True

        # The PA alert names the website, failing step, selector, module.
        note = (
            session.query(Notification)
            .filter(Notification.type == "website.structure_changed")
            .order_by(Notification.id.desc())
            .first()
        )
        assert note is not None
        assert (note.data or {}).get("domain") == domain
        assert "chapter_list" in note.body
        assert ".chapters li" in note.body
        assert f"{domain}_v1" in note.body
    finally:
        session.close()


def test_halt_is_scoped_to_one_website():
    """1G.7.7: a structure change on one website halts that website only."""
    broken = f"broken-{uuid.uuid4().hex[:6]}.com"
    fine = f"fine-{uuid.uuid4().hex[:6]}.com"
    session = SessionLocal()
    try:
        _approve(session, broken)
        _approve(session, fine)
        for _ in range(health.FAIL_AFTER):
            _fail_once(session, broken)

        assert health.is_halted(session, broken) is True
        assert health.is_halted(session, fine) is False
        # The healthy website's record is untouched.
        entry = session.query(ApprovedSourceDomain).filter_by(domain=fine).one()
        assert entry.status == "active"
    finally:
        session.close()


def test_workflow_skips_halted_website_but_keeps_data():
    """Queued work for a disabled website is parked; existing chapters stay."""
    from backend_fastapi.app.services.scraper_workflow_service import (
        ScraperWorkflowService,
    )

    domain = f"halt-{uuid.uuid4().hex[:6]}.com"
    session = SessionLocal()
    try:
        _approve(session, domain)
        manga = Manga(
            title="Halted",
            source_url=f"https://{domain}/manga/halted",
            type="manga",
            status="ongoing",
        )
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://{domain}/manga/halted/ch-1",
            pages=["https://x/p1.jpg"],
            ingestion_status="complete",
        )
        session.add(chapter)
        session.commit()
        chapter_id = chapter.id
        for _ in range(health.FAIL_AFTER):
            _fail_once(session, domain)
    finally:
        session.close()

    session = SessionLocal()
    try:
        service = ScraperWorkflowService(session)
        with mock.patch(
            "backend_fastapi.app.scrapers.base_scraper.BaseScraper.scrape_chapter"
        ) as scrape:
            result = service.process_chapter_scrape(chapter_id)
            assert result == {"status": "skipped", "error": "website_disabled"}
            assert not scrape.called  # the scraper module is never invoked
    finally:
        session.close()

    # Existing ingested data is never deleted (readers keep reading).
    session = SessionLocal()
    try:
        refreshed = session.get(Chapter, chapter_id)
        assert refreshed.pages == ["https://x/p1.jpg"]
    finally:
        session.close()


def test_dashboard_shows_which_website_broke(fastapi_client):
    broken = f"dash-{uuid.uuid4().hex[:6]}.com"
    session = SessionLocal()
    try:
        admin = User(
            email=f"dash-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Dash",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_id = admin.id
        _approve(session, broken)
        for _ in range(health.FAIL_AFTER):
            _fail_once(session, broken)
    finally:
        session.close()

    resp = fastapi_client.get(
        "/api/admin/scrapers/health",
        headers={"Authorization": f"Bearer {create_access_token(str(admin_id))}"},
    )
    assert resp.status_code == 200
    rows = {w["domain"]: w for w in resp.json()["websites"]}
    assert rows[broken]["health_state"] == "failing"
    assert rows[broken]["website_status"] == "disabled"
    assert rows[broken]["action"] == "repair"
    assert rows[broken]["last_error"]["missing_field"] == "chapter_list"


def test_retried_failures_of_one_logical_job_count_once_not_per_attempt():
    """F-29: Celery's autoretry_for runs the same task body fresh up to
    max_retries+1 times for ONE logical failure. Recording health on every
    attempt advances consecutive_failures by 3 for a single transient
    outage that just outlasts one job's retry window -- indistinguishable
    from three separately-observed failures, defeating DEGRADE_AFTER's
    "repeated, separated evidence" design. Only the final, truly-exhausted
    attempt should count.
    """
    from backend_fastapi.app.services.scraper_workflow_service import (
        ScraperWorkflowService,
    )

    domain = f"retry-{uuid.uuid4().hex[:6]}.com"
    session = SessionLocal()
    try:
        _approve(session, domain)
        manga = Manga(
            title="RetryTest",
            source_url=f"https://{domain}/manga/x",
            type="manga",
            status="ongoing",
        )
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://{domain}/manga/x/ch-1",
            pages=[],
            ingestion_status="pending",
        )
        session.add(chapter)
        session.commit()
        chapter_id = chapter.id
    finally:
        session.close()

    # Mirror Celery's autoretry_for=(Exception,), max_retries=3: the same
    # task body invoked fresh 3 times (retries 0, 1, 2) for one logical job,
    # only the last of which is the truly-exhausted final attempt.
    max_retries = 3
    for attempt in range(max_retries):
        session = SessionLocal()
        try:
            service = ScraperWorkflowService(session)
            with mock.patch(
                "backend_fastapi.app.scrapers.base_scraper.BaseScraper.scrape_chapter",
                side_effect=ExtractionError(
                    "boom", url=f"https://{domain}/manga/x/ch-1"
                ),
            ):
                try:
                    service.process_chapter_scrape(
                        chapter_id,
                        is_final_attempt=(attempt >= max_retries - 1),
                    )
                except Exception:
                    pass
        finally:
            session.close()

    session = SessionLocal()
    try:
        state = health._load(session, domain)
        assert state["consecutive_failures"] == 1
    finally:
        session.close()
