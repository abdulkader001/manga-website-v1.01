"""Synchronous HTML scraper.

H6: this module intentionally uses blocking I/O (``time.sleep`` for rate
limiting and ``requests`` for HTTP). It is only ever executed inside Celery
tasks (see ``app.services.scraper_workflow_service`` → ``app.tasks.scraper_tasks``),
which run in Celery's default **prefork** worker pool — a classic multi-process,
non-async pool where blocking calls are correct and do not share an event loop
with the FastAPI API. Do NOT call ``BaseScraper`` from the async request path; if
scraping ever needs to move onto an event loop, switch to ``asyncio.sleep`` and
an async HTTP client at that time.
"""

import structlog
import time
from typing import Dict, Any, List, Optional
import requests
from bs4 import BeautifulSoup
from .config import ConfigManager
from .schemas import MangaSchema, ScrapedChapterSchema

logger = structlog.get_logger(__name__)

# Guardrails for within-chapter pagination (some sources split one chapter across
# several "next page" URLs; others put every page image on a single URL). These
# caps make following the "next" link safe: a chapter can never fetch unbounded
# pages, revisit a URL, or run forever on a site whose pagination loops back on
# itself.
MAX_PAGES_PER_CHAPTER = 200  # hard ceiling on paginated fetches for one chapter
MAX_IMAGES_PER_CHAPTER = 2000  # hard ceiling on collected page images


class ScraperError(Exception):
    pass


class BaseScraper:
    """
    Base scraper architecture with rate limiting, retries, and dynamic config.
    """

    def __init__(self, domain: str, delay: int = 1, retries: int = 3):
        self.domain = domain
        self.delay = delay
        self.retries = retries
        self.config = ConfigManager.get_config(domain)

    @property
    def module_id(self) -> str:
        """Version identity of the parser in use, e.g. ``example.com_v3``.

        Falls back to ``<domain>_v0`` when no versioned parser exists (legacy
        config or AI fallback).
        """
        try:
            from ..core.db import SessionLocal
            from ..models import ParserVersion

            with SessionLocal() as session:
                active = (
                    session.query(ParserVersion)
                    .filter(
                        ParserVersion.domain == self.domain,
                        ParserVersion.status == "active",
                    )
                    .first()
                )
                if active is not None:
                    return active.module_id
        except Exception:  # pragma: no cover - identity is best-effort
            pass
        return f"{self.domain}_v0"

    def _fetch_html(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch HTML with retries, rate limiting, and metrics."""
        from .metrics import ScraperMetrics
        from .concurrency import check_rate_limit
        from .http_client import RequestWrapper
        import random

        for attempt in range(self.retries):
            start_time = time.time()

            # Distributed Rate Limit check (e.g. 10 requests per 60 seconds per domain)
            while not check_rate_limit(self.domain, limit=10, window=60):
                logger.debug(f"Rate limit hit for {self.domain}. Backing off.")
                time.sleep(5)

            try:
                # Local Delay Rate limit with jitter
                delay = self.delay * (attempt + 1) + random.uniform(0.1, 1.0)
                time.sleep(delay)

                response = RequestWrapper.get(url, timeout=10)
                response.raise_for_status()

                latency_ms = int((time.time() - start_time) * 1000)
                ScraperMetrics.record_success(self.domain, latency_ms)

                return BeautifulSoup(response.content, "html.parser")
            except requests.RequestException as e:
                ScraperMetrics.record_retry(self.domain)
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                status_code = None
                if hasattr(e, "response") and e.response is not None:
                    status_code = e.response.status_code
                if status_code in {403, 429}:
                    logger.warning(
                        f"Possible block on {self.domain}. Increasing backoff."
                    )
                    time.sleep(
                        self.delay * (attempt + 1) * 2
                    )  # Additional backoff on blocks

        ScraperMetrics.record_failure(self.domain)
        logger.error(f"Failed to fetch {url} after {self.retries} attempts.")
        return None

    def get_existing_chapters(self, manga_id: int, db_session) -> List[float]:
        """Fetch existing chapter numbers from DB to avoid re-scraping."""
        from ..models import Chapter

        existing_chapters = (
            db_session.query(Chapter.chapter_number)
            .filter(Chapter.manga_id == manga_id)
            .all()
        )
        return [float(c[0]) for c in existing_chapters if c[0] is not None]

    def scrape_manga(
        self,
        url: str,
        existing_chapters: Optional[List[float]] = None,
        is_retry: bool = False,
        _ai_config: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Scrape manga details using dynamic config."""
        from .errors import ExtractionError

        soup = self._fetch_html(url)
        if not soup:
            raise ExtractionError(
                "Failed to fetch the series page after retries.",
                url=url,
                missing_field="page",
                scraper_module=self.module_id,
            )

        used_ai = False
        config_to_use = self.config

        if _ai_config:
            config_to_use = _ai_config
            used_ai = True

        if not config_to_use:
            logger.info("No config found. Triggering AI fallback.")
            config_to_use = self._ai_fallback(url, soup, type="manga")
            used_ai = True

        if not config_to_use:
            raise ExtractionError(
                "Could not determine selectors for this site. A website-"
                "specific parser is required.",
                url=url,
                missing_field="selectors",
                scraper_module=self.module_id,
            )

        try:
            title_tag = soup.select_one(config_to_use.get("manga_title", ""))
            desc_tag = soup.select_one(config_to_use.get("manga_description", ""))
            cover_tag = soup.select_one(config_to_use.get("manga_cover", ""))

            title = title_tag.text.strip() if title_tag else "Unknown"
            description = desc_tag.text.strip() if desc_tag else ""
            cover = cover_tag.get("src") if cover_tag else ""

            chapters = []
            chapter_items = soup.select(config_to_use.get("chapter_list", ""))
            if not chapter_items:
                raise ExtractionError(
                    "Could not extract the chapter list from this page. The "
                    "selector for the chapter container returned no elements.",
                    url=url,
                    missing_field="chapter_list",
                    selector_used=config_to_use.get("chapter_list"),
                    scraper_module=self.module_id,
                )
            for item in chapter_items:
                a_tag = item.select_one(config_to_use.get("chapter_url", "a"))
                if a_tag:
                    c_url = a_tag.get("href")
                    title_elem = item.select_one(config_to_use.get("chapter_title", ""))
                    num_elem = item.select_one(config_to_use.get("chapter_number", ""))
                    c_title = title_elem.text.strip() if title_elem else "Unknown"
                    c_num_str = num_elem.text.strip() if num_elem else "0"

                    try:
                        c_num = float(c_num_str)
                    except ValueError:
                        # F-23: a selector match that isn't actually numeric
                        # used to become chapter 0.0 with no trace -- log the
                        # raw string so a bad `chapter_number` selector on a
                        # source site is visible instead of silently
                        # mislabeling (and potentially colliding with a real)
                        # chapter 0.
                        logger.warning(
                            "Unparseable chapter number %r for %s (domain=%s); "
                            "defaulting to 0.0",
                            c_num_str,
                            url,
                            self.domain,
                        )
                        c_num = 0.0

                    if existing_chapters is None or c_num not in existing_chapters:
                        chapters.append(
                            {"url": c_url, "title": c_title, "number": c_num}
                        )

            manga_data = {
                "title": title,
                "description": description,
                "cover": cover,
                "chapters": chapters,
                "source_url": url,
            }

            # Validation: ensure AI config actually produced something meaningful before saving
            if used_ai:
                if title != "Unknown" and len(chapters) > 0:
                    # Note: We do not overwrite self.config directly, so it stays untouched in production config
                    self._register_ai_candidate(
                        config_to_use,
                        test_results={
                            "title_found": True,
                            "chapters_found": len(chapters),
                        },
                    )
                else:
                    raise ScraperError("AI Config produced invalid or empty results")

            return MangaSchema(**manga_data).model_dump()
        except Exception as e:
            logger.error(f"Failed extracting data with config: {e}")
            if not is_retry and not used_ai:
                # AI Fallback trigger on failure
                new_ai_config = self._ai_fallback(url, soup, type="manga")
                if new_ai_config:
                    # Attempt scrape again with AI config but don't overwrite domain config yet
                    return self.scrape_manga(
                        url, existing_chapters, is_retry=True, _ai_config=new_ai_config
                    )
            if isinstance(e, ExtractionError):
                raise
            raise ExtractionError(
                "Scraping failed and AI fallback could not resolve selectors.",
                url=url,
                scraper_module=self.module_id,
            )

    def scrape_chapter(
        self,
        url: str,
        is_retry: bool = False,
        _ai_config: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Scrape chapter pages using dynamic config."""
        from .errors import ExtractionError

        soup = self._fetch_html(url)
        if not soup:
            raise ExtractionError(
                "Failed to fetch the chapter page after retries.",
                url=url,
                missing_field="page",
                scraper_module=self.module_id,
            )

        used_ai = False
        config_to_use = self.config

        if _ai_config:
            used_ai = True
            if config_to_use:
                config_to_use = config_to_use.copy()
                config_to_use.update(_ai_config)
            else:
                config_to_use = _ai_config

        if not config_to_use or "page_images" not in config_to_use:
            logger.info("No config found for pages. Triggering AI fallback.")
            new_ai_config = self._ai_fallback(url, soup, type="chapter")
            if new_ai_config:
                used_ai = True
                if config_to_use:
                    config_to_use = config_to_use.copy()
                    config_to_use.update(new_ai_config)
                else:
                    config_to_use = new_ai_config

        if not config_to_use or "page_images" not in config_to_use:
            raise ExtractionError(
                "Could not determine page-image selectors for this site.",
                url=url,
                missing_field="page_images",
                scraper_module=self.module_id,
            )

        try:
            # Collect page images from the first chapter URL, then — only when
            # the config declares a ``next_page`` selector — follow the "next
            # page" link and keep collecting, so chapters split across several
            # paginated URLs are captured in full. Chapters that put every image
            # on one URL (no ``next_page`` selector, or one that matches nothing)
            # behave exactly as before: a single fetch, single extraction.
            from urllib.parse import urljoin

            pages: List[str] = []
            seen_images: set[str] = set()
            visited_urls: set[str] = {url}
            next_selector = (config_to_use.get("next_page") or "").strip()

            current_url = url
            current_soup = soup
            fetched_pages = 0

            while True:
                fetched_pages += 1
                page_images = self._extract_page_images(
                    current_soup, config_to_use["page_images"], current_url
                )
                for src in page_images:
                    if src in seen_images:
                        continue  # de-dupe across paginated pages, keep order
                    seen_images.add(src)
                    pages.append(src)
                    if len(pages) >= MAX_IMAGES_PER_CHAPTER:
                        logger.warning(
                            "Chapter image cap reached (%s) for %s; stopping",
                            MAX_IMAGES_PER_CHAPTER,
                            url,
                        )
                        break

                # Stop unless a next-page selector is configured AND resolves to
                # a not-yet-visited URL within the guardrail caps.
                if not next_selector or len(pages) >= MAX_IMAGES_PER_CHAPTER:
                    break
                if fetched_pages >= MAX_PAGES_PER_CHAPTER:
                    logger.warning(
                        "Chapter page cap reached (%s) for %s; stopping pagination",
                        MAX_PAGES_PER_CHAPTER,
                        url,
                    )
                    break

                next_tag = current_soup.select_one(next_selector)
                next_href = next_tag.get("href") if next_tag else None
                if not next_href:
                    break
                next_url = urljoin(current_url, next_href.strip())
                if next_url in visited_urls:
                    break  # pagination looped back on itself
                visited_urls.add(next_url)

                current_soup = self._fetch_html(next_url)
                if not current_soup:
                    # A failed hop ends pagination but keeps what we have; the
                    # empty-pages guard below still catches a total failure.
                    logger.warning(
                        "Failed to fetch paginated page %s for chapter %s",
                        next_url,
                        url,
                    )
                    break
                current_url = next_url

            if used_ai:
                if len(pages) > 0:
                    self._register_ai_candidate(
                        config_to_use, test_results={"pages_found": len(pages)}
                    )
                else:
                    raise ScraperError("AI Config produced no pages")

            if not pages:
                # 1G.9.4: an extraction that returned no usable data is a
                # failure, never a success.
                raise ExtractionError(
                    "The page-image selector returned no images while the "
                    "page itself loaded.",
                    url=url,
                    missing_field="pages",
                    selector_used=config_to_use.get("page_images"),
                    scraper_module=self.module_id,
                )

            chapter_data = {"pages": pages, "source_url": url}
            return ScrapedChapterSchema(**chapter_data).model_dump()
        except Exception as e:
            logger.error(f"Failed extracting pages with config: {e}")
            if not is_retry and not used_ai:
                new_ai_config = self._ai_fallback(url, soup, type="chapter")
                if new_ai_config:
                    return self.scrape_chapter(
                        url, is_retry=True, _ai_config=new_ai_config
                    )
            if isinstance(e, ExtractionError):
                raise
            raise ExtractionError(
                "Scraping failed and AI fallback could not resolve selectors.",
                url=url,
                scraper_module=self.module_id,
            )

    def _extract_page_images(
        self, soup: BeautifulSoup, selector: str, base_url: str
    ) -> List[str]:
        """Return absolute page-image URLs from one already-fetched page.

        Handles lazy-loaded images (``data-src``), skips inline base64 images,
        and resolves relative URLs against ``base_url``. Shared by the single-URL
        and paginated (``next_page``) chapter paths so both behave identically
        per page.
        """
        from urllib.parse import urljoin

        images: List[str] = []
        for tag in soup.select(selector):
            src = tag.get("src") or tag.get("data-src")
            if not src:
                continue
            src = src.strip()
            if src.startswith("data:image"):
                continue
            images.append(urljoin(base_url, src))
        return images

    def _register_ai_candidate(
        self, config_to_use: Dict[str, str], test_results: Dict[str, Any]
    ) -> None:
        """Register a successful in-scrape AI-fallback config for PA review.

        F-21: this mid-scrape fallback used to persist to
        ``scraper_config_pending_ai_<domain>`` via
        ``ConfigManager.save_pending_ai_config`` -- a key nothing in the
        codebase ever read, so a working AI-derived config had no way to
        reach production. Every other parser source (manual, rules, and the
        human-approved AI generation flow in ``parser_generation_service``)
        already flows through ``parser_versions_service``'s
        candidate -> PA-approval -> activation lifecycle (its module
        docstring: "AI-generated, manual, and rule-based parsers all flow
        through the same candidate -> approval path"). Routing this
        fallback's output through the same service makes it visible and
        promotable via the existing ``GET /admin/parsers/{domain}`` /
        ``POST /admin/parsers/versions/{id}/approve`` endpoints, with no new
        admin surface required.
        """
        from ..core.db import SessionLocal
        from ..services import parser_versions_service

        session = SessionLocal()
        try:
            duplicate = any(
                v.status == "candidate"
                and v.source == "ai_generated"
                and v.definition == config_to_use
                for v in parser_versions_service.list_for(session, self.domain)
            )
            if duplicate:
                return
            parser_versions_service.create_candidate(
                session,
                domain=self.domain,
                definition=config_to_use,
                source="ai_generated",
                test_results=test_results,
                notes=(
                    "Auto-registered from an in-scrape AI fallback (F-21); "
                    "awaiting PA approval before it can activate."
                ),
            )
            session.commit()
        finally:
            session.close()

    def _ai_fallback(
        self, url: str, soup: BeautifulSoup, type: str
    ) -> Optional[Dict[str, str]]:
        """
        AI Fallback mechanism.
        Extracts HTML and passes it to the AI fallback service.
        """
        logger.info(f"AI fallback analyzing HTML for {url} (type: {type})")
        from .ai_fallback import AIFallbackService

        return AIFallbackService.extract_selectors(str(soup), type)
