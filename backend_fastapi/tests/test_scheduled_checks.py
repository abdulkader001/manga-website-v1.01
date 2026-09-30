"""Scheduled new-chapter detection (SRS 1G.12A).

Covers: Phase 2 starts automatically after initial ingestion; the check is
lightweight (chapter-list page only) and only ingests new chapters; per-series
override beats the website default; quiet hours and the enabled toggle are
honoured; followers are notified on a new chapter; failures don't escalate on
a single miss.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    ApprovedSourceDomain,
    Bookmark,
    Chapter,
    Manga,
    Notification,
    User,
    UserRole,
)
from backend_fastapi.app.services import scheduled_checks_service as svc


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"sc-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="SC",
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


def _approve(session, domain: str, **settings) -> ApprovedSourceDomain:
    entry = ApprovedSourceDomain(
        base_url=f"https://{domain}",
        domain=domain,
        status="active",
        check_settings=settings or None,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def _series(session, domain: str, **kwargs) -> Manga:
    manga = Manga(
        title=f"Series-{uuid.uuid4().hex[:6]}",
        source_url=f"https://{domain}/manga/{uuid.uuid4().hex[:6]}",
        type="manga",
        status="ongoing",
        **kwargs,
    )
    session.add(manga)
    session.commit()
    session.refresh(manga)
    return manga


def test_schedule_uses_default_window_with_jitter():
    session = SessionLocal()
    try:
        domain = f"sched-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain)
        manga = _series(session, domain)
        now = datetime.utcnow()
        next_at = svc.schedule_next_check(session, manga, now=now)
        delta_hours = (next_at - now).total_seconds() / 3600
        # Default interval 10h +/- 2h jitter (1G.12A.2's 8-12h window).
        assert 7.5 <= delta_hours <= 12.5
    finally:
        session.close()


def test_series_override_beats_website_default():
    session = SessionLocal()
    try:
        domain = f"ovr-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain, interval_hours=12)
        manga = _series(session, domain, check_interval_hours=6)
        now = datetime.utcnow()
        next_at = svc.schedule_next_check(session, manga, now=now)
        delta_hours = (next_at - now).total_seconds() / 3600
        # 6h override, default jitter 2h -> [4, 8], not anywhere near 12h.
        assert 3.5 <= delta_hours <= 8.5
    finally:
        session.close()


def test_disabled_website_and_quiet_hours_excluded_from_due():
    session = SessionLocal()
    try:
        disabled_domain = f"dis-{uuid.uuid4().hex[:6]}.com"
        quiet_domain = f"quiet-{uuid.uuid4().hex[:6]}.com"
        live_domain = f"live-{uuid.uuid4().hex[:6]}.com"

        _approve(session, disabled_domain, enabled=False)
        now = datetime.utcnow()
        _approve(session, quiet_domain, quiet_hours=[now.hour, (now.hour + 1) % 24])
        _approve(session, live_domain)

        m_disabled = _series(
            session, disabled_domain, next_check_at=now - timedelta(minutes=5)
        )
        m_quiet = _series(
            session, quiet_domain, next_check_at=now - timedelta(minutes=5)
        )
        m_live = _series(session, live_domain, next_check_at=now - timedelta(minutes=5))

        due_ids = {m.id for m in svc.due_series(session, now=now)}
        assert m_disabled.id not in due_ids
        assert m_quiet.id not in due_ids
        assert m_live.id in due_ids
    finally:
        session.close()


def test_check_is_lightweight_ingests_only_new_chapters_and_notifies():
    session = SessionLocal()
    try:
        follower_id = _user(session, UserRole.USER)
        domain = f"light-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain)
        manga = _series(session, domain)
        session.add(
            Chapter(
                manga_id=manga.id,
                chapter_number=1,
                chapter_url=f"https://{domain}/ch/1",
                pages=["p1"],
                ingestion_status="complete",
            )
        )
        session.add(Bookmark(user_id=follower_id, manga_id=manga.id))
        session.commit()
        manga_id = manga.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        manga = session.get(Manga, manga_id)
        with mock.patch(
            "backend_fastapi.app.scrapers.base_scraper.BaseScraper.scrape_manga",
            return_value={
                "title": manga.title,
                "chapters": [
                    {"url": f"https://{domain}/ch/1", "number": 1.0, "title": "1"},
                    {"url": f"https://{domain}/ch/2", "number": 2.0, "title": "2"},
                ],
            },
        ) as scrape_manga:
            with mock.patch(
                "backend_fastapi.app.tasks.scraper_tasks.process_chapter_scrape"
            ) as task:
                result = svc.run_check(session, manga)
        # A single request to the chapter-list page — never a deep crawl.
        assert scrape_manga.call_count == 1
        assert result["status"] == "new_chapters_found"
        assert result["count"] == 1
        assert task.delay.called
    finally:
        session.close()

    session = SessionLocal()
    try:
        # Existing chapter untouched; new chapter created queued.
        chapters = session.query(Chapter).filter(Chapter.manga_id == manga_id).all()
        by_number = {float(c.chapter_number): c for c in chapters}
        assert by_number[1.0].pages == ["p1"]
        assert by_number[2.0].ingestion_status == "queued"

        note = (
            session.query(Notification)
            .filter(Notification.type == "chapter.new")
            .filter(Notification.user_id == follower_id)
            .order_by(Notification.id.desc())
            .first()
        )
        assert note is not None
        assert "2" in note.title and manga.title in note.title

        refreshed = session.get(Manga, manga_id)
        assert refreshed.next_check_at is not None
    finally:
        session.close()


def test_single_failure_does_not_escalate():
    session = SessionLocal()
    try:
        domain = f"fail-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain)
        manga = _series(session, domain)
        manga_id = manga.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        manga = session.get(Manga, manga_id)
        with mock.patch(
            "backend_fastapi.app.scrapers.base_scraper.BaseScraper.scrape_manga",
            side_effect=Exception("network blip"),
        ):
            result = svc.run_check(session, manga)
        assert result["status"] == "failed"
    finally:
        session.close()

    session = SessionLocal()
    try:
        entry = session.query(ApprovedSourceDomain).filter_by(domain=domain).first()
        # One failure alone must not disable the website (1G.12A.7).
        assert entry.status == "active"
        refreshed = session.get(Manga, manga_id)
        # Retried at the next cycle — rescheduled, not abandoned.
        assert refreshed.next_check_at is not None
    finally:
        session.close()


def test_admin_controls_endpoints(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
        mod_id = _user(session, UserRole.MODERATOR)
        domain = f"ctrl-{uuid.uuid4().hex[:6]}.com"
        entry = _approve(session, domain)
        manga = _series(session, domain)
        entry_id = entry.id
        manga_id = manga.id
    finally:
        session.close()

    # Moderators cannot control scraping frequency (1G.12A.4).
    denied = fastapi_client.put(
        f"/api/admin/approved-domains/{entry_id}/check-settings",
        headers=_h(mod_id),
        json={"interval_hours": 6},
    )
    assert denied.status_code == 403

    updated = fastapi_client.put(
        f"/api/admin/approved-domains/{entry_id}/check-settings",
        headers=_h(pa_id),
        json={"interval_hours": 6, "jitter_hours": 1, "enabled": True},
    )
    assert updated.status_code == 200

    invalid = fastapi_client.put(
        f"/api/admin/approved-domains/{entry_id}/check-settings",
        headers=_h(pa_id),
        json={"interval_hours": 999},
    )
    assert invalid.status_code == 422

    override = fastapi_client.put(
        f"/api/admin/series/{manga_id}/check-override",
        headers=_h(pa_id),
        json={"interval_hours": 3},
    )
    assert override.status_code == 200
    assert override.json()["check_interval_hours"] == 3


def test_dashboard_reports_run_counts_and_per_website_visibility(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
        domain = f"dash2-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain)
        manga = _series(session, domain)
        manga_id = manga.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        manga = session.get(Manga, manga_id)
        with mock.patch(
            "backend_fastapi.app.scrapers.base_scraper.BaseScraper.scrape_manga",
            return_value={"title": manga.title, "chapters": []},
        ):
            svc.run_check(session, manga)
    finally:
        session.close()

    resp = fastapi_client.get(
        "/api/admin/scrapers/scheduled-checks/dashboard", headers=_h(pa_id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_24h"]["checked"] >= 1
    rows = {w["domain"]: w for w in body["websites"]}
    assert rows[domain]["series_tracked"] >= 1
    assert rows[domain]["next_check"] is not None


def test_series_ingestion_endpoint_shows_check_visibility(fastapi_client):
    session = SessionLocal()
    try:
        mod_id = _user(session, UserRole.MODERATOR)
        domain = f"iv-{uuid.uuid4().hex[:6]}.com"
        _approve(session, domain)
        manga = _series(
            session,
            domain,
            ingestion_status="complete",
            check_interval_hours=5,
            next_check_at=datetime.utcnow() + timedelta(hours=5),
        )
        manga_id = manga.id
    finally:
        session.close()

    resp = fastapi_client.get(
        f"/api/admin/series/{manga_id}/ingestion", headers=_h(mod_id)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["check_interval_hours"] == 5
    assert body["next_check_at"] is not None
