"""PDF inspection helpers used by periodic tasks."""

from __future__ import annotations

import structlog
from typing import Any, Dict, Iterable, Tuple

from sqlalchemy.sql import expression

from ..core.db import SessionLocal
from ..models import Chapter

logger = structlog.get_logger(__name__)


def _iter_pdf_pages(pages: Any) -> Iterable[Tuple[int, Dict[str, Any]]]:
    """Yield ``(index, page_dict)`` pairs for PDF-like pages."""

    if not isinstance(pages, list):
        return []
    pdf_like: list[Tuple[int, Dict[str, Any]]] = []
    for idx, entry in enumerate(pages):
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("type") or entry.get("format") or "").lower()
        url = str(entry.get("url") or entry.get("pdf_url") or "")
        if "pdf" in kind or url.lower().endswith(".pdf"):
            pdf_like.append((idx, entry))
    return pdf_like


def _page_has_ocr(entry: Dict[str, Any]) -> bool:
    for key in ("ocr", "ocr_text", "text", "tokens"):
        value = entry.get(key)
        if isinstance(value, (str, list, dict)) and value:
            return True
    return False


def refresh_pdf_integrity() -> Dict[str, Any]:
    """Scan stored PDF pages and log any that are missing OCR overlays."""

    checked_pages = 0
    missing_ocr = 0

    session = SessionLocal()
    try:
        chapters: Iterable[Tuple[int, Any]] = (
            session.query(Chapter.id, Chapter.pages)
            .filter(Chapter.pages.isnot(None))
            .filter(Chapter.pages != expression.null())
            .all()
        )
    finally:
        session.close()

    for chapter_id, pages in chapters:
        for idx, page in _iter_pdf_pages(pages):
            checked_pages += 1
            if _page_has_ocr(page):
                continue
            missing_ocr += 1
            logger.warning(
                "PDF OCR missing",
                extra={
                    "chapter_id": chapter_id,
                    "page_index": idx,
                    "page_url": page.get("url") or page.get("pdf_url"),
                },
            )

    logger.info(
        "PDF OCR integrity scan complete: %s checked, %s missing overlays",
        checked_pages,
        missing_ocr,
    )
    return {
        "status": "completed",
        "pdf_pages_checked": checked_pages,
        "pages_missing_ocr": missing_ocr,
    }


__all__ = ["refresh_pdf_integrity"]
