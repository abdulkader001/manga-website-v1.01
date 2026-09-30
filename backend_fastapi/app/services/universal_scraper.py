"""Compatibility wrappers for scraping helpers used by admin tooling."""

from __future__ import annotations

import structlog
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlparse

from ..core.api_errors import ApiError, ErrorCode
from ..core.db import SessionLocal
from ..models import Chapter, Manga, ScrapingJob
from . import scraper_service
from .url_guard import normalize_url, validate_scrape_url

logger = structlog.get_logger(__name__)


def _close_if_needed(session, provided: Optional[object]) -> None:
    if provided is None:
        session.close()


def scrape_series_by_url(url: str, db_session=None, added_by=None) -> Dict[str, object]:
    """Create a scraping job for ``url`` to preserve legacy admin actions.

    F-19: raises ``ApiError`` rather than a bare ``ValueError`` -- this
    function's caller, ``manga_service.schedule_series_scrape``, already
    raises ``ApiError`` for every other gate (approval, rights, duplicate
    URL/job), and its own caller (``admin.py``'s ``create_series_by_url``)
    only re-raises ``ApiError`` as the structured envelope; a bare
    ``ValueError`` fell through to a generic 500 with no error code.
    """

    if not url:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "A manga URL is required",
            field="manga_url",
        )

    session = db_session or SessionLocal()
    try:
        norm_url = normalize_url(url)
        err = validate_scrape_url(norm_url, session)
        if err:
            raise ApiError(
                ErrorCode.VALIDATION_FAILED,
                f"URL validation failed: {err}",
                field="manga_url",
                details={"url": norm_url},
            )

        job = ScrapingJob(source_url=norm_url, status="queued", requested_by=added_by)
        session.add(job)
        session.flush()
        session.commit()
        session.refresh(job)
        logger.info("Scheduled scraping job %s for %s", job.id, url)

        # Enqueue the job
        from ..tasks.scraper_tasks import process_manga_scrape

        process_manga_scrape.delay(job.id)

        return {"job_id": job.id, "source_url": job.source_url, "status": job.status}
    finally:
        _close_if_needed(session, db_session)


def scrape_chapter_by_url(url: str) -> Dict[str, object]:
    """Return a lightweight preview payload for a chapter scrape."""

    parsed = urlparse(url or "")
    return {
        "title": parsed.path.rsplit("/", 1)[-1] or "Unknown",
        "chapter": "preview",
        "pages": [url],
        "source": parsed.netloc,
        "scraped_at": datetime.utcnow().isoformat(),
    }


def rescrape_series(manga: Manga, db_session=None) -> Dict[str, object]:
    session = db_session or SessionLocal()
    try:
        result = scraper_service.rescrape_series(manga, db_session=session)
        return result
    finally:
        _close_if_needed(session, db_session)


def rescrape_chapter(chapter: Chapter, db_session=None) -> Dict[str, object]:
    session = db_session or SessionLocal()
    try:
        result = scraper_service.rescrape_chapter(chapter, db_session=session)
        return result
    finally:
        _close_if_needed(session, db_session)


def delete_chapter_pages_only(chapter: Chapter, db_session=None) -> None:
    session = db_session or SessionLocal()
    try:
        scraper_service.delete_chapter_pages_only(chapter, db_session=session)
    finally:
        _close_if_needed(session, db_session)


def run_scheduled_scrape() -> Dict[str, object]:
    """Return a summary of queued jobs to mimic the legacy scheduled task."""

    session = SessionLocal()
    try:
        queued = (
            session.query(ScrapingJob).filter(ScrapingJob.status == "queued").count()
        )
        return {"status": "ok", "queued_jobs": queued}
    finally:
        session.close()


def run_fast_scrape() -> Dict[str, object]:
    """Alias for ``run_scheduled_scrape`` used by Celery beat."""

    return run_scheduled_scrape()


def report_manga_count_metric() -> Dict[str, object]:
    """Return the tracked-manga count metric (F-22: not a reindex).

    Previously named/scheduled as "nightly-full-reindex", implying a
    consistency/repair pass. It has only ever done this one COUNT(*) -- no
    scraping, no chapter checks, no writes -- so it's named for what it
    actually does.
    """

    session = SessionLocal()
    try:
        tracked = session.query(Manga).count()
        return {"status": "ok", "tracked_manga": tracked}
    finally:
        session.close()


__all__ = [
    "delete_chapter_pages_only",
    "rescrape_chapter",
    "rescrape_series",
    "run_fast_scrape",
    "report_manga_count_metric",
    "run_scheduled_scrape",
    "scrape_chapter_by_url",
    "scrape_series_by_url",
]
