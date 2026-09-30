"""Cache administration: Mechanism A/B + admin controls (SRS 2C.4)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import (
    Chapter,
    Manga,
    OcrCache,
    TranslationCache,
    User,
    UserRole,
)
from backend_fastapi.app.services import cache_admin_service as cache_admin


def _login(client, email: str) -> str:
    request = client.post("/api/auth/request-magic-link", json={"email": email})
    assert request.status_code == 200, request.text
    token_value = request.json()["debug_token"]
    consume = client.get(f"/api/auth/magic-link/{token_value}")
    assert consume.status_code == 200, consume.text
    return consume.json()["access_token"]


def _create_main_admin() -> str:
    email = f"cacheadmin-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        user = User(
            email=email,
            is_active=True,
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
    return email


def _make_manga_with_chapter(db) -> tuple[int, int]:
    manga = Manga(
        title=f"Cache Test Series {uuid.uuid4().hex[:8]}",
        source_url=f"https://example.com/manga/{uuid.uuid4().hex}",
    )
    db.add(manga)
    db.commit()
    db.refresh(manga)
    chapter = Chapter(
        manga_id=manga.id,
        chapter_number=1,
        chapter_url=f"https://example.com/chapter/{uuid.uuid4().hex}",
        pages=["p1.jpg"],
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    # SQLite reuses rowids after a bulk delete elsewhere in the suite;
    # defensively clear any orphaned cache rows for this (possibly
    # recycled) chapter id before the test seeds its own.
    db.query(TranslationCache).filter(
        TranslationCache.chapter_id == chapter.id
    ).delete()
    db.query(OcrCache).filter(OcrCache.chapter_id == chapter.id).delete()
    db.commit()
    return manga.id, chapter.id


# --------------------------------------------------------------------------
# Mechanism A: cache_priority
# --------------------------------------------------------------------------


def test_cache_priority_on_always_checks_cache() -> None:
    assert cache_admin.should_check_cache("on") is True


def test_cache_priority_off_never_checks_unless_reader_asks() -> None:
    assert cache_admin.should_check_cache("off") is False
    assert cache_admin.should_check_cache("off", reader_requested_cached=True) is True


def test_cache_priority_reduced_is_probabilistic() -> None:
    with patch(
        "backend_fastapi.app.services.cache_admin_service.random.random",
        return_value=0.1,
    ):
        assert cache_admin.should_check_cache("reduced") is True
    with patch(
        "backend_fastapi.app.services.cache_admin_service.random.random",
        return_value=0.9,
    ):
        assert cache_admin.should_check_cache("reduced") is False


def test_invalid_cache_priority_rejected(db_session) -> None:
    try:
        cache_admin.set_cache_priority(db_session, "sometimes")
        assert False, "expected CacheAdminError"
    except cache_admin.CacheAdminError:
        pass


# --------------------------------------------------------------------------
# Admin API: priority, clear, refresh, statistics
# --------------------------------------------------------------------------


def test_admin_can_change_cache_priority(fastapi_client) -> None:
    email = _create_main_admin()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.patch(
        "/api/admin/cache/priority", json={"cache_priority": "reduced"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["cache_priority"] == "reduced"

    # Reset for other tests that assume the default.
    fastapi_client.patch(
        "/api/admin/cache/priority", json={"cache_priority": "on"}, headers=headers
    )


def test_clear_cache_requires_typed_confirmation(fastapi_client, db_session) -> None:
    email = _create_main_admin()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    manga_id, chapter_id = _make_manga_with_chapter(db_session)
    db_session.add(
        TranslationCache(
            chapter_id=chapter_id,
            page_index=0,
            target_lang="en",
            translated_boxes=["hi"],
        )
    )
    db_session.commit()

    wrong = fastapi_client.post(
        "/api/admin/cache/clear",
        json={"scope": "series", "manga_id": manga_id, "confirm": "not the title"},
        headers=headers,
    )
    assert wrong.status_code == 422

    manga = db_session.get(Manga, manga_id)
    correct = fastapi_client.post(
        "/api/admin/cache/clear",
        json={"scope": "series", "manga_id": manga_id, "confirm": manga.title},
        headers=headers,
    )
    assert correct.status_code == 200
    body = correct.json()
    assert body["translation_rows"] == 1
    assert body["chapters_affected"] == 1

    remaining = (
        db_session.query(TranslationCache)
        .filter(TranslationCache.chapter_id == chapter_id)
        .count()
    )
    assert remaining == 0


def test_clear_cache_aborts_safely_for_unknown_series(fastapi_client) -> None:
    email = _create_main_admin()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.post(
        "/api/admin/cache/clear",
        json={"scope": "series", "manga_id": 999999999, "confirm": "whatever"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_refresh_cache_downgrades_quality_tier_without_deleting(
    fastapi_client, db_session
) -> None:
    email = _create_main_admin()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    manga_id, chapter_id = _make_manga_with_chapter(db_session)
    db_session.add(
        TranslationCache(
            chapter_id=chapter_id,
            page_index=0,
            target_lang="en",
            translated_boxes=["hi"],
            quality_tier="paid",
        )
    )
    db_session.commit()

    manga = db_session.get(Manga, manga_id)
    resp = fastapi_client.post(
        "/api/admin/cache/refresh",
        json={"scope": "series", "manga_id": manga_id, "confirm": manga.title},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["translation_rows"] == 1

    entry = (
        db_session.query(TranslationCache)
        .filter(TranslationCache.chapter_id == chapter_id)
        .one()
    )
    assert entry.quality_tier == "free"


def test_clear_all_requires_the_literal_phrase(fastapi_client) -> None:
    email = _create_main_admin()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    wrong = fastapi_client.post(
        "/api/admin/cache/clear",
        json={"scope": "all", "confirm": "yes please"},
        headers=headers,
    )
    assert wrong.status_code == 422


def test_cache_statistics_endpoint(fastapi_client) -> None:
    email = _create_main_admin()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.get("/api/admin/cache", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "cache_priority" in body
    assert "translation_cache_entries" in body


def test_secondary_admin_cannot_manage_cache(fastapi_client) -> None:
    email = f"cachesecondary-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        user = User(
            email=email,
            is_active=True,
            role=UserRole.SECONDARY,
            is_secondary_admin=True,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
    token = _login(fastapi_client, email)
    headers = {"Authorization": f"Bearer {token}"}

    assert fastapi_client.get("/api/admin/cache", headers=headers).status_code == 403
    assert (
        fastapi_client.post(
            "/api/admin/cache/clear",
            json={"scope": "all", "confirm": "CLEAR CACHE"},
            headers=headers,
        ).status_code
        == 403
    )
