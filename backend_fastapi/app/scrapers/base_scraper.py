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
from . import parsing

logger = structlog.get_logger(__name__)

# Guardrails for within-chapter pagination (some sources split one chapter across
# several "next page" URLs; others put every page image on a single URL). These
# caps make following the "next" link safe: a chapter can never fetch unbounded
# pages, revisit a URL, or run forever on a site whose pagination loops back on
# itself.
MAX_PAGES_PER_CHAPTER = 200  # hard ceiling on paginated fetches for one chapter
MAX_IMAGES_PER_CHAPTER = 2000  # hard ceiling on collected page images
MAX_CHAPTER_LIST_PAGES = 60  # hard ceiling on paginated chapter-list fetches
MAX_CHAPTERS_PER_SERIES = 20000


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

    def _request_headers(self) -> Dict[str, str]:
        """Per-source request headers from the parser config (UA, language,
        Referer...). Header values come from admin-approved configs only."""

        headers: Dict[str, str] = {}
        config = self.config or {}
        configured = config.get("headers")
        if isinstance(configured, dict):
            for key, value in configured.items():
                if isinstance(key, str) and isinstance(value, str) and "\n" not in value:
                    headers[key] = value
        return headers

    def _fetch_html(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch HTML with retries, rate limiting, and metrics."""
        from .metrics import ScraperMetrics
        from .concurrency import check_rate_limit
        from .http_client import RequestWrapper
        import random

        headers = self._request_headers()
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

                response = RequestWrapper.get(url, timeout=10, headers=dict(headers))
                response.raise_for_status()

                latency_ms = int((time.time() - start_time) * 1000)
                ScraperMetrics.record_success(self.domain, latency_ms)

                encoding = (self.config or {}).get("encoding")
                if encoding:
                    return BeautifulSoup(
                        response.content, "html.parser", from_encoding=encoding
                    )
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

    def _fetch_json(self, url: str) -> Any:
        """GET a JSON document (chapter-list APIs) through the same SSRF-safe
        client and headers as page fetches."""
        from .http_client import RequestWrapper
        import json as _json

        headers = self._request_headers()
        headers.setdefault("Accept", "application/json")
        for attempt in range(self.retries):
            try:
                time.sleep(self.delay * (attempt + 1))
                response = RequestWrapper.get(url, timeout=10, headers=dict(headers))
                response.raise_for_status()
                return _json.loads(response.content)
            except (requests.RequestException, ValueError) as e:
                logger.warning(f"JSON fetch attempt {attempt + 1} failed for {url}: {e}")
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
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Scrape manga details using dynamic config.

        ``dry_run`` is for admin previews: no AI fallback, and nothing is
        registered (no candidate parser rows).
        """
        from .errors import ExtractionError

        if dry_run:
            is_retry = True
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

        if not config_to_use and not dry_run:
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
            details = self._extract_series_details(soup, url, config_to_use)
            title = details["title"] or "Unknown"
            description = details["description"]
            cover = details["cover"]

            chapters = []
            raw_chapters = self._collect_chapters(soup, url, config_to_use)
            if not raw_chapters:
                raise ExtractionError(
                    "Could not extract the chapter list from this page. The "
                    "selector for the chapter container returned no elements.",
                    url=url,
                    missing_field="chapter_list",
                    selector_used=config_to_use.get("chapter_list"),
                    scraper_module=self.module_id,
                )
            for c_data in raw_chapters:
                c_num = c_data["number"]
                if existing_chapters is None or c_num not in existing_chapters:
                    chapters.append(c_data)

            manga_data = {
                "title": title,
                "description": description,
                "cover": cover,
                "chapters": chapters,
                "source_url": url,
                "total_chapters": len(raw_chapters),
                "authors": details["authors"],
                "genres": details["genres"],
            }

            # Validation: ensure AI config actually produced something meaningful before saving
            if used_ai and not dry_run:
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

        if not config_to_use or not (
            "page_images" in config_to_use or "image_source" in config_to_use
        ):
            logger.info("No config found for pages. Triggering AI fallback.")
            new_ai_config = self._ai_fallback(url, soup, type="chapter")
            if new_ai_config:
                used_ai = True
                if config_to_use:
                    config_to_use = config_to_use.copy()
                    config_to_use.update(new_ai_config)
                else:
                    config_to_use = new_ai_config

        if not config_to_use or not (
            "page_images" in config_to_use or "image_source" in config_to_use
        ):
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
                    current_soup,
                    config_to_use.get("page_images"),
                    current_url,
                    config_to_use,
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
        self,
        soup: BeautifulSoup,
        selector: Optional[str],
        base_url: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Return absolute page-image URLs from one already-fetched page.

        Handles lazy-loaded images (``data-src`` and friends, ``srcset``),
        skips inline base64 images and lazy-load placeholders, resolves
        relative URLs against ``base_url``, and reads images embedded as JSON
        when the config declares an ``image_source``. Shared by the
        single-URL and paginated (``next_page``) chapter paths.
        """

        config = config or self.config or {}
        images: List[str] = []
        source = config.get("image_source")
        if isinstance(source, dict) and source.get("decoder") == "manhuagui":
            from . import packed_scripts

            images.extend(packed_scripts.manhuagui_images(soup, source.get("host") or "https://i.hamreus.com"))
        elif isinstance(source, dict):
            images.extend(self._images_from_json(soup, source, base_url))
        if not images:
            preferred = config.get("image_attr")
            for tag in parsing.select(soup, selector):
                url = parsing.image_url(tag, base_url, preferred)
                if url:
                    images.append(url)
        images = parsing.dedupe(images)
        skip = int(config.get("skip_first_images") or 0)
        return images[skip:] if skip > 0 else images

    def _images_from_json(
        self, soup: BeautifulSoup, source: Dict[str, Any], base_url: str
    ) -> List[str]:
        data = parsing.json_from_scripts(
            soup,
            script_selector=source.get("script_selector"),
            marker=source.get("marker"),
        )
        found = parsing.dig(data, source.get("path"))
        urls: List[str] = []
        template = source.get("url_template")
        field = source.get("field")
        for entry in found if isinstance(found, list) else []:
            value = entry.get(field) if isinstance(entry, dict) and field else entry
            if isinstance(value, dict):
                value = value.get("url") or value.get("src")
            if not isinstance(value, str):
                continue
            if template:
                value = template.replace("{value}", value)
            url = parsing.absolute(base_url, value)
            if url:
                urls.append(url)
        return urls

    # ------------------------------------------------------------------
    # Series details and chapter lists
    # ------------------------------------------------------------------

    def _extract_series_details(
        self, soup: BeautifulSoup, url: str, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        title_tag = parsing.select_one(soup, config.get("manga_title"))
        desc_tag = parsing.select_one(soup, config.get("manga_description"))
        cover_tag = parsing.select_one(soup, config.get("manga_cover"))

        cover = ""
        if cover_tag is not None:
            if getattr(cover_tag, "name", None) == "meta":
                cover = parsing.absolute(url, cover_tag.get("content")) or ""
            else:
                cover = parsing.image_url(cover_tag, url) or ""

        authors = [
            parsing.text_of(tag)
            for tag in parsing.select(soup, config.get("manga_author"))
            if parsing.text_of(tag)
        ]
        genres = [
            parsing.text_of(tag)
            for tag in parsing.select(soup, config.get("manga_genres"))
            if parsing.text_of(tag)
        ]
        return {
            "title": parsing.text_of(title_tag) if title_tag is not None else "",
            "description": parsing.text_of(desc_tag) if desc_tag is not None else "",
            "cover": cover,
            "authors": parsing.dedupe(authors)[:10],
            "genres": parsing.dedupe(genres)[:30],
        }

    def _chapter_from_item(
        self, item: Any, base_url: str, config: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        link_selector = config.get("chapter_url", "a") or "a"
        link = parsing.select_one(item, link_selector)
        if link is None and getattr(item, "name", None) == "a":
            link = item  # the list selector already points at the <a> itself
        href = link.get("href") if link is not None else None
        chapter_url = parsing.absolute(base_url, href)
        if not chapter_url:
            return None

        title_elem = parsing.select_one(item, config.get("chapter_title"))
        num_elem = parsing.select_one(item, config.get("chapter_number"))
        title = parsing.text_of(title_elem) or parsing.text_of(link) or "Unknown"

        if num_elem is not None:
            raw_number = parsing.text_of(num_elem)
            number = parsing.parse_chapter_number(raw_number)
            if number is None:
                # F-23: a selector match that isn't actually numeric used to
                # become chapter 0.0 with no trace -- log the raw string so a
                # bad `chapter_number` selector on a source site is visible
                # instead of silently mislabeling (and potentially colliding
                # with a real) chapter 0.
                logger.warning(
                    "Unparseable chapter number %r for %s (domain=%s); "
                    "defaulting to 0.0",
                    raw_number,
                    base_url,
                    self.domain,
                )
                number = 0.0
        else:
            number = parsing.parse_chapter_number(title, parsing.text_of(link))
            if number is None:
                number = parsing.chapter_number_from_url(chapter_url)
            if number is None:
                number = 0.0
        return {"url": chapter_url, "title": title, "number": float(number)}

    def _chapters_from_html(
        self, soup: BeautifulSoup, base_url: str, config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        chapters: List[Dict[str, Any]] = []
        for item in parsing.select(soup, config.get("chapter_list")):
            chapter = self._chapter_from_item(item, base_url, config)
            if chapter is not None:
                chapters.append(chapter)
        return chapters

    def _chapters_from_json(
        self,
        data: Any,
        base_url: str,
        source: Dict[str, Any],
        series_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        found = parsing.dig(data, source.get("path"))
        if isinstance(found, dict):
            found = list(found.values())
        fields = source.get("fields") or {}
        template = source.get("url_template")
        skip = source.get("skip_if") or {}
        chapters: List[Dict[str, Any]] = []
        for entry in found if isinstance(found, list) else []:
            if not isinstance(entry, dict):
                continue
            if skip.get("field") and parsing.dig(entry, skip["field"]) == skip.get("equals"):
                continue  # e.g. paid / locked chapters
            raw_url = parsing.dig(entry, fields.get("url", "url"))
            raw_number = parsing.dig(entry, fields.get("number", "number"))
            if template:
                raw_url = (
                    template.replace("{url}", str(raw_url or ""))
                    .replace("{id}", str(parsing.dig(entry, fields.get("id", "id")) or ""))
                    .replace("{number}", str(raw_number if raw_number is not None else ""))
                    .replace("{series_id}", series_id or "")
                )
            chapter_url = parsing.absolute(base_url, str(raw_url) if raw_url else None)
            if not chapter_url:
                continue
            raw_title = parsing.dig(entry, fields.get("title", "title"))
            title = str(raw_title).strip() if raw_title else ""
            number = None
            if isinstance(raw_number, (int, float)) and not isinstance(raw_number, bool):
                number = float(raw_number)
            elif raw_number is not None:
                number = parsing.parse_chapter_number(str(raw_number))
            if number is None:
                number = parsing.parse_chapter_number(title)
            if number is None:
                number = parsing.chapter_number_from_url(chapter_url)
            chapters.append(
                {
                    "url": chapter_url,
                    "title": title or (f"Chapter {number:g}" if number is not None else "Unknown"),
                    "number": float(number) if number is not None else 0.0,
                }
            )
        return chapters

    def _chapters_from_api(
        self, api: Dict[str, Any], page_url: str, config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        series_id = self._series_id(page_url, config)
        if series_id is None and "{series_id}" in str(api.get("url", "")):
            return []
        first_url = parsing.absolute(
            page_url, str(api["url"]).replace("{series_id}", series_id or "")
        )
        if not first_url:
            return []
        data = self._fetch_json(first_url)
        chapters = self._chapters_from_json(data, page_url, api, series_id)
        paginate = api.get("paginate")
        if isinstance(paginate, dict) and data is not None:
            param = paginate.get("param") or "page"
            try:
                total = int(parsing.dig(data, paginate.get("total_path")) or 1)
            except (TypeError, ValueError):
                total = 1
            from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

            for page in range(2, min(total, MAX_CHAPTER_LIST_PAGES) + 1):
                parts = urlparse(first_url)
                query = dict(parse_qsl(parts.query))
                query[param] = str(page)
                more = self._fetch_json(urlunparse(parts._replace(query=urlencode(query))))
                if more is None:
                    break
                batch = self._chapters_from_json(more, page_url, api, series_id)
                if not batch:
                    break
                chapters.extend(batch)
        return chapters

    def _series_id(self, page_url: str, config: Dict[str, Any]) -> Optional[str]:
        import re

        pattern = config.get("series_id_regex") or r"/([^/?#]+)/?(?:[?#].*)?$"
        match = re.search(pattern, page_url)
        return match.group(1) if match else None

    def _collect_chapters(
        self, soup: BeautifulSoup, url: str, config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Every chapter the source lists, de-duplicated and ordered oldest
        first: DOM list (following ``chapter_list_next`` pagination), embedded
        JSON (``chapter_source``) or a JSON API (``chapter_api``)."""

        chapters: List[Dict[str, Any]] = []
        source = config.get("chapter_source")
        if isinstance(source, dict):
            data = parsing.json_from_scripts(
                soup,
                script_selector=source.get("script_selector"),
                marker=source.get("marker"),
            )
            chapters = self._chapters_from_json(data, url, source)

        api = config.get("chapter_api")
        if not chapters and isinstance(api, dict) and api.get("url"):
            chapters = self._chapters_from_api(api, url, config)

        if not chapters:
            chapters = self._chapters_from_html(soup, url, config)
            next_selector = (config.get("chapter_list_next") or "").strip()
            current_soup, current_url = soup, url
            visited = {url}
            fetched = 1
            while next_selector and fetched < MAX_CHAPTER_LIST_PAGES:
                next_tag = parsing.select_one(current_soup, next_selector)
                next_url = parsing.absolute(current_url, next_tag.get("href")) if next_tag is not None else None
                if not next_url or next_url in visited:
                    break
                visited.add(next_url)
                current_soup = self._fetch_html(next_url)
                fetched += 1
                if not current_soup:
                    break
                current_url = next_url
                more = self._chapters_from_html(current_soup, current_url, config)
                if not more:
                    break
                chapters.extend(more)

        return self._normalise_chapters(chapters)

    @staticmethod
    def _normalise_chapters(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        unique: Dict[str, Dict[str, Any]] = {}
        for chapter in chapters:
            unique.setdefault(chapter["url"], chapter)
        ordered = list(unique.values())[:MAX_CHAPTERS_PER_SERIES]
        # Sources list newest-first or oldest-first; either way, oldest first.
        # sorted() is stable, so equal numbers keep the source's order.
        return sorted(ordered, key=lambda c: c["number"])

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
