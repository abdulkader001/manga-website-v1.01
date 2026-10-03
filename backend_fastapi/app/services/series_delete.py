"""Deleting a series and everything that belongs to it.

One path for the single delete, bulk delete and "delete all manga". Rows that
point at the series or its chapters are removed explicitly, children first,
so a delete works on a database that missed the
``20261018_cascade_series_children`` migration too (before it, any series a
signed-in reader had opened, or with a translated page, failed with HTTP 500
on PostgreSQL). Scraping-job history is kept, unlinked from the series.
"""

from __future__ import annotations

from typing import Iterable, Optional

import structlog
from sqlalchemy.orm import Session

logger = structlog.get_logger(__name__)


def _delete_rows(db: Session, manga_id: int) -> int:
    from ..models import Bookmark, Chapter, Manga, OcrCache, ReadHistory, ScrapingJob, TranslationCache

    chapter_ids = db.query(Chapter.id).filter(Chapter.manga_id == manga_id).scalar_subquery()

    db.query(TranslationCache).filter(TranslationCache.chapter_id.in_(chapter_ids)).delete(
        synchronize_session=False
    )
    db.query(OcrCache).filter(OcrCache.chapter_id.in_(chapter_ids)).delete(synchronize_session=False)
    for model in (ReadHistory, Bookmark):
        db.query(model).filter(
            (model.manga_id == manga_id) | (model.chapter_id.in_(chapter_ids))
        ).delete(synchronize_session=False)
    db.query(ScrapingJob).filter(ScrapingJob.manga_id == manga_id).update(
        {ScrapingJob.manga_id: None}, synchronize_session=False
    )
    deleted = db.query(Chapter).filter(Chapter.manga_id == manga_id).delete(synchronize_session=False)
    db.query(Manga).filter(Manga.id == manga_id).delete(synchronize_session=False)
    return int(deleted or 0)


def delete_series(db: Session, manga_id: int) -> Optional[int]:
    """Delete one series, its chapters and its stored pictures.

    Returns the number of chapters deleted, or ``None`` when the series does
    not exist. Commits.
    """

    from ..models import Manga

    if db.get(Manga, manga_id) is None:
        return None
    try:
        deleted = _delete_rows(db, manga_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.expire_all()
    from . import page_image_service

    page_image_service.delete_series_files(manga_id)
    return deleted


def delete_many(db: Session, manga_ids: Iterable[int]) -> tuple[int, int]:
    """Delete several series, one commit each so a failure keeps the rest.

    Returns ``(series deleted, chapters deleted)``.
    """

    series = chapters = 0
    for manga_id in manga_ids:
        try:
            deleted = delete_series(db, int(manga_id))
        except Exception:
            logger.exception("series_delete_failed", manga_id=manga_id)
            continue
        if deleted is not None:
            series += 1
            chapters += deleted
    return series, chapters


__all__ = ["delete_series", "delete_many"]
