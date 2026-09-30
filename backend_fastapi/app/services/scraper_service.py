"""Simplified scraping service used by FastAPI admin routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from ..models import Chapter, Manga, ScrapingJob


def _job_to_dict(job: ScrapingJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "manga_id": job.manga_id,
        "source_url": job.source_url,
        "status": job.status,
        "error": job.error,
        "last_chapter_number": job.last_chapter_number,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def rescrape_series(manga: Manga, *, db_session: Session) -> Dict[str, Any]:
    """Queue a scraping job for the provided manga."""

    # Deduplication check
    existing_job = (
        db_session.query(ScrapingJob)
        .filter(
            ScrapingJob.manga_id == manga.id,
            ScrapingJob.status.in_(["queued", "in_progress"]),
        )
        .first()
    )

    if existing_job:
        return _job_to_dict(existing_job)

    job = ScrapingJob(
        manga_id=manga.id,
        source_url=manga.source_url,
        status="queued",
    )
    db_session.add(job)
    manga.last_scraped = datetime.utcnow()
    db_session.add(manga)
    db_session.commit()
    db_session.refresh(job)

    from ..tasks.scraper_tasks import process_manga_scrape

    process_manga_scrape.delay(job.id)

    return _job_to_dict(job)


def rescrape_chapter(chapter: Chapter, *, db_session: Session) -> Dict[str, Any]:
    """Queue a scraping job focused on a single chapter."""

    # Deduplication check
    existing_job = (
        db_session.query(ScrapingJob)
        .filter(
            ScrapingJob.source_url == chapter.chapter_url,
            ScrapingJob.status.in_(["queued", "in_progress"]),
        )
        .first()
    )

    if existing_job:
        return _job_to_dict(existing_job)

    job = ScrapingJob(
        manga_id=chapter.manga_id,
        source_url=chapter.chapter_url,
        status="queued",
        last_chapter_number=(
            str(chapter.chapter_number) if chapter.chapter_number is not None else None
        ),
    )
    chapter.scraped_at = datetime.utcnow()
    db_session.add(job)
    db_session.add(chapter)
    db_session.commit()
    db_session.refresh(job)

    from ..tasks.scraper_tasks import process_chapter_scrape

    process_chapter_scrape.delay(chapter.id)

    return _job_to_dict(job)


def delete_chapter_pages_only(chapter: Chapter, *, db_session: Session) -> None:
    """Remove stored pages for ``chapter`` without deleting the row."""

    chapter.pages = []
    chapter.scraped_at = None
    db_session.add(chapter)
    db_session.commit()


__all__ = ["delete_chapter_pages_only", "rescrape_chapter", "rescrape_series"]
