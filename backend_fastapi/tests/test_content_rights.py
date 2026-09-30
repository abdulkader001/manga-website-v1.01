"""Tests for content rights (SRS Part 1J).

Covers:
  * may_host and may_translate as SEPARATE permissions.
  * Effective rights AND the website default with the series value.
  * A series marked not translatable cannot be translated by any path/role.
  * Takedown denies both hosting and translation.
  * Ingestion gate rejects hosting from a not-licensed website.
  * The translation endpoint enforces the gate.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.api_errors import ApiError, ErrorCode
from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    ApprovedSourceDomain,
    Chapter,
    Manga,
    User,
    UserRole,
)
from backend_fastapi.app.services.content_rights import (
    MSG_HOST_FORBIDDEN,
    MSG_TAKEN_DOWN,
    MSG_TRANSLATE_FORBIDDEN,
    assert_may_host_url,
    assert_series_translatable,
    resolve_series_rights,
)
from backend_fastapi.app.services.manga_service import schedule_series_scrape
from _support.db_reset import clear_content


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _reset(session):
    clear_content(session, commit=False)
    session.query(ApprovedSourceDomain).delete()
    session.commit()


def _domain(session, domain, **kw):
    entry = ApprovedSourceDomain(base_url=f"https://{domain}", domain=domain, **kw)
    session.add(entry)
    session.commit()
    return entry


def _manga(session, source_url, **kw):
    m = Manga(title=f"T-{uuid.uuid4().hex}", source_url=source_url, **kw)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def test_rights_default_open():
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "open.example")
        m = _manga(session, "https://open.example/manga/a")
        rights = resolve_series_rights(session, m)
        assert rights["may_host"] is True
        assert rights["may_translate"] is True
    finally:
        session.close()


def test_may_host_and_may_translate_are_separate():
    """NoDerivatives: hosting allowed, translation forbidden."""
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "nd.example")
        m = _manga(
            session,
            "https://nd.example/manga/a",
            may_host=True,
            may_translate=False,
        )
        rights = resolve_series_rights(session, m)
        assert rights["may_host"] is True
        assert rights["may_translate"] is False
    finally:
        session.close()


def test_website_default_ands_with_series():
    """A website that forbids translation overrides a permissive series flag."""
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "site.example", may_translate=False)
        m = _manga(session, "https://site.example/manga/a", may_translate=True)
        rights = resolve_series_rights(session, m)
        assert rights["may_translate"] is False
    finally:
        session.close()


def test_assert_series_translatable_blocks():
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "block.example")
        m = _manga(session, "https://block.example/manga/a", may_translate=False)
        with pytest.raises(ApiError) as exc:
            assert_series_translatable(session, m)
        assert exc.value.code == ErrorCode.CONTENT_TRANSLATE_FORBIDDEN
        assert exc.value.message == MSG_TRANSLATE_FORBIDDEN
    finally:
        session.close()


def test_takedown_blocks_host_and_translate():
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "td.example")
        m = _manga(
            session,
            "https://td.example/manga/a",
            takedown_status="taken_down",
        )
        rights = resolve_series_rights(session, m)
        assert rights["may_host"] is False
        assert rights["may_translate"] is False
        with pytest.raises(ApiError) as exc:
            assert_series_translatable(session, m)
        assert exc.value.code == ErrorCode.CONTENT_TAKEN_DOWN
        assert exc.value.message == MSG_TAKEN_DOWN
    finally:
        session.close()


def test_ingestion_gate_rejects_unhostable_website():
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "nohost.example", may_host=False)
        with pytest.raises(ApiError) as exc:
            assert_may_host_url(session, "https://nohost.example/manga/a")
    finally:
        session.close()
    assert exc.value.code == ErrorCode.CONTENT_HOST_FORBIDDEN
    assert exc.value.message == MSG_HOST_FORBIDDEN


def test_schedule_scrape_blocked_when_host_forbidden():
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "nohost2.example", may_host=False)
        with pytest.raises(ApiError) as exc:
            schedule_series_scrape(session, "https://nohost2.example/manga/a")
    finally:
        session.close()
    assert exc.value.code == ErrorCode.CONTENT_HOST_FORBIDDEN
    assert exc.value.message == MSG_HOST_FORBIDDEN


# --------------------------- endpoint-level --------------------------------


def _main_admin(session):
    admin = User(
        email=f"admin-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Admin",
        role=UserRole.ADMIN,
        is_main_admin=True,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin


def test_translation_endpoint_blocks_untranslatable_series(
    fastapi_client, auth_headers
):
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "trx.example")
        m = _manga(session, "https://trx.example/manga/a", may_translate=False)
        manga_id = m.id
    finally:
        session.close()

    resp = fastapi_client.post(
        "/api/translation/text",
        json={"text": "こんにちは", "target": "en", "manga_id": manga_id},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CONTENT_TRANSLATE_FORBIDDEN"
    assert body["error"]["message"] == MSG_TRANSLATE_FORBIDDEN


def test_translation_jobs_path_blocks_untranslatable_series(
    fastapi_client, auth_headers
):
    """The async submit-and-poll path enforces the gate too (SRS 1J: no path)."""
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "jobtrx.example")
        m = _manga(session, "https://jobtrx.example/manga/a", may_translate=False)
        manga_id = m.id
    finally:
        session.close()

    resp = fastapi_client.post(
        "/api/translation/jobs",
        json={"text": "こんにちは", "target": "en", "manga_id": manga_id},
        headers=auth_headers,
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CONTENT_TRANSLATE_FORBIDDEN"
    assert body["error"]["message"] == MSG_TRANSLATE_FORBIDDEN


def test_chapter_detail_exposes_may_translate(fastapi_client):
    """The chapter content endpoint carries the series' effective right."""
    session = SessionLocal()
    try:
        _reset(session)
        clear_content(session, commit=False)
        session.commit()
        _domain(session, "chp.example")
        m = _manga(session, "https://chp.example/manga/a", may_translate=False)
        ch = Chapter(
            manga_id=m.id,
            chapter_number=1,
            chapter_url=f"https://chp.example/manga/a/c/{uuid.uuid4().hex}",
            pages=["https://chp.example/p1.jpg"],
        )
        session.add(ch)
        session.commit()
        manga_id, chapter_id = m.id, ch.id
    finally:
        session.close()

    resp = fastapi_client.get(f"/api/manga/{manga_id}/chapters/{chapter_id}")
    assert resp.status_code == 200
    assert resp.json()["may_translate"] is False


def test_admin_takedown_then_rights_reflect(fastapi_client):
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "adm.example")
        m = _manga(session, "https://adm.example/manga/a")
        manga_id = m.id
        admin_id = _main_admin(session).id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    # Set may_translate False via rights endpoint.
    put = fastapi_client.put(
        f"/api/admin/series/{manga_id}/rights",
        headers=headers,
        json={"may_translate": False},
    )
    assert put.status_code == 200
    assert put.json()["may_translate"] is False
    assert put.json()["may_host"] is True

    # Takedown denies everything.
    td = fastapi_client.post(
        f"/api/admin/series/{manga_id}/takedown",
        headers=headers,
        json={"status": "taken_down", "reason": "DMCA"},
    )
    assert td.status_code == 200
    body = td.json()
    assert body["may_host"] is False
    assert body["may_translate"] is False
    assert body["takedown_status"] == "taken_down"


def test_taken_down_series_read_paths_refuse_ordinary_readers(fastapi_client):
    """F-18: a taken-down series must not remain readable.

    Prior to the fix, get_manga_detail/get_chapter_list/get_chapter_content
    never consulted resolve_series_rights at all, so a series marked
    taken_down stayed fully browsable by anyone.
    """
    session = SessionLocal()
    try:
        _reset(session)
        clear_content(session, commit=False)
        session.commit()
        _domain(session, "takedown-read.example")
        m = _manga(session, "https://takedown-read.example/manga/a")
        ch = Chapter(
            manga_id=m.id,
            chapter_number=1,
            chapter_url=f"https://takedown-read.example/manga/a/c/{uuid.uuid4().hex}",
            pages=["https://takedown-read.example/p1.jpg"],
        )
        session.add(ch)
        session.commit()
        manga_id, chapter_id = m.id, ch.id
        admin_id = _main_admin(session).id
    finally:
        session.close()

    admin_headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    # Readable before takedown.
    assert fastapi_client.get(f"/api/manga/{manga_id}").status_code == 200
    assert (
        fastapi_client.get(f"/api/manga/{manga_id}/chapters").status_code == 200
    )
    assert (
        fastapi_client.get(
            f"/api/manga/{manga_id}/chapters/{chapter_id}"
        ).status_code
        == 200
    )

    takedown = fastapi_client.post(
        f"/api/admin/series/{manga_id}/takedown",
        headers=admin_headers,
        json={"status": "taken_down", "reason": "DMCA"},
    )
    assert takedown.status_code == 200

    # Ordinary (anonymous) readers are refused on every read path.
    detail = fastapi_client.get(f"/api/manga/{manga_id}")
    assert detail.status_code == 451
    assert detail.json()["error"]["code"] == "CONTENT_TAKEN_DOWN"

    chapters = fastapi_client.get(f"/api/manga/{manga_id}/chapters")
    assert chapters.status_code == 451

    content = fastapi_client.get(f"/api/manga/{manga_id}/chapters/{chapter_id}")
    assert content.status_code == 451

    # A main admin can still see it.
    admin_detail = fastapi_client.get(
        f"/api/manga/{manga_id}", headers=admin_headers
    )
    assert admin_detail.status_code == 200

    admin_chapters = fastapi_client.get(
        f"/api/manga/{manga_id}/chapters", headers=admin_headers
    )
    assert admin_chapters.status_code == 200

    admin_content = fastapi_client.get(
        f"/api/manga/{manga_id}/chapters/{chapter_id}", headers=admin_headers
    )
    assert admin_content.status_code == 200


def test_taken_down_series_rescrape_is_refused_even_for_admins(fastapi_client):
    """F-18: rescrape must not refresh a taken-down series' pages from
    source -- absolute, no admin bypass (mirrors
    assert_series_translatable's own "every path and role" rule)."""
    session = SessionLocal()
    try:
        _reset(session)
        _domain(session, "takedown-rescrape.example")
        m = _manga(session, "https://takedown-rescrape.example/manga/a")
        m.takedown_status = "taken_down"
        session.commit()
        manga_id, manga_title = m.id, m.title
        admin_id = _main_admin(session).id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    resp = fastapi_client.post(
        f"/api/admin/series/{manga_id}/rescrape",
        headers=headers,
        json={"confirm_title": manga_title},
    )
    assert resp.status_code == 451
    assert resp.json()["error"]["code"] == "CONTENT_TAKEN_DOWN"
