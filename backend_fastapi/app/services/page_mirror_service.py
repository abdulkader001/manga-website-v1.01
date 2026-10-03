"""Database side of page mirroring: compress a chapter's pictures and swap the
stored page list over to our own WebP copies.

The chapter is readable from its source URLs the moment it is scraped; this
runs right after (as its own worker task, with its own time budget and
retries) so a slow image host can never make ingestion itself fail.
"""

from __future__ import annotations

from typing import Any, Dict, List

import structlog
from sqlalchemy.orm import Session

from ..models import Chapter
from ..utils.cache_invalidation import invalidate_manga_caches_sync
from . import page_image_service

logger = structlog.get_logger(__name__)


def _source_urls(chapter: Chapter) -> List[str]:
    if isinstance(chapter.source_pages, list) and chapter.source_pages:
        return [p for p in chapter.source_pages if isinstance(p, str) and p]
    pages = chapter.pages if isinstance(chapter.pages, list) else []
    return [p for p in pages if isinstance(p, str) and p and not page_image_service.is_local_url(p)]


def needs_mirroring(chapter: Chapter) -> bool:
    pages = chapter.pages if isinstance(chapter.pages, list) else []
    return any(isinstance(p, str) and p.startswith(("http://", "https://")) for p in pages)


def mirror_chapter_by_id(db: Session, chapter_id: int) -> Dict[str, Any]:
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        return {"status": "skipped", "reason": "chapter_not_found"}
    if not page_image_service.mirroring_enabled():
        return {"status": "skipped", "reason": "disabled"}
    from .takedown import is_taken_down

    if is_taken_down(chapter.manga):
        # plan.md P1-2: a taken-down series keeps no pictures on this server.
        return {"status": "skipped", "reason": "taken_down"}
    sources = _source_urls(chapter)
    if not sources or not needs_mirroring(chapter):
        return {"status": "skipped", "reason": "nothing_to_mirror"}

    referer, headers = page_image_service.referer_for_chapter(chapter.chapter_url)
    from .chapter_grouping import effective_layout

    manga_id, layout = chapter.manga_id, effective_layout(chapter.manga)
    # Downloading and compressing a whole chapter takes far longer than a
    # transaction should stay open: end it, then look the chapter up again.
    db.commit()
    result = page_image_service.mirror_chapter(
        manga_id, chapter_id, sources, referer=referer, headers=headers, layout=layout
    )
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        return {"status": "skipped", "reason": "chapter_removed"}
    if not result.mirrored:
        # Every page failed: keep the source URLs (still readable) and let the
        # task retry -- the source may just have been briefly unavailable.
        raise RuntimeError(
            f"no page of chapter {chapter_id} could be mirrored: {'; '.join(result.errors[:3])}"
        )
    chapter.source_pages = sources
    chapter.pages = result.urls
    chapter.pages_bytes = result.stored_bytes
    db.commit()
    invalidate_manga_caches_sync(chapter.manga_id)
    return {
        "status": "success",
        "pages": len(result.urls),
        "failed_pages": result.failed,
        "source_kb": result.source_bytes // 1024,
        "stored_kb": result.stored_bytes // 1024,
    }


def chapters_needing_mirror(db: Session, manga_id: int) -> List[int]:
    rows = db.query(Chapter).filter(Chapter.manga_id == manga_id).order_by(Chapter.chapter_number).all()
    return [c.id for c in rows if needs_mirroring(c)]
