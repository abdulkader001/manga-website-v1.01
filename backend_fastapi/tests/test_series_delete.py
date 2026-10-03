"""Deleting a series works once readers have used it (plan.md P0-3).

The owner's report: deleting a manga failed. On PostgreSQL the bulk chapter
delete hit foreign keys from reading history, bookmarks and the OCR /
translation caches that had no delete rule. These tests create every kind of
row that points at a series, then delete through each admin path. On
PostgreSQL (CI) the foreign keys are enforced, so the old code fails here.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    Bookmark,
    Chapter,
    Manga,
    OcrCache,
    ReadHistory,
    ScrapingJob,
    TranslationCache,
    User,
    UserRole,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _owner() -> int:
    with SessionLocal() as session:
        user = User(
            email=f"del-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Owner",
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        return user.id


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def _used_series(reader_id: int) -> tuple[int, int]:
    """A series a reader opened and bookmarked, with a translated page and a
    scraping job. Returns ``(manga_id, scraping_job_id)``."""

    tag = uuid.uuid4().hex
    with SessionLocal() as session:
        manga = Manga(title=f"Used {tag}", source_url=f"https://src.example/{tag}")
        session.add(manga)
        session.flush()
        chapter = Chapter(manga_id=manga.id, chapter_number=1, chapter_url=f"https://src.example/{tag}/1")
        session.add(chapter)
        session.flush()
        session.add(ReadHistory(user_id=reader_id, manga_id=manga.id, chapter_id=chapter.id))
        session.add(Bookmark(user_id=reader_id, manga_id=manga.id, chapter_id=chapter.id))
        ocr = OcrCache(chapter_id=chapter.id, page_index=0, text_boxes=[])
        session.add(ocr)
        session.flush()
        session.add(
            TranslationCache(
                chapter_id=chapter.id, page_index=0, target_lang="en", translated_boxes=[], ocr_cache_id=ocr.id
            )
        )
        job = ScrapingJob(manga_id=manga.id, source_url=f"https://src.example/{tag}", status="success")
        session.add(job)
        session.commit()
        return manga.id, job.id


def _gone(manga_id: int, job_id: int) -> None:
    with SessionLocal() as session:
        assert session.get(Manga, manga_id) is None
        assert session.query(Chapter).filter(Chapter.manga_id == manga_id).count() == 0
        assert session.query(ReadHistory).filter(ReadHistory.manga_id == manga_id).count() == 0
        assert session.query(Bookmark).filter(Bookmark.manga_id == manga_id).count() == 0
        job = session.get(ScrapingJob, job_id)
        assert job is not None and job.manga_id is None  # history kept, unlinked


def test_deleting_a_series_readers_used(fastapi_client):
    owner = _owner()
    manga_id, job_id = _used_series(owner)
    response = fastapi_client.delete(f"/api/v1/admin/series/{manga_id}", headers=_h(owner))
    assert response.status_code == 200, response.text
    assert response.json()["deleted_chapters"] == 1
    _gone(manga_id, job_id)


def test_deleting_a_missing_series_is_404(fastapi_client):
    response = fastapi_client.delete("/api/v1/admin/series/999999999", headers=_h(_owner()))
    assert response.status_code == 404


def test_bulk_delete_task_removes_used_series():
    from backend_fastapi.app.tasks.scraper_tasks import bulk_delete_series_task

    owner = _owner()
    first = _used_series(owner)
    second = _used_series(owner)
    bulk_delete_series_task.run([first[0], second[0]])
    _gone(*first)
    _gone(*second)


def test_delete_all_and_purge_with_used_series(fastapi_client):
    owner = _owner()
    used = _used_series(owner)
    response = fastapi_client.post("/api/v1/admin/maintenance/purge-all-images", headers=_h(owner), json={})
    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        assert session.query(OcrCache).count() == 0
        assert session.query(TranslationCache).count() == 0
    response = fastapi_client.post("/api/v1/admin/maintenance/delete-all-manga", headers=_h(owner), json={})
    assert response.status_code == 200, response.text
    _gone(*used)
