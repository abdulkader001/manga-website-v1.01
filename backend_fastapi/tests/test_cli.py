from __future__ import annotations

from backend_fastapi.app import cli as backend_cli
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import Chapter, Manga
from _support.db_reset import clear_content


def test_cli_rescrape_helpers(monkeypatch):
    session = SessionLocal()
    try:
        clear_content(session, commit=False)
        session.commit()

        manga = Manga(
            title="CLI Manga",
            slug="cli-manga",
            source_url="https://example.com/cli",
        )
        session.add(manga)
        session.commit()
        session.refresh(manga)

        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_title="One",
            chapter_url="https://example.com/cli/1",
        )
        session.add(chapter)
        session.commit()
        session.refresh(chapter)
    finally:
        session.close()

    called = {}

    def fake_series(manga_obj, db_session=None):
        called["series"] = manga_obj.id

    def fake_chapter(chapter_obj, db_session=None):
        called.setdefault("chapters", []).append(chapter_obj.id)

    def fake_delete(chapter_obj, db_session=None):
        called.setdefault("deleted", []).append(chapter_obj.id)

    monkeypatch.setattr(backend_cli, "rescrape_series_service", fake_series)
    monkeypatch.setattr(backend_cli, "rescrape_chapter_service", fake_chapter)
    monkeypatch.setattr(backend_cli, "delete_chapter_pages_only", fake_delete)

    backend_cli.rescrape_series(manga.id)
    backend_cli.rescrape_chapter(chapter.id, delete_previous=True)

    assert called["series"] == manga.id
    assert chapter.id in called["chapters"]
    assert chapter.id in called["deleted"]
