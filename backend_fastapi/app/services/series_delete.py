"""Delete a series and everything that belongs to it (plan.md P0-3).

The admin route, the bulk-delete task and "delete all manga" each deleted
chapters with one bulk query and then the series. A bulk query skips the
ORM's cascades, and on PostgreSQL the reading history, chapter bookmarks and
OCR/translation caches still pointed at those chapters, so the database
refused and the admin got HTTP 500.

Migration ``20261018_cascade_series_children`` makes the database remove
those rows itself. This module removes them explicitly as well, so a database
that missed the migration, and SQLite (which does not enforce foreign keys
unless asked), behave the same.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Bookmark, Chapter, Manga, OcrCache, ReadHistory, TranslationCache


def delete_series(db: Session, manga: Manga) -> int:
    """Delete ``manga``, its chapters and their rows. Returns the chapter count.

    The caller commits, and deletes the picture files after the commit.
    """

    chapter_ids = select(Chapter.id).where(Chapter.manga_id == manga.id).scalar_subquery()

    # Translations point at OCR rows, so they go first.
    db.query(TranslationCache).filter(TranslationCache.chapter_id.in_(chapter_ids)).delete(
        synchronize_session=False
    )
    db.query(OcrCache).filter(OcrCache.chapter_id.in_(chapter_ids)).delete(
        synchronize_session=False
    )
    for model in (ReadHistory, Bookmark):
        db.query(model).filter(
            or_(model.manga_id == manga.id, model.chapter_id.in_(chapter_ids))
        ).delete(synchronize_session=False)

    deleted_chapters = (
        db.query(Chapter).filter(Chapter.manga_id == manga.id).delete(synchronize_session=False)
    )
    # The series itself goes through the ORM so its own cascades (scraping
    # jobs, ratings and the rest) still run; drop what the session cached of
    # the rows deleted above first.
    db.expire(manga)
    db.delete(manga)
    return int(deleted_chapters or 0)


__all__ = ["delete_series"]
