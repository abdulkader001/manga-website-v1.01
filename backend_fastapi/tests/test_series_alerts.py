"""New-chapter alerts reach the readers who bookmarked the series.

A signed-in reader's bookmarks are kept on the server as series ids (the
browser syncs them), and every path that adds chapters to an existing series
tells those readers: the scheduled check (test_scheduled_checks.py) and a
scrape job run on a series that already exists (here).
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import (
    Bookmark,
    Chapter,
    Manga,
    Notification,
    ScrapingJob,
    User,
    UserRole,
)
from backend_fastapi.app.scrapers.base_scraper import BaseScraper
from backend_fastapi.app.services.scraper_workflow_service import ScraperWorkflowService
from backend_fastapi.app.services.series_alerts import notify_followers_of_new_chapters


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session) -> int:
    user = User(
        email=f"al-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Reader",
        role=UserRole.USER,
        provider="magic_link",
    )
    session.add(user)
    session.commit()
    return user.id


def _series(session, host: str) -> Manga:
    manga = Manga(
        title=f"Alert Series {uuid.uuid4().hex[:6]}",
        source_url=f"https://{host}/series/{uuid.uuid4().hex[:6]}",
    )
    session.add(manga)
    session.commit()
    return manga


def _alerts(session, user_id: int) -> list[Notification]:
    return (
        session.query(Notification)
        .filter(Notification.type == "chapter.new", Notification.user_id == user_id)
        .all()
    )


def test_only_readers_who_bookmarked_the_series_are_told():
    with SessionLocal() as session:
        follower, other = _user(session), _user(session)
        manga = _series(session, "alerts.example")
        elsewhere = _series(session, "alerts.example")
        session.add(Bookmark(user_id=follower, manga_id=manga.id))
        session.add(Bookmark(user_id=other, manga_id=elsewhere.id))
        session.commit()

        assert notify_followers_of_new_chapters(session, manga, [2.0, 3.0]) == 1

        notes = _alerts(session, follower)
        assert len(notes) == 1
        # The newest chapter, written the way readers count ("3", not "3.0").
        assert notes[0].title == f"Chapter 3 of {manga.title} is available"
        assert notes[0].target_id == str(manga.id)
        assert _alerts(session, other) == []


def test_nothing_to_tell_without_new_chapters():
    with SessionLocal() as session:
        follower = _user(session)
        manga = _series(session, "alerts.example")
        session.add(Bookmark(user_id=follower, manga_id=manga.id))
        session.commit()
        assert notify_followers_of_new_chapters(session, manga, []) == 0
        assert _alerts(session, follower) == []


def _run_scrape_job(session, manga: Manga | None, url: str, chapters: list[dict]) -> None:
    job = ScrapingJob(manga_id=manga.id if manga else None, status="queued", source_url=url)
    session.add(job)
    session.commit()
    with mock.patch.object(
        BaseScraper, "scrape_manga", return_value={"title": "Alert Series", "chapters": chapters}
    ), mock.patch("backend_fastapi.app.tasks.scraper_tasks.process_chapter_scrape"):
        result = ScraperWorkflowService(session).process_manga_scrape(job.id)
    assert result["status"] == "success", result


def test_a_scrape_of_an_existing_series_tells_its_readers():
    with SessionLocal() as session:
        follower = _user(session)
        manga = _series(session, "alerts-scrape.example")
        session.add(
            Chapter(
                manga_id=manga.id,
                chapter_number=1,
                chapter_url=f"{manga.source_url}/ch/1",
                pages=["p1"],
                ingestion_status="complete",
            )
        )
        session.add(Bookmark(user_id=follower, manga_id=manga.id))
        session.commit()

        _run_scrape_job(
            session,
            manga,
            manga.source_url,
            [
                {"url": f"{manga.source_url}/ch/1", "number": 1.0, "title": "1"},
                {"url": f"{manga.source_url}/ch/2", "number": 2.0, "title": "2"},
            ],
        )

        notes = _alerts(session, follower)
        assert len(notes) == 1
        assert "Chapter 2 of" in notes[0].title


def test_importing_a_new_series_tells_nobody():
    with SessionLocal() as session:
        url = f"https://alerts-new.example/series/{uuid.uuid4().hex[:6]}"
        before = session.query(Notification).filter(Notification.type == "chapter.new").count()
        _run_scrape_job(session, None, url, [{"url": f"{url}/ch/1", "number": 1.0, "title": "1"}])
        after = session.query(Notification).filter(Notification.type == "chapter.new").count()
        assert after == before
