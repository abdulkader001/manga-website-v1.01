"""Scraper related Celery tasks."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator

import structlog
from celery.exceptions import Retry

from ..core.celery_app import celery_app
from ..core.db import SessionLocal
from ..models import Chapter, Manga, ScrapingJob
from ..services import universal_scraper
from ..services.scraper_workflow_service import ScraperWorkflowService

logger = structlog.get_logger(__name__)


def _invalidate_manga_caches_best_effort() -> None:
    """Item 34: drop cached manga list/detail pages after a write (scrape)."""

    try:
        import redis as _redis

        from ..utils.cache_invalidation import invalidate_all_manga_caches

        broker = celery_app.conf.broker_url or ""
        if broker.startswith(("redis://", "rediss://")):
            client = _redis.Redis.from_url(broker)
            invalidate_all_manga_caches(client)
    except Exception:  # never let cache invalidation break a scrape
        logger.warning("manga_cache_invalidation_failed")


@contextmanager
def _session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@celery_app.task(
    bind=True,
    time_limit=300,
    soft_time_limit=240,
    name="backend_fastapi.app.tasks.scraper_tasks.process_manga_scrape",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # F-17: this was 3600, implying these tasks get a full hour to back off
    # before their final retry. celery_app.py's wildcard task_annotations
    # entry always applies after and wins over this per-task kwarg for
    # retry_backoff_max specifically (confirmed via Celery's own annotation
    # resolution order, not overridable per-task in this version) -- 600 is
    # what's actually enforced, so that's what this now declares.
    retry_backoff_max=600,
)
def process_manga_scrape(self, job_id: int):
    """Async task to perform heavy manga scraping."""
    # F-29: this same call runs once per physical Celery attempt (up to
    # max_retries + 1 times) for one logical failure -- only the final,
    # truly-exhausted attempt should advance the scraper health-tracking
    # failure streak.
    is_final_attempt = self.request.retries >= self.max_retries
    with _session_scope() as session:
        service = ScraperWorkflowService(session)
        try:
            result = service.process_manga_scrape(
                job_id, is_final_attempt=is_final_attempt
            )
            _invalidate_manga_caches_best_effort()
            return result
        except Exception as exc:
            if isinstance(exc, Retry):
                raise
            if self.request.retries >= self.max_retries:
                logger.error(
                    "process_manga_scrape max retries reached",
                    job_id=job_id,
                    exc_info=exc,
                )
                from ..repositories import ScrapingJobRepository

                repo = ScrapingJobRepository(session)
                job = repo.get_by_id(job_id)
                if job:
                    repo.mark_failed(job, str(exc))
                    session.commit()
                    if job.requested_by:
                        from ..services.notification_service import notify_async

                        notify_async(
                            type="ingestion.failed",
                            title="Your manga submission could not be scraped",
                            body=(
                                f"{job.source_url or 'The submitted URL'} could "
                                f"not be scraped: {exc}. No series was created."
                            ),
                            user_id=job.requested_by,
                            data={"job_id": job.id, "source_url": job.source_url},
                            target_type="scraping_job",
                            target_id=job.id,
                        )
            else:
                logger.warning(
                    "Error in process_manga_scrape, retrying...",
                    job_id=job_id,
                    exc_info=exc,
                )
            raise exc


@celery_app.task(
    bind=True,
    time_limit=300,
    soft_time_limit=240,
    name="backend_fastapi.app.tasks.scraper_tasks.process_chapter_scrape",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # F-17: this was 3600, implying these tasks get a full hour to back off
    # before their final retry. celery_app.py's wildcard task_annotations
    # entry always applies after and wins over this per-task kwarg for
    # retry_backoff_max specifically (confirmed via Celery's own annotation
    # resolution order, not overridable per-task in this version) -- 600 is
    # what's actually enforced, so that's what this now declares.
    retry_backoff_max=600,
)
def process_chapter_scrape(self, chapter_id: int):
    """Async task to scrape chapter pages and handle image processing."""
    # F-29: see process_manga_scrape's identical comment -- only the final,
    # truly-exhausted attempt should advance the health-tracking failure
    # streak.
    is_final_attempt = self.request.retries >= self.max_retries
    with _session_scope() as session:
        service = ScraperWorkflowService(session)
        try:
            return service.process_chapter_scrape(
                chapter_id, is_final_attempt=is_final_attempt
            )
        except Exception as exc:
            if isinstance(exc, Retry):
                raise
            if self.request.retries >= self.max_retries:
                logger.error(
                    "process_chapter_scrape max retries reached",
                    chapter_id=chapter_id,
                    exc_info=exc,
                )
                # We need to mark the job associated with this chapter as failed too.
                # Find the most recent job for this chapter_url
                from ..repositories import ScrapingJobRepository

                repo = ScrapingJobRepository(session)
                chapter = session.get(Chapter, chapter_id)
                if chapter:
                    # Mark the chapter itself or the job
                    # The job might not be easily linked directly, but we can look it up by source_url
                    job = (
                        session.query(ScrapingJob)
                        .filter(ScrapingJob.source_url == chapter.chapter_url)
                        .order_by(ScrapingJob.id.desc())
                        .first()
                    )
                    if job:
                        repo.mark_failed(job, str(exc))
                        session.commit()
            else:
                logger.warning(
                    "Error in process_chapter_scrape, retrying...",
                    chapter_id=chapter_id,
                    exc_info=exc,
                )
            raise exc


@celery_app.task(
    bind=True,
    time_limit=300,
    soft_time_limit=240,
    name="backend_fastapi.app.tasks.scraper_tasks.scrape_series_by_url",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # F-17: this was 3600, implying these tasks get a full hour to back off
    # before their final retry. celery_app.py's wildcard task_annotations
    # entry always applies after and wins over this per-task kwarg for
    # retry_backoff_max specifically (confirmed via Celery's own annotation
    # resolution order, not overridable per-task in this version) -- 600 is
    # what's actually enforced, so that's what this now declares.
    retry_backoff_max=600,
)
def scrape_series_by_url(self, url: str) -> Dict[str, Any]:
    try:
        return universal_scraper.scrape_series_by_url(url)
    except Exception as exc:
        if isinstance(exc, Retry):
            raise
        logger.warning(
            "Error in scrape_series_by_url, retrying...",
            url=url,
            attempt=self.request.retries,
            exc_info=exc,
        )
        if self.request.retries >= self.max_retries:
            logger.error(
                "scrape_series_by_url max retries reached", url=url, exc_info=exc
            )
        raise exc


@celery_app.task(
    bind=True,
    time_limit=300,
    soft_time_limit=240,
    name="backend_fastapi.app.tasks.scraper_tasks.scrape_chapter_by_url",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # F-17: this was 3600, implying these tasks get a full hour to back off
    # before their final retry. celery_app.py's wildcard task_annotations
    # entry always applies after and wins over this per-task kwarg for
    # retry_backoff_max specifically (confirmed via Celery's own annotation
    # resolution order, not overridable per-task in this version) -- 600 is
    # what's actually enforced, so that's what this now declares.
    retry_backoff_max=600,
)
def scrape_chapter_by_url(self, url: str) -> Dict[str, Any]:
    try:
        return universal_scraper.scrape_chapter_by_url(url)
    except Exception as exc:
        if isinstance(exc, Retry):
            raise
        logger.warning(
            "Error in scrape_chapter_by_url, retrying...",
            url=url,
            attempt=self.request.retries,
            exc_info=exc,
        )
        if self.request.retries >= self.max_retries:
            logger.error(
                "scrape_chapter_by_url max retries reached", url=url, exc_info=exc
            )
        raise exc


@celery_app.task(
    bind=True,
    time_limit=300,
    soft_time_limit=240,
    name="backend_fastapi.app.tasks.scraper_tasks.rescrape_series",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # F-17: this was 3600, implying these tasks get a full hour to back off
    # before their final retry. celery_app.py's wildcard task_annotations
    # entry always applies after and wins over this per-task kwarg for
    # retry_backoff_max specifically (confirmed via Celery's own annotation
    # resolution order, not overridable per-task in this version) -- 600 is
    # what's actually enforced, so that's what this now declares.
    retry_backoff_max=600,
)
def rescrape_series(self, manga_id: int) -> Dict[str, Any]:
    try:
        with _session_scope() as session:
            manga = session.get(Manga, manga_id)
            if manga is None:
                raise ValueError(f"manga {manga_id} not found")
            return universal_scraper.rescrape_series(manga, db_session=session)
    except Exception as exc:
        if isinstance(exc, Retry):
            raise
        logger.warning(
            "Error in rescrape_series, retrying...",
            manga_id=manga_id,
            attempt=self.request.retries,
            exc_info=exc,
        )
        if self.request.retries >= self.max_retries:
            logger.error(
                "rescrape_series max retries reached", manga_id=manga_id, exc_info=exc
            )
        raise exc


@celery_app.task(
    bind=True,
    time_limit=300,
    soft_time_limit=240,
    name="backend_fastapi.app.tasks.scraper_tasks.rescrape_chapter",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    # F-17: this was 3600, implying these tasks get a full hour to back off
    # before their final retry. celery_app.py's wildcard task_annotations
    # entry always applies after and wins over this per-task kwarg for
    # retry_backoff_max specifically (confirmed via Celery's own annotation
    # resolution order, not overridable per-task in this version) -- 600 is
    # what's actually enforced, so that's what this now declares.
    retry_backoff_max=600,
)
def rescrape_chapter(self, chapter_id: int) -> Dict[str, Any]:
    try:
        with _session_scope() as session:
            chapter = session.get(Chapter, chapter_id)
            if chapter is None:
                raise ValueError(f"chapter {chapter_id} not found")
            return universal_scraper.rescrape_chapter(chapter, db_session=session)
    except Exception as exc:
        if isinstance(exc, Retry):
            raise
        logger.warning(
            "Error in rescrape_chapter, retrying...",
            chapter_id=chapter_id,
            attempt=self.request.retries,
            exc_info=exc,
        )
        if self.request.retries >= self.max_retries:
            logger.error(
                "rescrape_chapter max retries reached",
                chapter_id=chapter_id,
                exc_info=exc,
            )
        raise exc


@celery_app.task(
    name="backend_fastapi.app.tasks.scraper_tasks.delete_chapter_pages_only"
)
def delete_chapter_pages_only(chapter_id: int) -> Dict[str, Any]:
    with _session_scope() as session:
        chapter = session.get(Chapter, chapter_id)
        if chapter is None:
            raise ValueError(f"chapter {chapter_id} not found")
        universal_scraper.delete_chapter_pages_only(chapter, db_session=session)
        return {"status": "cleared", "chapter_id": chapter_id}


@celery_app.task(name="backend_fastapi.app.tasks.scraper_tasks.run_scheduled_scrape")
def run_scheduled_scrape() -> Dict[str, Any]:
    with _session_scope() as session:
        from ..repositories import ScrapingJobRepository

        repo = ScrapingJobRepository(session)
        queued = repo.get_queued_jobs()
        for job in queued:
            process_manga_scrape.delay(job.id)
        return {"status": "ok", "queued_jobs": len(queued)}


@celery_app.task(name="backend_fastapi.app.tasks.scraper_tasks.run_fast_scrape")
def run_fast_scrape() -> Dict[str, Any]:
    return run_scheduled_scrape()


@celery_app.task(
    name="backend_fastapi.app.tasks.scraper_tasks.report_manga_count_metric"
)
def report_manga_count_metric() -> Dict[str, Any]:
    # F-22: this was named/scheduled as "nightly-full-reindex" but only ever
    # did a SELECT count(*) -- no scraping, no chapter checks, no writes of
    # any kind. Renamed to describe what it actually does rather than
    # implying a consistency/repair pass that was never implemented.
    return universal_scraper.report_manga_count_metric()


@celery_app.task(name="backend_fastapi.app.tasks.scraper_tasks.sync")
def sync() -> Dict[str, Any]:
    return run_scheduled_scrape()


@celery_app.task(name="backend_fastapi.app.tasks.scraper_tasks.cleanup_stuck_jobs")
def cleanup_stuck_jobs() -> Dict[str, Any]:
    """Reset jobs that have been stuck in 'in_progress' state for too long."""
    from datetime import datetime, timedelta

    with _session_scope() as session:
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        from ..models import ScrapingJob

        stuck_jobs = (
            session.query(ScrapingJob)
            .filter(
                ScrapingJob.status == "in_progress", ScrapingJob.updated_at < cutoff
            )
            .all()
        )

        count = 0
        for job in stuck_jobs:
            job.status = "queued"
            job.error = "Reset from stuck in_progress state."
            count += 1

        if count > 0:
            session.commit()
            logger.info("Reset stuck scraping jobs to queued", count=count)

        return {"status": "ok", "reset_count": count}


__all__ = [
    "delete_chapter_pages_only",
    "rescrape_chapter",
    "rescrape_series",
    "run_fast_scrape",
    "report_manga_count_metric",
    "run_scheduled_scrape",
    "scrape_chapter_by_url",
    "scrape_series_by_url",
    "sync",
    "process_manga_scrape",
    "process_chapter_scrape",
    "cleanup_stuck_jobs",
]


@celery_app.task(name="backend_fastapi.app.tasks.scraper_tasks.bulk_delete_series_task")
def bulk_delete_series_task(unique_ids: list[int]):
    from ..core.db import SessionLocal
    from ..models import Manga, Chapter
    import structlog

    logger = structlog.get_logger("bulk_delete_task")
    db = SessionLocal()
    try:
        mangas = db.query(Manga).filter(Manga.id.in_(unique_ids)).all()
        count = 0
        deleted_chapters_total = 0
        for manga in mangas:
            deleted_chapters = (
                db.query(Chapter).filter(Chapter.manga_id == manga.id).delete()
            )
            db.delete(manga)
            count += 1
            deleted_chapters_total += deleted_chapters
        db.commit()
        logger.info(
            "Bulk delete complete",
            extra={"deleted_series": count, "deleted_chapters": deleted_chapters_total},
        )
    finally:
        db.close()


@celery_app.task(name="backend_fastapi.app.tasks.scraper_tasks.prune_history_task")
def prune_history_task():
    from ..core.db import SessionLocal
    from ..models import ReadHistory
    import datetime
    import structlog

    logger = structlog.get_logger("prune_history")
    db = SessionLocal()
    try:
        threshold = datetime.datetime.utcnow() - datetime.timedelta(days=90)
        deleted = (
            db.query(ReadHistory).filter(ReadHistory.last_read_at < threshold).delete()
        )
        db.commit()
        logger.info(
            "History pruned",
            extra={"deleted": deleted, "threshold": threshold.isoformat()},
        )
    finally:
        db.close()


@celery_app.task(
    name="backend_fastapi.app.tasks.scraper_tasks.generate_parser_task",
    time_limit=600,
    soft_time_limit=540,
)
def generate_parser_task(
    domain: str,
    base_url: str,
    trigger: str = "website_saved",
    series_url: str | None = None,
    chapter_urls: list[str] | None = None,
):
    """Invoke the scraper-creation AI for a website (SRS 1G.6.0A / 1G.8.4).

    Every outcome — candidate ready, honest failure, or AI unconfigured —
    ends in a notification to the Permanent Administrator.

    ``series_url`` / ``chapter_urls`` are the optional operator-supplied sample
    pages from the 1G.9 honest-failure report, used when homepage discovery
    could not locate a series page on its own.
    """

    from ..services import parser_generation_service

    with _session_scope() as session:
        return parser_generation_service.attempt_generation(
            session,
            domain=domain,
            base_url=base_url,
            trigger=trigger,
            series_url=series_url,
            chapter_urls=chapter_urls,
        )


@celery_app.task(
    name="backend_fastapi.app.tasks.scraper_tasks.staged_series_rescrape",
    time_limit=3600,
    soft_time_limit=3300,
)
def staged_series_rescrape(manga_id: int, actor_id: int = None) -> Dict[str, Any]:
    """Full-series rescrape with staged validation (SRS 1G.12.3 / 1G.12.4).

    Aborts — leaving existing data untouched — rather than ever emptying a
    series. ``actor_id`` is the initiating administrator, threaded through so
    the completion notification and audit entry can name them (1G.12.3).
    """

    from ..services import rescrape_service

    with _session_scope() as session:
        result = rescrape_service.run_staged_rescrape(
            session, manga_id, actor_id=actor_id
        )
    _invalidate_manga_caches_best_effort()
    return result


@celery_app.task(
    name="backend_fastapi.app.tasks.scraper_tasks.run_scheduled_chapter_checks"
)
def run_scheduled_chapter_checks() -> Dict[str, Any]:
    """Celery beat entry point for 1G.12A: check due series for new chapters.

    Low priority (1C.5.3) — capped per run so it never competes meaningfully
    with user-facing work; anything past the cap is simply due again next run
    (deferred, never dropped).
    """

    from ..services import scheduled_checks_service as svc

    with _session_scope() as session:
        due = svc.due_series(session, limit=svc.GLOBAL_MAX_SCHEDULED_CHECKS)
        results = {"checked": 0, "new_chapters": 0, "failed": 0}
        for manga in due:
            outcome = svc.run_check(session, manga)
            results["checked"] += 1
            if outcome.get("status") == "new_chapters_found":
                results["new_chapters"] += 1
            elif outcome.get("status") == "failed":
                results["failed"] += 1
        return results
