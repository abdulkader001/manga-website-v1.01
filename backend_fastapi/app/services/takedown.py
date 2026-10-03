"""Taking a series down removes its pictures, not just its pages (plan.md P1-2).

A takedown used to set ``manga.takedown_status`` and clear the caches. The API
then answered 451, but nginx serves the stored page and cover files straight
from disk, so every picture stayed reachable to anyone holding its address.

Now a takedown also deletes the series' stored page files and its cover file
(when no other series shares it), drops its OCR and translation caches, and
points its chapters back at the source pages they were mirrored from, so a
later restore can mirror them again. Nothing is downloaded while the series
stays taken down (``page_mirror_service`` and the scheduled checks skip it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chapter, Manga, OcrCache, TranslationCache

TAKEN_DOWN = "taken_down"


@dataclass
class TakedownResult:
    chapters: int = 0
    cover_file: Optional[str] = None
    _cleanup: List = field(default_factory=list)

    def remove_files(self) -> None:
        """Delete the picture files. Call after the database commit."""

        for step in self._cleanup:
            step()


def set_takedown(db: Session, manga: Manga, status: str, reason: Optional[str]) -> TakedownResult:
    """Record the decision; when it is a takedown, also strip the pictures.

    The caller commits, then calls ``remove_files()`` on the result.
    """

    manga.takedown_status = status
    manga.takedown_reason = (reason or "").strip() or None
    result = TakedownResult()
    if status != TAKEN_DOWN:
        return result

    from . import cover_service, page_image_service

    chapter_ids = select(Chapter.id).where(Chapter.manga_id == manga.id).scalar_subquery()
    db.query(TranslationCache).filter(TranslationCache.chapter_id.in_(chapter_ids)).delete(
        synchronize_session=False
    )
    db.query(OcrCache).filter(OcrCache.chapter_id.in_(chapter_ids)).delete(
        synchronize_session=False
    )

    for chapter in db.query(Chapter).filter(Chapter.manga_id == manga.id):
        pages = chapter.pages if isinstance(chapter.pages, list) else []
        if not any(page_image_service.is_local_url(p) for p in pages):
            continue
        sources = chapter.source_pages if isinstance(chapter.source_pages, list) else []
        chapter.pages = list(sources)
        chapter.pages_bytes = None
        result.chapters += 1

    manga_id = manga.id
    result._cleanup.append(lambda: page_image_service.delete_series_files(manga_id))

    cover = manga.cover_image or ""
    if cover.startswith(cover_service.COVER_URL_PREFIX):
        shared = (
            db.query(Manga.id)
            .filter(Manga.cover_image == cover, Manga.id != manga.id)
            .first()
        )
        manga.cover_image = None
        if shared is None:
            name = cover[len(cover_service.COVER_URL_PREFIX):]
            result.cover_file = name

            def _remove_cover(name=name) -> None:
                path = cover_service.path_for(name)
                if path is not None:
                    path.unlink(missing_ok=True)

            result._cleanup.append(_remove_cover)
    return result


def is_taken_down(manga: Optional[Manga]) -> bool:
    return manga is not None and (manga.takedown_status or "none") == TAKEN_DOWN


__all__ = ["TAKEN_DOWN", "TakedownResult", "is_taken_down", "set_takedown"]
