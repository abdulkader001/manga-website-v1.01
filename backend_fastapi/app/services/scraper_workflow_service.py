import structlog
from datetime import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session

from ..repositories import MangaRepository, ChapterRepository, ScrapingJobRepository
from ..scrapers.base_scraper import BaseScraper
from ..scrapers.concurrency import acquire_lock
from ..scrapers.errors import error_details_for

logger = structlog.get_logger(__name__)


class ScraperWorkflowService:
    def __init__(self, db_session: Session):
        self.db = db_session
        self.manga_repo = MangaRepository(db_session)
        self.chapter_repo = ChapterRepository(db_session)
        self.job_repo = ScrapingJobRepository(db_session)

    def _record_failure(self, job_id: int, exc: Exception, url: str) -> None:
        """Persist structured failure detail on the job (SRS 1G.5.3/1G.5.4).

        Runs after a rollback, so it re-fetches the job. Every failure names
        the URL and, when the scraper raised a typed error, the missing field
        and the selector that produced it.
        """

        try:
            self.db.rollback()
            job = self.job_repo.get_by_id(job_id)
            if job is None:
                return
            details = error_details_for(exc, url=url)
            job.error = details.get("message") or str(exc)
            job.error_details = details
            self.db.commit()
        except Exception:  # pragma: no cover - recording must never mask exc
            logger.warning("failed_to_record_scrape_failure", job_id=job_id)
            self.db.rollback()

    def process_manga_scrape(
        self, job_id: int, *, is_final_attempt: bool = True
    ) -> Dict[str, Any]:
        job = self.job_repo.get_by_id(job_id)
        if not job:
            logger.error(f"ScrapingJob {job_id} not found.")
            return {"status": "failed", "error": "job_not_found"}

        url = job.source_url
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        lock_key = f"scrape_lock:{url}"

        # 1G.7.7: a confirmed structure change halts ingestion for THIS
        # website only. Queued work for a disabled website is parked, not run.
        from .scraper_health_service import is_halted

        if is_halted(self.db, domain):
            logger.warning("ingestion_halted_for_website", domain=domain, url=url)
            return {"status": "skipped", "error": "website_disabled"}

        with acquire_lock(lock_key, timeout=600, wait_for=0) as acquired:
            if not acquired:
                logger.warning(
                    f"Could not acquire lock for {url}. It might be processing already."
                )
                return {"status": "failed", "error": "lock_not_acquired"}

            self.job_repo.mark_in_progress(job)
            self.db.commit()

            scraper = BaseScraper(domain)

            manga = None
            if job.manga_id:
                manga = self.manga_repo.get_by_id(job.manga_id)
            else:
                manga = self.manga_repo.get_by_url(url)
                if manga:
                    self.job_repo.update(job, manga_id=manga.id)

            existing_chapters = (
                self.chapter_repo.get_existing_chapter_numbers(manga.id)
                if manga
                else []
            )

            try:
                manga_data = scraper.scrape_manga(url, existing_chapters)

                if not manga:
                    # 1G.2.2: the series record is created only AFTER metadata
                    # extraction succeeded — a metadata failure creates no
                    # partial record.
                    manga = self.manga_repo.create(
                        title=manga_data.get("title", "Unknown"),
                        description=manga_data.get("description", ""),
                        cover_image=manga_data.get("cover", ""),
                        source_url=url,
                        last_scraped=datetime.utcnow(),
                        added_by=job.requested_by,
                        ingestion_status="scraping",
                    )
                    self.job_repo.update(job, manga_id=manga.id)
                else:
                    updates = {}
                    if manga_data.get("title") and manga_data["title"] != "Unknown":
                        updates["title"] = manga_data["title"]
                    if manga_data.get("description"):
                        updates["description"] = manga_data["description"]
                    if manga_data.get("cover"):
                        updates["cover_image"] = manga_data["cover"]
                    updates["last_scraped"] = datetime.utcnow()
                    updates["ingestion_status"] = "scraping"
                    updates["last_error"] = None
                    self.manga_repo.update(manga, **updates)

                chapters_data = manga_data.get("chapters", [])
                new_chapters = []

                existing_urls = (
                    self.chapter_repo.get_urls_for_manga(manga.id) if manga else set()
                )

                for c_data in chapters_data:
                    c_url = c_data.get("url")
                    if not c_url:
                        continue

                    if c_url not in existing_urls:
                        new_chapters.append(
                            {
                                "manga_id": manga.id,
                                "chapter_number": c_data.get("number", 0.0),
                                "chapter_title": c_data.get("title", ""),
                                "chapter_url": c_url,
                                "ingestion_status": "queued",
                            }
                        )

                if new_chapters:
                    self.chapter_repo.bulk_insert(new_chapters)

                self.job_repo.mark_success(job)
                self.db.commit()

                from ..tasks.scraper_tasks import process_chapter_scrape

                # 1G.2.3: chapters are ingested one by one, resumable — only
                # chapters without pages are (re)queued, so a failure at
                # chapter 400 of 600 never restarts from chapter 1.
                unscraped_chapters = self.chapter_repo.get_unscraped_chapters(manga.id)
                if unscraped_chapters:
                    for c in unscraped_chapters:
                        process_chapter_scrape.delay(c.id)
                else:
                    self._maybe_complete(manga.id)

                logger.info(f"Successfully scraped manga data for {url}")
                self._record_health(domain, success=True)
                return {"status": "success", "new_chapters_found": len(new_chapters)}
            except Exception as e:
                # 1G.7.4: a scraper failure never takes down the ingestion
                # service — it is recorded with structured detail and the task
                # boundary handles retry/backoff.
                logger.error(f"Failed to scrape manga {url}: {e}")
                self._record_failure(job_id, e, url)
                # F-29: Celery retries this same task body up to max_retries
                # times for ONE logical failure -- recording health on every
                # attempt advances the failure streak by 3 instead of 1,
                # letting a single transient outage (that just outlasts one
                # job's retry window) push a healthy site straight to
                # degraded. Only the truly-exhausted final attempt counts.
                if is_final_attempt:
                    self._record_health(domain, success=False, exc=e)
                raise e

    def _notify_fix_subscribers(self, chapter, *, success: bool, error=None) -> None:
        """Everyone who clicked Fix gets the completion notice (1G.12.2A)."""

        try:
            from .rescrape_service import notify_fix_subscribers

            notify_fix_subscribers(self.db, chapter, success=success, error=error)
        except Exception:  # pragma: no cover - best-effort
            logger.warning("fix_subscriber_notification_failed")
            self.db.rollback()

    def _record_health(self, domain: str, *, success: bool, exc=None) -> None:
        """Feed the structure-change detector (1G.7.8). Never masks errors."""

        try:
            from .scraper_health_service import record_failure, record_success

            if success:
                record_success(self.db, domain)
            else:
                record_failure(self.db, domain, exc or Exception("unknown"))
        except Exception:  # pragma: no cover - health is best-effort
            logger.warning("scraper_health_recording_failed", domain=domain)
            self.db.rollback()

    def _maybe_complete(self, manga_id: int) -> None:
        """Mark the series complete when no chapters remain pending, and
        notify the submitter (1G.2.2)."""

        from ..models import Chapter, Manga

        manga = self.db.get(Manga, manga_id)
        if manga is None:
            return
        pending = (
            self.db.query(Chapter)
            .filter(
                Chapter.manga_id == manga_id,
                Chapter.ingestion_status.notin_(["complete", "failed"]),
            )
            .count()
        )
        if pending:
            return
        if (manga.ingestion_status or "") == "complete":
            return
        manga.ingestion_status = "complete"

        # 1G.12A.1: Phase 2 (ongoing monitoring) starts the moment Phase 1
        # (initial ingestion) finishes.
        from .scheduled_checks_service import schedule_next_check

        schedule_next_check(self.db, manga)

        if manga.added_by:
            from .notification_service import notify_async

            notify_async(
                type="series.ingested",
                title=f"'{manga.title}' finished ingesting",
                body=(
                    f"All chapters of '{manga.title}' have been scraped and "
                    "the series is live in the catalogue."
                ),
                user_id=manga.added_by,
                data={"series_id": manga.id},
                target_type="series",
                target_id=manga.id,
            )
        self.db.commit()

    def process_chapter_scrape(
        self, chapter_id: int, *, is_final_attempt: bool = True
    ) -> Dict[str, Any]:
        chapter = self.chapter_repo.get_by_id(chapter_id)
        if not chapter:
            return {"status": "failed", "error": "chapter_not_found"}

        url = chapter.chapter_url
        from urllib.parse import urlparse

        domain = urlparse(url).netloc
        lock_key = f"scrape_chapter_lock:{url}"

        from .scraper_health_service import is_halted

        if is_halted(self.db, domain):
            logger.warning("ingestion_halted_for_website", domain=domain, url=url)
            return {"status": "skipped", "error": "website_disabled"}

        with acquire_lock(lock_key, timeout=300, wait_for=0) as acquired:
            if not acquired:
                return {"status": "failed", "error": "lock_not_acquired"}

            scraper = BaseScraper(domain)

            try:
                chapter_data = scraper.scrape_chapter(url)
                self.chapter_repo.update(
                    chapter,
                    pages=chapter_data.get("pages", []),
                    scraped_at=datetime.utcnow(),
                    ingestion_status="complete",
                )
                self.db.commit()
                self._maybe_complete(chapter.manga_id)

                logger.info(f"Successfully scraped chapter data for {url}")
                self._record_health(domain, success=True)
                self._notify_fix_subscribers(chapter, success=True)
                return {"status": "success", "pages_count": len(chapter.pages)}
            except Exception as e:
                logger.error(f"Failed to scrape chapter {url}: {e}")
                self.db.rollback()
                # F-29: see process_manga_scrape's identical comment -- only
                # the exhausted final attempt should count toward the
                # failure streak, not every retry of one logical failure.
                if is_final_attempt:
                    self._record_health(domain, success=False, exc=e)
                self._notify_fix_subscribers(chapter, success=False, error=str(e))
                try:
                    chapter = self.chapter_repo.get_by_id(chapter_id)
                    if chapter is not None:
                        # Existing pages are left untouched (1G.12.2) — only
                        # the status records that this attempt failed.
                        self.chapter_repo.update(chapter, ingestion_status="failed")
                        self.db.commit()
                except Exception:  # pragma: no cover
                    self.db.rollback()
                raise e
