"""Shared OCR/translation cache data model + policy layer (SRS 1H.14).

Data model + get/put/upgrade/eviction policy only - wiring an actual
OCR/MT engine to populate these caches is Part 2 scope.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import Chapter, Manga
from backend_fastapi.app.models.translation_cache import OcrCache, TranslationCache
from backend_fastapi.app.services import translation_cache_service as cache_service


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _make_chapter() -> int:
    with SessionLocal() as db:
        unique = datetime.utcnow().timestamp()
        manga = Manga(
            title="Cache Test Manga",
            slug=f"cache-test-{unique}",
            source_url=f"https://example.com/cache-test-{unique}",
        )
        db.add(manga)
        db.commit()
        db.refresh(manga)
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://example.com/cache-test/{manga.id}",
            pages=[{"url": "https://example.com/p1.jpg"}],
        )
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        return chapter.id


def test_ocr_cache_put_and_get_round_trips():
    chapter_id = _make_chapter()
    with SessionLocal() as db:
        cache_service.put_ocr_cache(
            db,
            chapter_id,
            0,
            ["hello", "world"],
            quality_tier="free",
            provider="tesseract",
        )
        entry = cache_service.get_ocr_cache(db, chapter_id, 0)
        assert entry is not None
        assert entry.text_boxes == ["hello", "world"]
        assert entry.quality_tier == "free"


def test_ocr_cache_upgrade_replaces_free_with_paid():
    chapter_id = _make_chapter()
    with SessionLocal() as db:
        cache_service.put_ocr_cache(db, chapter_id, 0, ["rough"], quality_tier="free")
        cache_service.put_ocr_cache(
            db, chapter_id, 0, ["precise"], quality_tier="paid", provider="cloud_ocr"
        )
        entry = cache_service.get_ocr_cache(db, chapter_id, 0)
        assert entry.text_boxes == ["precise"]
        assert entry.quality_tier == "paid"


def test_ocr_cache_downgrade_is_a_no_op():
    chapter_id = _make_chapter()
    with SessionLocal() as db:
        cache_service.put_ocr_cache(db, chapter_id, 0, ["precise"], quality_tier="paid")
        cache_service.put_ocr_cache(db, chapter_id, 0, ["rough"], quality_tier="free")
        entry = cache_service.get_ocr_cache(db, chapter_id, 0)
        # The paid result is kept; a later free-tier run doesn't clobber it.
        assert entry.text_boxes == ["precise"]
        assert entry.quality_tier == "paid"


def test_translation_cache_is_keyed_per_language():
    chapter_id = _make_chapter()
    with SessionLocal() as db:
        ocr_entry = cache_service.put_ocr_cache(db, chapter_id, 0, ["hello"])
        cache_service.put_translation_cache(
            db, chapter_id, 0, "es", ["hola"], ocr_cache_id=ocr_entry.id
        )
        cache_service.put_translation_cache(
            db, chapter_id, 0, "fr", ["bonjour"], ocr_cache_id=ocr_entry.id
        )

        es_entry = cache_service.get_translation_cache(db, chapter_id, 0, "es")
        fr_entry = cache_service.get_translation_cache(db, chapter_id, 0, "fr")
        assert es_entry.translated_boxes == ["hola"]
        assert fr_entry.translated_boxes == ["bonjour"]
        # No cross-language collision.
        assert es_entry.id != fr_entry.id


def test_evict_stale_removes_old_entries_but_keeps_recent():
    chapter_id = _make_chapter()
    with SessionLocal() as db:
        stale = cache_service.put_ocr_cache(db, chapter_id, 0, ["old"])
        fresh = cache_service.put_ocr_cache(db, chapter_id, 1, ["new"])

        stale_id, fresh_id = stale.id, fresh.id

        db.query(OcrCache).filter(OcrCache.id == stale_id).update(
            {"last_accessed_at": datetime.utcnow() - timedelta(days=200)}
        )
        db.commit()

        removed = cache_service.evict_stale(db, older_than_days=90)
        assert removed == 1

        assert db.get(OcrCache, stale_id) is None
        assert db.get(OcrCache, fresh_id) is not None


def test_evict_stale_removes_translation_rows_before_their_ocr_parent():
    chapter_id = _make_chapter()
    with SessionLocal() as db:
        ocr_entry = cache_service.put_ocr_cache(db, chapter_id, 0, ["hello"])
        translation_entry = cache_service.put_translation_cache(
            db, chapter_id, 0, "es", ["hola"], ocr_cache_id=ocr_entry.id
        )
        ocr_id, translation_id = ocr_entry.id, translation_entry.id

        cutoff = datetime.utcnow() - timedelta(days=200)
        db.query(OcrCache).filter(OcrCache.id == ocr_id).update(
            {"last_accessed_at": cutoff}
        )
        db.query(TranslationCache).filter(TranslationCache.id == translation_id).update(
            {"last_accessed_at": cutoff}
        )
        db.commit()

        removed = cache_service.evict_stale(db, older_than_days=90)
        assert removed == 2
        assert db.get(OcrCache, ocr_id) is None
        assert db.get(TranslationCache, translation_id) is None
