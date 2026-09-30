"""Ingestion correctness (SRS 1G.2, 1G.4, 1G.5).

Covers: URL canonicalization variance in duplicate detection; the duplicate
response carrying the existing series; typed extraction errors naming field,
URL, selector, and module; scraper failures contained with structured detail;
chapter-by-chapter progress visibility.
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
    ScrapingJob,
    User,
    UserRole,
)
from backend_fastapi.app.scrapers.errors import ExtractionError, error_details_for
from backend_fastapi.app.services.url_guard import canonicalize_source_url


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"ing-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="ING",
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


def _approve(session, domain: str) -> None:
    session.add(
        ApprovedSourceDomain(
            base_url=f"https://{domain}", domain=domain, status="active"
        )
    )
    session.commit()


# ---------------------------------------------------------------------------
# 1G.4.1 — URL canonicalization
# ---------------------------------------------------------------------------


def test_canonicalize_collapses_specified_variance():
    canonical = canonicalize_source_url("https://example.com/manga/title")
    assert canonicalize_source_url("http://example.com/manga/title/") == canonical
    assert canonicalize_source_url("https://WWW.Example.COM/manga/title") == canonical
    assert (
        canonicalize_source_url(
            "https://example.com/manga/title?utm_source=x&fbclid=abc"
        )
        == canonical
    )
    assert (
        canonicalize_source_url("https://example.com:443/manga/title#chapter-2")
        == canonical
    )
    # Identifying query params survive (sorted).
    assert (
        canonicalize_source_url("https://example.com/series?id=42&utm_medium=y")
        == "https://example.com/series?id=42"
    )


def test_duplicate_detected_across_url_variants(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
        domain = f"dup-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain)
        existing = Manga(
            title="Dup Series",
            source_url=f"https://www.{domain}/manga/dup-title/",
            type="manga",
            status="ongoing",
        )
        session.add(existing)
        session.commit()
        session.refresh(existing)
        existing_id = existing.id
    finally:
        session.close()

    # Same page, different protocol/host-case/tracking-noise spelling.
    resp = fastapi_client.post(
        "/api/admin/series",
        headers=_h(pa_id),
        json={"url": f"http://{domain}/manga/dup-title?utm_source=share"},
    )
    assert resp.status_code == 409
    err = resp.json()["error"]
    assert err["code"] == "DUPLICATE_MANGA_URL"
    assert err["message"].startswith("Invalid — this URL has already been added")
    # 1G.4.3: the existing series is returned so the submitter can find it.
    assert err["details"]["existing_series_id"] == existing_id


# ---------------------------------------------------------------------------
# 1G.5.4 — typed extraction errors
# ---------------------------------------------------------------------------


def test_extraction_error_carries_structured_detail():
    exc = ExtractionError(
        "Could not extract the chapter list from this page.",
        url="https://example.com/manga/title",
        missing_field="chapter_list",
        selector_used=".chapter-list-item",
        scraper_module="example.com_v2",
    )
    details = error_details_for(exc)
    assert details == {
        "url": "https://example.com/manga/title",
        "missing_field": "chapter_list",
        "selector_used": ".chapter-list-item",
        "scraper_module": "example.com_v2",
        "message": "Could not extract the chapter list from this page.",
    }

    # Untyped failures still name the URL (1G.5.3: every failure names the
    # field/url/reason to the extent known — never an empty body).
    plain = error_details_for(ValueError("boom"), url="https://x.com/y")
    assert plain["url"] == "https://x.com/y"
    assert plain["message"] == "boom"


def test_zero_pages_is_failure_not_success():
    """1G.9.4: extraction returning no usable data must never report success."""
    from backend_fastapi.app.scrapers.base_scraper import BaseScraper

    scraper = BaseScraper("zero-pages.example")
    scraper.config = {"page_images": ".pages img"}

    class FakeSoup:
        def select(self, sel):
            return []

        def select_one(self, sel):
            return None

        def __str__(self):
            return "<html></html>"

    with mock.patch.object(BaseScraper, "_fetch_html", return_value=FakeSoup()):
        with mock.patch(
            "backend_fastapi.app.scrapers.ai_fallback.AIFallbackService."
            "extract_selectors",
            return_value=None,
        ):
            with pytest.raises(ExtractionError) as excinfo:
                scraper.scrape_chapter("https://zero-pages.example/ch/1")
    err = excinfo.value
    assert err.missing_field in ("pages", "page_images")
    assert err.url == "https://zero-pages.example/ch/1"


def test_chapter_scrape_failure_marks_status_and_keeps_pages():
    """1G.12.2: a failed rescrape leaves existing pages untouched; the chapter
    is marked failed, and the exception stays contained at the task boundary."""
    from backend_fastapi.app.services.scraper_workflow_service import (
        ScraperWorkflowService,
    )
    from backend_fastapi.app.scrapers.base_scraper import BaseScraper

    session = SessionLocal()
    try:
        manga = Manga(
            title="Contained",
            source_url=f"https://cont-{uuid.uuid4().hex[:6]}.com/manga/x",
            type="manga",
            status="ongoing",
        )
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://cont.example/ch/{uuid.uuid4().hex[:6]}",
            pages=["https://cont.example/p1.jpg"],
            ingestion_status="complete",
        )
        session.add(chapter)
        session.commit()
        chapter_id = chapter.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        service = ScraperWorkflowService(session)
        with mock.patch.object(
            BaseScraper,
            "scrape_chapter",
            side_effect=ExtractionError(
                "The source page returned no images.",
                url="https://cont.example/ch/1",
                missing_field="pages",
                selector_used=".pages img",
                scraper_module="cont.example_v1",
            ),
        ):
            with pytest.raises(ExtractionError):
                service.process_chapter_scrape(chapter_id)
    finally:
        session.close()

    session = SessionLocal()
    try:
        refreshed = session.get(Chapter, chapter_id)
        assert refreshed.ingestion_status == "failed"
        # Existing pages untouched.
        assert refreshed.pages == ["https://cont.example/p1.jpg"]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 1G.2.3 — progress visibility
# ---------------------------------------------------------------------------


def test_ingestion_progress_endpoint(fastapi_client):
    session = SessionLocal()
    try:
        mod_id = _user(session, UserRole.MODERATOR)
        manga = Manga(
            title="Progress Series",
            source_url=f"https://prog-{uuid.uuid4().hex[:6]}.com/manga/p",
            type="manga",
            status="ongoing",
            ingestion_status="scraping",
        )
        session.add(manga)
        session.flush()
        for i, st in enumerate(["complete", "complete", "queued", "failed"], 1):
            session.add(
                Chapter(
                    manga_id=manga.id,
                    chapter_number=i,
                    chapter_url=f"https://prog.example/{uuid.uuid4().hex[:8]}",
                    ingestion_status=st,
                    pages=["p"] if st == "complete" else None,
                )
            )
        session.commit()
        manga_id = manga.id
    finally:
        session.close()

    resp = fastapi_client.get(
        f"/api/admin/series/{manga_id}/ingestion", headers=_h(mod_id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ingestion_status"] == "scraping"
    assert body["chapters_total"] == 4
    assert body["chapters_complete"] == 2
    assert body["chapters_failed"] == 1
    assert body["chapters_pending"] == 1
    assert body["progress"] == "2 of 4"


def test_scraping_job_records_submitter(fastapi_client):
    """The submitter is recorded on the job so the series' added_by (1G.1.2)
    and the completion notification (1G.2.2) know who to credit."""
    session = SessionLocal()
    try:
        mod_id = _user(session, UserRole.MODERATOR)
        domain = f"sub-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain)
    finally:
        session.close()

    url = f"https://{domain}/manga/who-submitted"
    with mock.patch(
        "backend_fastapi.app.tasks.scraper_tasks.process_manga_scrape"
    ) as task:
        task.delay.return_value = None
        with mock.patch(
            "backend_fastapi.app.services.url_guard._host_addresses",
            return_value=["93.184.216.34"],
        ):
            resp = fastapi_client.post(
                "/api/admin/series", headers=_h(mod_id), json={"url": url}
            )
    assert resp.status_code == 201, resp.text

    session = SessionLocal()
    try:
        job = (
            session.query(ScrapingJob)
            .filter(ScrapingJob.source_url == url)
            .order_by(ScrapingJob.id.desc())
            .first()
        )
        assert job is not None
        assert job.requested_by == mod_id
    finally:
        session.close()
