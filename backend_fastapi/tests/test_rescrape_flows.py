"""Rescrape flows (SRS 1G.12): the Fix button and staged full rescrape.

Covers: atomic Fix dedupe with all clickers notified (1G.12.2A); the
"source may be broken" banner that warns but does not block (1G.12.2B); the
consolidated repeat alert; staged full-series rescrape that aborts rather
than emptying a series (1G.12.4); history/bookmark preservation; snapshot +
PA rollback; typed-name confirmation; moderator FORBIDDEN on full rescrape.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    AdminAuditLog,
    Bookmark,
    Chapter,
    Manga,
    Notification,
    ReadHistory,
    ScrapingJob,
    User,
    UserRole,
)
from backend_fastapi.app.services import rescrape_service


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"rf-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="RF",
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


def _series_with_chapters(session, n=2, *, pages=True) -> tuple[int, list[int]]:
    manga = Manga(
        title=f"Series-{uuid.uuid4().hex[:6]}",
        source_url=f"https://rf-{uuid.uuid4().hex[:6]}.com/manga/s",
        type="manga",
        status="ongoing",
    )
    session.add(manga)
    session.flush()
    ids = []
    for i in range(1, n + 1):
        c = Chapter(
            manga_id=manga.id,
            chapter_number=i,
            chapter_url=f"https://rf.example/{uuid.uuid4().hex[:8]}",
            pages=[f"https://rf.example/p{i}.jpg"] if pages else None,
            ingestion_status="complete" if pages else "queued",
            scraped_at=None,
        )
        session.add(c)
        session.flush()
        ids.append(c.id)
    session.commit()
    return manga.id, ids


# ---------------------------------------------------------------------------
# 1G.12.2A — Fix dedupe + everyone notified
# ---------------------------------------------------------------------------


def test_fix_dedupe_single_job_all_clickers_notified():
    session = SessionLocal()
    try:
        admin_a = _user(session, UserRole.SECONDARY, secondary=True)
        admin_b = _user(session, UserRole.SECONDARY, secondary=True)
        _, chapter_ids = _series_with_chapters(session, 1)
        chapter = session.get(Chapter, chapter_ids[0])

        with mock.patch(
            "backend_fastapi.app.tasks.scraper_tasks.process_chapter_scrape"
        ) as task:
            first = rescrape_service.fix_chapter(session, chapter, actor_id=admin_a)
            assert first["status"] == "queued"
            assert task.apply_async.called

            second = rescrape_service.fix_chapter(session, chapter, actor_id=admin_b)
        # 1G.12.2A: no second job; the banner message is shown instead.
        assert second["status"] == "already_in_progress"
        assert "already being rescripted" in second["message"]

        jobs = (
            session.query(ScrapingJob)
            .filter(ScrapingJob.source_url == chapter.chapter_url)
            .all()
        )
        assert len(jobs) == 1
        assert set(jobs[0].subscribers) == {admin_a, admin_b}

        # Completion: ALL clickers are notified, not just the first.
        rescrape_service.notify_fix_subscribers(session, chapter, success=True)
        notes = (
            session.query(Notification)
            .filter(Notification.type == "chapter.fix_completed")
            .all()
        )
        notified = {n.user_id for n in notes if n.data.get("chapter_id") == chapter.id}
        assert {admin_a, admin_b} <= notified
        session.refresh(jobs[0])
        assert jobs[0].status == "success"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 1G.12.2B — source-may-be-broken banner
# ---------------------------------------------------------------------------


def test_recent_fix_shows_banner_but_does_not_block():
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.SECONDARY, secondary=True)
        _, chapter_ids = _series_with_chapters(session, 1)
        chapter = session.get(Chapter, chapter_ids[0])
        chapter.scraped_at = datetime.utcnow()
        chapter.ingestion_status = "complete"
        session.commit()

        with mock.patch(
            "backend_fastapi.app.tasks.scraper_tasks.process_chapter_scrape"
        ):
            warned = rescrape_service.fix_chapter(session, chapter, actor_id=admin_id)
            assert warned["status"] == "recently_fixed"
            assert "may be damaged or scrambled" in warned["banner"]
            assert warned["options"] == [
                "rescrape_anyway",
                "view_source_page",
                "dismiss",
            ]
            assert warned["source_url"] == chapter.chapter_url

            # "Rescrape anyway" forces it through.
            forced = rescrape_service.fix_chapter(
                session, chapter, actor_id=admin_id, force=True
            )
            assert forced["status"] == "queued"
    finally:
        session.close()


def test_repeated_broken_cycles_one_consolidated_alert():
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.SECONDARY, secondary=True)
        _, chapter_ids = _series_with_chapters(session, 1)
        chapter_id = chapter_ids[0]

        with mock.patch(
            "backend_fastapi.app.tasks.scraper_tasks.process_chapter_scrape"
        ):
            for _ in range(rescrape_service.CONSOLIDATED_ALERT_AFTER + 2):
                chapter = session.get(Chapter, chapter_id)
                chapter.scraped_at = datetime.utcnow()
                chapter.ingestion_status = "complete"
                session.commit()
                rescrape_service.fix_chapter(
                    session, chapter, actor_id=admin_id, force=True
                )
                # Simulate the rescrape finishing so the next Fix re-arms.
                job = (
                    session.query(ScrapingJob)
                    .filter(ScrapingJob.source_url == chapter.chapter_url)
                    .order_by(ScrapingJob.id.desc())
                    .first()
                )
                job.status = "success"
                session.commit()

        alerts = (
            session.query(Notification)
            .filter(Notification.type == "chapter.repeatedly_broken")
            .all()
        )
        mine = [a for a in alerts if a.data.get("chapter_id") == chapter_id]
        # ONE consolidated alert, not one per click.
        assert len(mine) == 1
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 1G.12.3 / 1G.12.4 — staged full rescrape
# ---------------------------------------------------------------------------


def _mock_scraper(chapters: list[dict], pages_by_url: dict):
    """Patch BaseScraper to return staged data without network."""
    manga_patch = mock.patch(
        "backend_fastapi.app.scrapers.base_scraper.BaseScraper.scrape_manga",
        return_value={
            "title": "Staged",
            "description": "",
            "cover": "",
            "chapters": chapters,
        },
    )
    chapter_patch = mock.patch(
        "backend_fastapi.app.scrapers.base_scraper.BaseScraper.scrape_chapter",
        side_effect=lambda url, **kw: {"pages": pages_by_url.get(url, [])},
    )
    return manga_patch, chapter_patch


def test_staged_rescrape_aborts_rather_than_emptying():
    session = SessionLocal()
    try:
        manga_id, chapter_ids = _series_with_chapters(session, 3)
        original_pages = {cid: session.get(Chapter, cid).pages for cid in chapter_ids}

        # Parser broken: only 1 chapter comes back where 3 exist.
        manga_patch, chapter_patch = _mock_scraper(
            [{"url": "https://rf.example/only", "title": "1", "number": 1.0}],
            {"https://rf.example/only": ["https://rf.example/p.jpg"]},
        )
        with manga_patch, chapter_patch:
            result = rescrape_service.run_staged_rescrape(session, manga_id)

        assert result["status"] == "aborted"
        assert "1 chapters where 3 exist" in result["reason"]
        assert "No data was changed" in result["reason"]

        # Existing data untouched.
        for cid, pages in original_pages.items():
            assert session.get(Chapter, cid).pages == pages

        note = (
            session.query(Notification)
            .filter(Notification.type == "series.rescrape_aborted")
            .order_by(Notification.id.desc())
            .first()
        )
        assert note is not None and note.data["series_id"] == manga_id
    finally:
        session.close()


def test_staged_rescrape_replaces_and_preserves_history():
    session = SessionLocal()
    try:
        user_id = _user(session, UserRole.USER)
        manga_id, chapter_ids = _series_with_chapters(session, 2)
        # Reading history + bookmark referencing chapter rows.
        session.add(
            ReadHistory(user_id=user_id, manga_id=manga_id, chapter_id=chapter_ids[0])
        )
        session.add(
            Bookmark(user_id=user_id, manga_id=manga_id, chapter_id=chapter_ids[1])
        )
        session.commit()

        chapters = [
            {
                "url": f"https://rf.example/new{i}",
                "title": f"Ch {i}",
                "number": float(i),
            }
            for i in (1, 2)
        ]
        pages_by_url = {
            "https://rf.example/new1": ["https://rf.example/new1-p1.jpg"],
            "https://rf.example/new2": ["https://rf.example/new2-p1.jpg"],
        }
        secondary_id = _user(session, UserRole.SECONDARY, secondary=True)
        manga_patch, chapter_patch = _mock_scraper(chapters, pages_by_url)
        with manga_patch, chapter_patch:
            result = rescrape_service.run_staged_rescrape(
                session, manga_id, actor_id=secondary_id
            )

        assert result["status"] == "success"
        assert result["chapters_total"] == 2

        # 1G.12.3: audited with actor, series, chapter count, and outcome —
        # and the initiating administrator (who may not be the PA) is
        # notified directly, not only the PA's bell.
        audit = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "RESCRAPE_SERIES_OUTCOME")
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert audit is not None
        assert audit.user_id == secondary_id
        assert audit.metadata_json["series_id"] == manga_id
        assert audit.metadata_json["chapter_count"] == 2
        assert audit.metadata_json["outcome"] == "success"

        completion_note = (
            session.query(Notification)
            .filter(Notification.type == "series.rescraped")
            .filter(Notification.user_id == secondary_id)
            .order_by(Notification.id.desc())
            .first()
        )
        assert completion_note is not None

        # Chapter rows survive in place -> history/bookmarks intact.
        session.expire_all()
        c1 = session.get(Chapter, chapter_ids[0])
        assert c1.pages == ["https://rf.example/new1-p1.jpg"]
        history = session.query(ReadHistory).filter_by(user_id=user_id).all()
        assert history and history[0].chapter_id == chapter_ids[0]
        bookmark = session.query(Bookmark).filter_by(user_id=user_id).first()
        assert bookmark.chapter_id == chapter_ids[1]

        # One prior snapshot retained; rollback restores the old pages.
        manga = session.get(Manga, manga_id)
        rollback = rescrape_service.rollback_series(session, manga)
        assert rollback["restored_chapters"] == 2
        session.expire_all()
        assert session.get(Chapter, chapter_ids[0]).pages == [
            "https://rf.example/p1.jpg"
        ]
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Endpoint contracts
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_rescrape_limiter():
    """test_admin_scraper leaves a limit=1 limiter behind; reset it here."""
    from backend_fastapi.app.api.routers import admin as admin_router
    from backend_fastapi.app.services.admin_service import RescrapeRateLimiter

    admin_router._rescrape_limiter = RescrapeRateLimiter(limit=1000, window_seconds=60)
    yield


def test_full_rescrape_requires_typed_confirmation(fastapi_client):
    session = SessionLocal()
    try:
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
        manga_id, _ = _series_with_chapters(session, 1)
        title = session.get(Manga, manga_id).title
    finally:
        session.close()

    wrong = fastapi_client.post(
        f"/api/admin/series/{manga_id}/rescrape",
        headers=_h(sec_id),
        json={"confirm_title": "wrong name"},
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["field"] == "confirm_title"

    with mock.patch(
        "backend_fastapi.app.tasks.scraper_tasks.staged_series_rescrape"
    ) as task:
        task.delay.return_value = mock.Mock(id="t1")
        ok = fastapi_client.post(
            f"/api/admin/series/{manga_id}/rescrape",
            headers=_h(sec_id),
            json={"confirm_title": title},
        )
    assert ok.status_code == 200
    assert ok.json()["result"]["status"] == "queued"
    # The initiating administrator is threaded through to the task so
    # completion can be routed to them, not only the PA's bell (1G.12.3).
    task.delay.assert_called_once_with(manga_id, sec_id)


def test_moderator_forbidden_on_full_rescrape_by_direct_call(fastapi_client):
    """1G.12.3 verified by direct API call as a Moderator."""
    session = SessionLocal()
    try:
        mod_id = _user(session, UserRole.MODERATOR)
        manga_id, _ = _series_with_chapters(session, 1)
        title = session.get(Manga, manga_id).title
    finally:
        session.close()

    resp = fastapi_client.post(
        f"/api/admin/series/{manga_id}/rescrape",
        headers=_h(mod_id),
        json={"confirm_title": title},
    )
    assert resp.status_code == 403
