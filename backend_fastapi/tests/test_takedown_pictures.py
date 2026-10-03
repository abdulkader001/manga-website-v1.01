"""plan.md P1-2: a takedown removes the series' pictures.

Takedown only set a status. The API answered 451, but the stored page and
cover files stayed on disk, and nginx serves them straight from there, so
every picture stayed reachable. The backend routes for those files did not
check the takedown either.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Chapter, Manga, OcrCache
from backend_fastapi.app.services import cover_service, page_image_service

from _support import staff

WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "


@pytest.fixture
def mirrored_series(fastapi_app, tmp_path, monkeypatch):
    monkeypatch.setenv("PAGE_STORAGE_DIR", str(tmp_path / "pages"))
    monkeypatch.setenv("COVER_UPLOAD_DIR", str(tmp_path / "covers"))
    tag = uuid.uuid4().hex
    cover_name = uuid.uuid4().hex[:40].ljust(40, "a") + ".webp"
    (cover_service.covers_dir() / cover_name).write_bytes(WEBP)
    with SessionLocal() as session:
        manga = Manga(
            title=f"Takedown {tag}",
            source_url=f"https://td.invalid/{tag}",
            cover_image=cover_service.public_url(cover_name),
            type="manga",
        )
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://td.invalid/{tag}/1",
            source_pages=[f"https://td.invalid/{tag}/1.jpg"],
        )
        session.add(chapter)
        session.flush()
        page_name = "0001-abcdef0123.webp"
        folder = page_image_service.pages_dir() / str(manga.id) / str(chapter.id)
        folder.mkdir(parents=True)
        (folder / page_name).write_bytes(WEBP)
        chapter.pages = [page_image_service.public_url(manga.id, chapter.id, page_name)]
        session.add(OcrCache(chapter_id=chapter.id, page_index=0, text_boxes=["hi"]))
        session.commit()
        return {
            "manga": manga.id,
            "chapter": chapter.id,
            "page": f"/api/v1/manga/pages/{manga.id}/{chapter.id}/{page_name}",
            "page_file": folder / page_name,
            "cover": f"/api/v1/manga/covers/{cover_name}",
            "cover_file": cover_service.covers_dir() / cover_name,
        }


def _takedown(client, manga_id, status="taken_down"):
    owner = staff.owner()
    return client.post(
        f"/api/v1/admin/series/{manga_id}/takedown",
        headers=staff.headers(owner),
        json={"status": status, "reason": "DMCA notice"},
    )


def test_pictures_are_served_before_takedown(fastapi_client, mirrored_series):
    assert fastapi_client.get(mirrored_series["page"]).status_code == 200
    assert fastapi_client.get(mirrored_series["cover"]).status_code == 200


def test_takedown_deletes_the_pictures(fastapi_client, mirrored_series):
    ids = mirrored_series
    response = _takedown(fastapi_client, ids["manga"])
    assert response.status_code == 200, response.text

    assert not ids["page_file"].exists()
    assert not ids["cover_file"].exists()
    assert fastapi_client.get(ids["page"]).status_code == 404
    assert fastapi_client.get(ids["cover"]).status_code == 404
    with SessionLocal() as session:
        chapter = session.get(Chapter, ids["chapter"])
        manga = session.get(Manga, ids["manga"])
        # Back to the source pages, so a restore can mirror them again.
        assert chapter.pages == chapter.source_pages
        assert manga.cover_image is None
        assert session.query(OcrCache).filter(OcrCache.chapter_id == ids["chapter"]).count() == 0


def test_takedown_is_audited(fastapi_client, mirrored_series):
    from backend_fastapi.app.models import AdminAuditLog

    _takedown(fastapi_client, mirrored_series["manga"])
    with SessionLocal() as session:
        rows = session.query(AdminAuditLog).filter(AdminAuditLog.action == "SET_TAKEDOWN").all()
        assert any(str(mirrored_series["manga"]) in str(row.metadata_json) for row in rows)


def test_requested_keeps_the_pictures(fastapi_client, mirrored_series):
    response = _takedown(fastapi_client, mirrored_series["manga"], status="requested")
    assert response.status_code == 200
    assert mirrored_series["page_file"].exists()
    assert mirrored_series["cover_file"].exists()


def test_backend_refuses_pictures_of_a_series_taken_down_elsewhere(fastapi_client, mirrored_series):
    """A file left behind (or one nginx is not serving) is still refused."""

    with SessionLocal() as session:
        session.get(Manga, mirrored_series["manga"]).takedown_status = "taken_down"
        session.commit()
    assert fastapi_client.get(mirrored_series["page"]).status_code == 404
    assert fastapi_client.get(mirrored_series["cover"]).status_code == 404
    owner = staff.owner()
    assert fastapi_client.get(mirrored_series["page"], headers=staff.headers(owner)).status_code == 200


def test_mirroring_skips_a_taken_down_series(fastapi_app, mirrored_series, monkeypatch):
    from backend_fastapi.app.services import page_mirror_service

    monkeypatch.setattr(page_image_service, "mirroring_enabled", lambda: True)
    with SessionLocal() as session:
        session.get(Manga, mirrored_series["manga"]).takedown_status = "taken_down"
        session.commit()
        result = page_mirror_service.mirror_chapter_by_id(session, mirrored_series["chapter"])
    assert result == {"status": "skipped", "reason": "taken_down"}
