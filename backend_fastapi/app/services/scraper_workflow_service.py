import structlog
from datetime import datetime
from types import SimpleNamespace
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

            manga = None
            if job.manga_id:
                manga = self.manga_repo.get_by_id(job.manga_id)
            else:
                manga = self.manga_repo.get_by_url(url)
                if manga:
                    self.job_repo.update(job, manga_id=manga.id)

            try:
                options = self._prepare_options(job, url)
                # Built after _prepare_options: it may have just activated the
                # parser this scrape should use.
                scraper = BaseScraper(domain)

                remap = bool(options.get("remap_chapters")) and manga is not None
                existing_chapters = (
                    self.chapter_repo.get_existing_chapter_numbers(manga.id)
                    if manga and not remap
                    else []
                )
                manga_data = scraper.scrape_manga(
                    url, None if remap else existing_chapters
                )
                if remap:
                    self._remap_chapter_urls(manga, manga_data.get("chapters", []))

                if not manga:
                    # 1G.2.2: the series record is created only AFTER metadata
                    # extraction succeeded — a metadata failure creates no
                    # partial record.
                    manga = self.manga_repo.create(
                        **self._new_series_fields(url, job, manga_data, options)
                    )
                    self.job_repo.update(job, manga_id=manga.id)
                else:
                    updates = {}
                    if not manga.mangaupdates_url:
                        # MangaUpdates-managed series keep their metadata; the
                        # source site only ever supplies chapters for them.
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
                cap = options.get("chapters_to_scrape") if options else None
                if isinstance(cap, int) and cap > 0 and len(chapters_data) > cap:
                    # The admin asked for only the latest N chapters.
                    chapters_data = sorted(
                        chapters_data, key=lambda c: c.get("number", 0.0)
                    )[-cap:]
                existing_urls = (
                    self.chapter_repo.get_urls_for_manga(manga.id) if manga else set()
                )

                from .chapter_grouping import build_chapter_rows, effective_layout

                layout = effective_layout(manga)
                status_value = getattr(manga.status, "value", manga.status)
                new_chapters = build_chapter_rows(
                    manga.id,
                    chapters_data,
                    group_size=layout["group_size"],
                    consumed_urls=existing_urls,
                    # A finished series has nothing more coming: publish the
                    # last, shorter group instead of holding it.
                    flush=str(status_value or "") == "completed",
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

    def _prepare_options(self, job, url: str) -> Dict[str, Any]:
        """Resolve what the submitter asked for before scraping starts.

        * ``ensure_parser``: find or generate a parser for this website (this
          is what makes a site on a new domain work), activating it when the
          submitter is allowed to.
        * ``mangaupdates_url``: load the series metadata from MangaUpdates. A
          failure fails the job loudly -- never an import with wrong metadata.
        """

        options = dict(job.options or {})
        changed = False

        if options.get("ensure_parser"):
            from ..models import User
            from ..scrapers.errors import ExtractionError
            from ..scrapers.source_pipeline import resolve_parser

            actor = self.db.get(User, job.requested_by) if job.requested_by else None
            result = resolve_parser(
                self.db, url, base_url=options.get("base_url"), actor=actor, activate=True
            )
            if not result.get("ok"):
                raise ExtractionError(
                    result.get("message") or "No parser could read this website.",
                    url=url,
                    missing_field="parser",
                    scraper_module=None,
                )
            options.pop("ensure_parser")
            changed = True

        mu_url = options.get("mangaupdates_url")
        if mu_url and "metadata" not in options:
            from ..scrapers.errors import ExtractionError
            from .mangaupdates_service import MangaUpdatesError, fetch_series

            try:
                metadata = fetch_series(mu_url).to_dict()
            except MangaUpdatesError as exc:
                raise ExtractionError(
                    f"MangaUpdates: {exc}", url=mu_url, missing_field="metadata"
                ) from exc
            options["metadata"] = metadata
            changed = True

        if changed:
            job.options = options
            self.db.commit()
        return options

    def _remap_chapter_urls(self, manga, scraped: list) -> None:
        """After a source moved to a new domain: point each existing chapter at
        its new URL (matched by chapter number), keeping its pages, so nothing
        is duplicated and a later re-scrape of one chapter hits the live site."""

        from ..models import Chapter

        by_number = {}
        for item in scraped:
            by_number.setdefault(float(item["number"]), item["url"])
        taken = {
            row[0]
            for row in self.db.query(Chapter.chapter_url).filter(Chapter.manga_id == manga.id)
        }
        remapped = 0
        from .chapter_grouping import remap_members

        for chapter in self.db.query(Chapter).filter(Chapter.manga_id == manga.id):
            # Grouped chapters carry several source URLs; move them all.
            members_moved = remap_members(chapter, by_number)
            new_url = by_number.get(float(chapter.chapter_number))
            if not new_url or new_url == chapter.chapter_url or new_url in taken:
                remapped += 1 if members_moved else 0
                continue
            taken.discard(chapter.chapter_url)
            taken.add(new_url)
            chapter.chapter_url = new_url
            if not chapter.pages:
                chapter.ingestion_status = "queued"
            remapped += 1
        self.db.flush()
        logger.info("chapters_remapped", manga_id=manga.id, remapped=remapped)

    def _new_series_fields(
        self, url: str, job, manga_data: Dict[str, Any], options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Column values for a brand-new series: MangaUpdates metadata when the
        submitter supplied it, otherwise what the source page said."""

        meta = dict(options.get("metadata") or {})
        if options.get("author"):
            meta["authors"] = [options["author"]]
        cover_source = (
            options.get("cover_override") or meta.get("cover_url") or manga_data.get("cover") or ""
        )
        cover = ""
        if cover_source:
            from .cover_service import fetch_and_store

            cover = fetch_and_store(cover_source, referer=url) or cover_source

        series_type = options.get("type") or meta.get("type") or "manga"
        if series_type not in {"manga", "manhwa", "manhua"}:
            series_type = "manga"
        status_value = meta.get("status") or "ongoing"
        if status_value not in {"ongoing", "completed", "hiatus", "dropped", "cancelled"}:
            status_value = "ongoing"

        fields: Dict[str, Any] = dict(
            title=(
                options.get("title")
                or meta.get("title")
                or manga_data.get("title")
                or "Unknown"
            ),
            description=meta.get("description") or manga_data.get("description", ""),
            cover_image=cover,
            source_url=url,
            last_scraped=datetime.utcnow(),
            added_by=job.requested_by,
            ingestion_status="scraping",
            type=series_type,
            status=status_value,
            genres=meta.get("genres") or manga_data.get("genres") or [],
            authors=meta.get("authors") or manga_data.get("authors") or [],
            artists=meta.get("artists") or [],
            alternative_titles=meta.get("alt_titles") or [],
            mangaupdates_url=meta.get("url"),
        )
        if options.get("description"):
            fields["description"] = options["description"]
        if options.get("text_language"):
            fields["language"] = options["text_language"]
        if options.get("interval_hours"):
            fields["check_interval_hours"] = int(options["interval_hours"])
        if options.get("auto_scrape_enabled") is False:
            fields["auto_scrape_enabled"] = False
        if options.get("layout"):
            from .chapter_grouping import normalize_layout

            fields["scrape_layout"] = normalize_layout(options["layout"]) or None
        return fields

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

        if manga.auto_scrape_enabled is not False:
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

    @staticmethod
    def _scrape_chapter_pages(scraper, chapter) -> Dict[str, Any]:
        """Pages of a chapter; for a grouped chapter, every member's pages
        joined in reading order (each member follows its own pagination)."""

        members = [
            m["url"]
            for m in (chapter.group_urls or [])
            if isinstance(m, dict) and m.get("url")
        ]
        if len(members) < 2:
            return scraper.scrape_chapter(chapter.chapter_url)
        pages: list = []
        seen: set = set()
        for member_url in members:
            for page in scraper.scrape_chapter(member_url).get("pages", []):
                if page not in seen:
                    seen.add(page)
                    pages.append(page)
        return {"pages": pages, "source_url": chapter.chapter_url}

    def _queue_page_mirroring(self, chapter_id: int) -> None:
        """Compress and self-host the chapter's pictures (own task, own
        retries). Never lets a broker hiccup fail the scrape itself."""

        try:
            from ..tasks.scraper_tasks import mirror_chapter_pages

            mirror_chapter_pages.delay(chapter_id)
        except Exception:  # pragma: no cover - broker unavailable
            logger.warning("page_mirroring_not_queued", chapter_id=chapter_id)

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
                # Fetching every page of a (possibly grouped or paginated)
                # chapter is slow network work: don't sit in a transaction.
                members = SimpleNamespace(
                    chapter_url=chapter.chapter_url,
                    group_urls=list(chapter.group_urls or []),
                )
                self.db.commit()
                chapter_data = self._scrape_chapter_pages(scraper, members)
                chapter = self.chapter_repo.get_by_id(chapter_id)
                self.chapter_repo.update(
                    chapter,
                    pages=chapter_data.get("pages", []),
                    source_pages=None,
                    pages_bytes=None,
                    scraped_at=datetime.utcnow(),
                    ingestion_status="complete",
                )
                self.db.commit()
                self._maybe_complete(chapter.manga_id)
                self._queue_page_mirroring(chapter.id)

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
