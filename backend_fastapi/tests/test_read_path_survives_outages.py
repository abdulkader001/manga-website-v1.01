"""The read path survives every optional service being down (SRS 1C.7 /
1H.10.2 / 1H.10.8): "With Community, Ranking, OCR, Translation, AI,
Notification, and Scraper services stopped, a reader can browse and read."

This simulates "stopped" by making each optional service's entry point raise
on any call, then proving catalogue browsing and chapter reading still
succeed end-to-end through the real HTTP stack (not just at the unit level).
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import Chapter, Manga


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _service_down(*_args, **_kwargs):
    raise RuntimeError("service stopped")


@pytest.fixture
def _sample_series():
    session = SessionLocal()
    try:
        manga = Manga(
            title=f"Outage Test {uuid.uuid4().hex[:6]}",
            source_url=f"https://outage-{uuid.uuid4().hex[:6]}.example/manga/x",
            type="manga",
            status="ongoing",
        )
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://outage.example/{uuid.uuid4().hex[:8]}",
            pages=["https://outage.example/p1.jpg", "https://outage.example/p2.jpg"],
            ingestion_status="complete",
        )
        session.add(chapter)
        session.commit()
        return manga.id, chapter.id
    finally:
        session.close()


def test_browse_and_read_survive_all_optional_services_down(
    fastapi_client, _sample_series
):
    manga_id, chapter_id = _sample_series

    # "Stopped": every optional-service entry point raises unconditionally.
    patches = [
        mock.patch(
            "backend_fastapi.app.services.ocr_service.OCRService.recognize",
            side_effect=_service_down,
            create=True,
        ),
        mock.patch(
            "backend_fastapi.app.services.translation_service.TranslationService.translate",
            side_effect=_service_down,
            create=True,
        ),
        mock.patch(
            "backend_fastapi.app.services.notification_service.notify_async",
            side_effect=_service_down,
        ),
        mock.patch(
            "backend_fastapi.app.tasks.scraper_tasks.process_manga_scrape.delay",
            side_effect=_service_down,
        ),
        mock.patch(
            "backend_fastapi.app.tasks.scraper_tasks.process_chapter_scrape.delay",
            side_effect=_service_down,
        ),
    ]
    with patches[0], patches[1], patches[2], patches[3], patches[4]:
        # Catalogue browsing.
        listing = fastapi_client.get("/api/manga/")
        assert listing.status_code == 200
        assert isinstance(listing.json().get("items"), list)

        detail = fastapi_client.get(f"/api/manga/{manga_id}")
        assert detail.status_code == 200

        chapters = fastapi_client.get(f"/api/manga/{manga_id}/chapters")
        assert chapters.status_code == 200

        # Reading a chapter's actual pages.
        content = fastapi_client.get(f"/api/manga/{manga_id}/chapters/{chapter_id}")
        assert content.status_code == 200
        body = content.json()
        assert body["pages"] == [
            "https://outage.example/p1.jpg",
            "https://outage.example/p2.jpg",
        ]
