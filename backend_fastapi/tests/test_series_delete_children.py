"""plan.md P0-3: deleting series works once readers and translations exist.

On PostgreSQL, deleting a series, "delete all manga", bulk delete and "purge
all images" answered HTTP 500 as soon as a reader had opened a chapter or a
page had been translated: reading history, chapter bookmarks and the
OCR/translation caches pointed at the chapters with no delete rule. The old
tests only deleted series nobody had touched, and SQLite does not enforce
foreign keys, so nothing noticed.

Each case runs twice on PostgreSQL: with the delete rules of migration
``20261018_cascade_series_children``, and with the old rules (a database that
missed the migration), where only the explicit deletes in
``services/series_delete.py`` keep it working.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from backend_fastapi.app.core.db import SessionLocal, engine
from backend_fastapi.app.models import (
    Bookmark,
    Chapter,
    Manga,
    OcrCache,
    ReadHistory,
    ScrapingJob,
    TranslationCache,
)

from _support import staff

# (table, column, referenced table, rule after the migration)
_FOREIGN_KEYS = (
    ("bookmarks", "chapter_id", "chapters", "CASCADE"),
    ("bookmarks", "manga_id", "manga", "CASCADE"),
    ("read_history", "chapter_id", "chapters", "CASCADE"),
    ("read_history", "manga_id", "manga", "CASCADE"),
    ("ocr_cache", "chapter_id", "chapters", "CASCADE"),
    ("translation_cache", "chapter_id", "chapters", "CASCADE"),
    ("translation_cache", "ocr_cache_id", "ocr_cache", "SET NULL"),
    ("scraping_jobs", "manga_id", "manga", "SET NULL"),
)


def _set_rules(cascade: bool) -> None:
    """Put the foreign keys in the state before (False) or after the migration."""

    with engine.begin() as conn:
        for table, column, referred, after in _FOREIGN_KEYS:
            rows = conn.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey) "
                    "WHERE c.contype = 'f' AND c.conrelid = CAST(:t AS regclass) "
                    "AND c.confrelid = CAST(:r AS regclass) AND a.attname = :c"
                ),
                {"t": table, "r": referred, "c": column},
            ).scalars()
            for name in list(rows):
                conn.execute(text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
            rule = f" ON DELETE {after}" if cascade else ""
            conn.execute(
                text(
                    f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_{column}_{referred} "
                    f"FOREIGN KEY ({column}) REFERENCES {referred} (id){rule}"
                )
            )


@pytest.fixture(params=["with-migration", "old-rules"])
def rules(request, fastapi_app):
    if engine.dialect.name != "postgresql":
        if request.param == "old-rules":
            pytest.skip("foreign-key rules are only enforced on PostgreSQL")
        yield request.param
        return
    _set_rules(cascade=request.param == "with-migration")
    yield request.param
    _set_rules(cascade=True)


def _series_someone_read() -> dict:
    reader = staff.reader()
    with SessionLocal() as session:
        manga = Manga(title=f"Del-{uuid.uuid4().hex}", source_url=f"https://src.invalid/{uuid.uuid4().hex}")
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://src.invalid/c/{uuid.uuid4().hex}",
            pages=["https://src.invalid/p1.jpg"],
        )
        session.add(chapter)
        session.flush()
        session.add(ReadHistory(user_id=reader, manga_id=manga.id, chapter_id=chapter.id))
        session.add(Bookmark(user_id=reader, manga_id=manga.id, chapter_id=chapter.id))
        ocr = OcrCache(chapter_id=chapter.id, page_index=0, text_boxes=["hi"])
        session.add(ocr)
        session.flush()
        session.add(
            TranslationCache(
                chapter_id=chapter.id,
                page_index=0,
                target_lang="en",
                ocr_cache_id=ocr.id,
                translated_boxes=["hi"],
            )
        )
        job = ScrapingJob(manga_id=manga.id, source_url=manga.source_url)
        session.add(job)
        session.commit()
        return {"manga": manga.id, "chapter": chapter.id, "job": job.id}


def _children_left(ids: dict) -> int:
    with SessionLocal() as session:
        return sum(
            session.query(model).filter(model.chapter_id == ids["chapter"]).count()
            for model in (ReadHistory, Bookmark, OcrCache, TranslationCache)
        )


def test_deleting_a_series_someone_read(fastapi_client, rules):
    owner = staff.owner()
    ids = _series_someone_read()

    response = fastapi_client.delete(f"/api/v1/admin/series/{ids['manga']}", headers=staff.headers(owner))

    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        assert session.get(Manga, ids["manga"]) is None
        assert session.get(Chapter, ids["chapter"]) is None
    assert _children_left(ids) == 0


def test_bulk_delete_task(fastapi_app, rules):
    from backend_fastapi.app.tasks.scraper_tasks import bulk_delete_series_task

    first, second = _series_someone_read(), _series_someone_read()

    bulk_delete_series_task([first["manga"], second["manga"]])

    with SessionLocal() as session:
        assert session.get(Manga, first["manga"]) is None
        assert session.get(Manga, second["manga"]) is None
    assert _children_left(first) == _children_left(second) == 0


def test_delete_all_manga(fastapi_client, rules):
    owner = staff.owner()
    ids = _series_someone_read()

    response = fastapi_client.post(
        "/api/v1/admin/maintenance/delete-all-manga", headers=staff.headers(owner), json={}
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        assert session.query(Manga).count() == 0
    assert _children_left(ids) == 0


def test_purge_all_images(fastapi_client, rules):
    owner = staff.owner()
    ids = _series_someone_read()

    response = fastapi_client.post(
        "/api/v1/admin/maintenance/purge-all-images", headers=staff.headers(owner), json={}
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        assert session.query(OcrCache).count() == 0
        assert session.query(TranslationCache).count() == 0
        # Chapters stay readable: only the caches go.
        assert session.get(Chapter, ids["chapter"]) is not None
