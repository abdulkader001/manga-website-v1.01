"""Integration test for the chapter/page processing endpoint (SRS 2F.1)."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import (
    Chapter,
    Manga,
    OcrCache,
    SystemProviderInstance,
    TranslationCache,
    User,
)
from backend_fastapi.app.services import provider_management_service as pms


@pytest.fixture
def allow_remote_host(monkeypatch):
    from backend_fastapi.app.services import url_guard

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)


class DummyNormalizedOCR:
    def extract_normalized(
        self, image_bytes, *, provider_config=None, language_hint=None, **_
    ):
        return {
            "regions": [
                {
                    "index": 0,
                    "text": "こんにちは",
                    "coordinates": {
                        "x": 10.0,
                        "y": 10.0,
                        "width": 40.0,
                        "height": 20.0,
                    },
                    "confidence": 92.0,
                    "region_type": "speech_bubble",
                    "reading_order": 0,
                }
            ],
            "detected_language": "ja",
            "detected_script": "cjk",
            "reading_order_mode": "rtl_vertical",
            "engine_tier": 2,
        }


class DummyTranslator:
    def translate(self, text, source_lang, target_lang, provider_config=None, **_):
        lines = []
        for line in text.splitlines():
            n, _, rest = line.partition("] ")
            lines.append(f"{n}] EN:{rest}")
        return "\n".join(lines)


def _make_chapter(db) -> Chapter:
    manga = Manga(
        title=f"Processing Endpoint Test {uuid.uuid4().hex[:8]}",
        source_url=f"https://example.com/manga/{uuid.uuid4().hex}",
    )
    db.add(manga)
    db.commit()
    db.refresh(manga)
    chapter = Chapter(
        manga_id=manga.id,
        chapter_number=1,
        chapter_url=f"https://example.com/chapter/{uuid.uuid4().hex}",
        pages=["https://example.com/pages/0.jpg"],
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    # SQLite reuses rowids after a bulk delete (other tests wipe
    # Chapter/Manga wholesale); defensively clear any orphaned cache rows
    # that might otherwise collide with this fresh chapter's (recycled) id.
    db.query(TranslationCache).filter(
        TranslationCache.chapter_id == chapter.id
    ).delete()
    db.query(OcrCache).filter(OcrCache.chapter_id == chapter.id).delete()
    db.commit()
    return chapter


def _login(client, email: str) -> str:
    request = client.post("/api/auth/request-magic-link", json={"email": email})
    assert request.status_code == 200, request.text
    token_value = request.json()["debug_token"]
    consume = client.get(f"/api/auth/magic-link/{token_value}")
    assert consume.status_code == 200, consume.text
    return consume.json()["access_token"]


def test_processing_endpoint_full_flow(
    fastapi_client, monkeypatch, allow_remote_host
) -> None:
    from backend_fastapi.app.api.routers import ocr as ocr_router
    from backend_fastapi.app.api.routers import processing as processing_router

    monkeypatch.setattr(ocr_router, "ocr_service", DummyNormalizedOCR())
    monkeypatch.setattr(
        processing_router, "_fetch_image_bytes_sync", lambda url: b"fake-bytes"
    )
    monkeypatch.setattr(
        processing_router, "TranslationService", lambda *a, **kw: DummyTranslator()
    )

    with SessionLocal() as session:
        chapter = _make_chapter(session)
        chapter_id = chapter.id

    email = f"processing-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        session.add(User(email=email, is_active=True, provider="magic_link"))
        session.commit()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    response = fastapi_client.get(
        f"/api/processing/chapter/{chapter_id}/page/0",
        params={"target": "en"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cached"] is False
    assert body["regions"][0]["text"] == "EN:こんにちは"
    assert body["detected_language"] == "ja"

    # Second call for the same page must hit the shared cache.
    second = fastapi_client.get(
        f"/api/processing/chapter/{chapter_id}/page/0",
        params={"target": "en"},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["cached"] is True

    with SessionLocal() as session:
        assert (
            session.query(TranslationCache)
            .filter(TranslationCache.chapter_id == chapter_id)
            .count()
            == 1
        )


def test_processing_endpoint_requires_login(fastapi_client) -> None:
    with SessionLocal() as session:
        chapter = _make_chapter(session)
        chapter_id = chapter.id

    response = fastapi_client.get(
        f"/api/processing/chapter/{chapter_id}/page/0", params={"target": "en"}
    )
    assert response.status_code in (401, 403)


def test_platform_default_provider_success_and_failure_are_recorded(
    fastapi_client, monkeypatch, allow_remote_host
) -> None:
    """2D.3/2D.4: the multi-provider priority system's failure tracking must
    actually be fed by real traffic, not just be theoretically callable."""

    from backend_fastapi.app.api.routers import ocr as ocr_router
    from backend_fastapi.app.api.routers import processing as processing_router

    with SessionLocal() as session:
        session.query(SystemProviderInstance).filter(
            SystemProviderInstance.service == "ocr"
        ).delete()
        session.commit()
        provider = pms.create_provider(
            session,
            provider_name="Test OCR",
            service="ocr",
            provider_id="custom",
            api_url="https://example.com/ocr",
        )
        pms.verify_provider(session, provider.id, live_test=lambda r, d: (True, None))
        provider_id = provider.id

    monkeypatch.setattr(
        processing_router, "_fetch_image_bytes_sync", lambda url: b"fake-bytes"
    )
    monkeypatch.setattr(
        processing_router, "TranslationService", lambda *a, **kw: DummyTranslator()
    )

    with SessionLocal() as session:
        chapter = _make_chapter(session)
        chapter_id = chapter.id

    email = f"processing-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        session.add(User(email=email, is_active=True, provider="magic_link"))
        session.commit()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    # Success path.
    monkeypatch.setattr(ocr_router, "ocr_service", DummyNormalizedOCR())
    ok = fastapi_client.get(
        f"/api/processing/chapter/{chapter_id}/page/0",
        params={"target": "en"},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text

    with SessionLocal() as session:
        row = session.get(SystemProviderInstance, provider_id)
        assert row.usage_stats["requests"] >= 1
        assert row.error_stats["consecutive_failures"] == 0

    # Failure path, on a different (uncached) page.
    class FailingOCR:
        def extract_normalized(self, *a, **kw):
            raise RuntimeError("provider unreachable")

    monkeypatch.setattr(ocr_router, "ocr_service", FailingOCR())
    with SessionLocal() as session:
        chapter = session.get(Chapter, chapter_id)
        chapter.pages = list(chapter.pages) + ["https://example.com/pages/1.jpg"]
        session.commit()

    # The test client re-raises unhandled server exceptions by default;
    # what matters here is that record_failure ran before it propagated.
    with pytest.raises(RuntimeError, match="provider unreachable"):
        fastapi_client.get(
            f"/api/processing/chapter/{chapter_id}/page/1",
            params={"target": "en"},
            headers=headers,
        )

    with SessionLocal() as session:
        row = session.get(SystemProviderInstance, provider_id)
        assert row.error_stats["consecutive_failures"] == 1
        assert row.error_stats["last_error"] == "provider unreachable"


def test_processing_endpoint_404_for_missing_page(fastapi_client) -> None:
    with SessionLocal() as session:
        chapter = _make_chapter(session)
        chapter_id = chapter.id

    email = f"processing-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        session.add(User(email=email, is_active=True, provider="magic_link"))
        session.commit()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    response = fastapi_client.get(
        f"/api/processing/chapter/{chapter_id}/page/99",
        params={"target": "en"},
        headers=headers,
    )
    assert response.status_code == 404


def test_page_work_runs_off_the_event_loop(fastapi_client, monkeypatch, allow_remote_host) -> None:
    """F-93: OCR + translation must never run on the event loop, or one
    reader's page freezes the API worker for everybody else."""

    import asyncio

    from backend_fastapi.app.api.routers import ocr as ocr_router
    from backend_fastapi.app.api.routers import processing as processing_router

    monkeypatch.setattr(ocr_router, "ocr_service", DummyNormalizedOCR())
    monkeypatch.setattr(processing_router, "_fetch_image_bytes_sync", lambda url: b"fake-bytes")
    monkeypatch.setattr(processing_router, "TranslationService", lambda *a, **kw: DummyTranslator())

    seen = {}
    original = processing_router.cps.process_page

    def spy(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            seen["on_event_loop"] = True
        except RuntimeError:
            seen["on_event_loop"] = False
        return original(*args, **kwargs)

    monkeypatch.setattr(processing_router.cps, "process_page", spy)

    with SessionLocal() as session:
        chapter_id = _make_chapter(session).id
    email = f"processing-loop-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        session.add(User(email=email, is_active=True, provider="magic_link"))
        session.commit()
    headers = {"Authorization": f"Bearer {_login(fastapi_client, email)}"}

    response = fastapi_client.get(
        f"/api/processing/chapter/{chapter_id}/page/0", params={"target": "en"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert seen == {"on_event_loop": False}
