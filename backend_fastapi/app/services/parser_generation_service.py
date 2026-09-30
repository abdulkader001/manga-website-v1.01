"""AI-assisted parser generation and repair (SRS 1G.8.2 / 1G.8.4 / 1G.9).

The workflow, exactly as specified:

    site analysis -> candidate extraction rules -> TEST against real pages
    (a listing page, a series page, and at least TWO chapter pages)
      -> all pass: register a CANDIDATE for Permanent Administrator review
         (never auto-activated, 1G.8.3)
      -> any fail: report honestly (1G.9) — the exact statement plus the
         specific inputs needed — and notify the PA's bell.

A generated parser is only ever presented as a candidate when every test
extracted real data from every page. A scraper that passes on some pages and
fails on others is a failure, not a success (1G.9.4).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import structlog
from sqlalchemy.orm import Session

from . import notification_service, parser_versions_service, scraper_ai_service

logger = structlog.get_logger(__name__)

# Path fragments that usually identify a series page on manga sites.
_SERIES_HINTS = ("/manga/", "/series/", "/comic/", "/title/", "/book/")


def _fetch_html(url: str) -> Optional[str]:
    """Fetch a page for parser generation/testing.

    Uses the same SSRF-hardened client as the production scraper (1H.4):
    validated before every request AND before following each redirect hop —
    a plain ``requests.get`` here would let a malicious "homepage URL" the
    Permanent Administrator pastes redirect the server into internal ranges
    or cloud metadata endpoints.
    """

    from ..scrapers.http_client import RequestWrapper

    try:
        response = RequestWrapper.get(url, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as exc:
        logger.info("parser_generation_fetch_failed", url=url, error=str(exc)[:200])
        return None


def _soup(html: str):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def _find_series_links(
    base_url: str, listing_html: str, *, limit: int = 5
) -> List[str]:
    host = urlparse(base_url).netloc
    links: List[str] = []
    for a in _soup(listing_html).find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        parsed = urlparse(href)
        if parsed.netloc != host:
            continue
        if any(hint in parsed.path.lower() for hint in _SERIES_HINTS):
            if href not in links:
                links.append(href)
        if len(links) >= limit:
            break
    return links


def _test_series_selectors(html: str, selectors: Dict[str, str]) -> Dict[str, Any]:
    from ..scrapers import parsing

    soup = _soup(html)
    selectors = selectors or {}
    title_el = parsing.select_one(soup, selectors.get("manga_title"))
    chapter_els = parsing.select(soup, selectors.get("chapter_list"))
    chapter_urls: List[str] = []
    for el in chapter_els:
        a = parsing.select_one(el, selectors.get("chapter_url", "a") or "a")
        if a is None and getattr(el, "name", None) == "a":
            a = el
        href = a.get("href") if a is not None else None
        if href:
            chapter_urls.append(href)
    title = parsing.text_of(title_el) if title_el is not None else ""
    return {
        "title": title or None,
        "chapter_count": len(chapter_els),
        "chapter_urls": chapter_urls,
        "passed": bool(title and chapter_urls),
    }


def _test_chapter_selectors(html: str, selectors: Dict[str, str]) -> Dict[str, Any]:
    from ..scrapers.base_scraper import BaseScraper

    soup = _soup(html)
    selectors = selectors or {}
    scraper = BaseScraper.__new__(BaseScraper)  # no DB/config lookup for a probe
    scraper.domain = "probe.invalid"
    scraper.config = selectors
    images = scraper._extract_page_images(
        soup, selectors.get("page_images"), "https://probe.invalid/", selectors
    )
    return {"image_count": len(images), "passed": len(images) > 0}


def generate_and_test(
    domain: str,
    base_url: str,
    *,
    series_url: Optional[str] = None,
    chapter_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the full 1G.8.2 workflow. Returns either

    ``{"possible": True, "definition": ..., "test_results": ...}`` — every
    test extracted real data — or the honest-failure report of 1G.9 with the
    step that could not be completed.

    ``series_url`` and ``chapter_urls`` are the operator-supplied samples the
    1G.9 honest-failure report asks for: when auto-discovery from the homepage
    cannot find a series page (a site whose URLs don't match the usual
    ``/manga/`` etc. hints), the Permanent Administrator can paste a real
    series page and two real chapter pages and generation proceeds from those
    directly, skipping discovery. Both are still fetched through the
    SSRF-hardened client, so a pasted URL cannot redirect the server into
    internal ranges.
    """

    def _failure(step: str) -> Dict[str, Any]:
        report = scraper_ai_service.honest_failure_report(domain)
        report["failed_step"] = step
        return report

    series_links_found = 0
    if series_url:
        # Operator supplied a sample series page: use it directly, no discovery.
        resolved_series_url = series_url
    else:
        listing_html = _fetch_html(base_url)
        if not listing_html:
            return _failure("fetch_homepage")

        series_links = _find_series_links(base_url, listing_html)
        if not series_links:
            # No recognizable series page reachable from the homepage: it is
            # not theoretically possible to derive extraction rules from this
            # URL alone (1G.9.1) — the caller should re-run with a sample
            # series_url (which the honest-failure report asks for).
            return _failure("discover_series_page")
        resolved_series_url = series_links[0]
        series_links_found = len(series_links)

    series_html = _fetch_html(resolved_series_url)
    if not series_html:
        return _failure("fetch_series_page")

    series_selectors = scraper_ai_service.generate_selectors(series_html, "manga")
    if not series_selectors:
        return _failure("generate_series_selectors")

    series_test = _test_series_selectors(series_html, series_selectors)
    if not series_test["passed"]:
        return _failure("test_series_page")

    # Operator-supplied chapter samples take precedence over discovered ones;
    # otherwise use the chapter links extracted from the series page.
    if chapter_urls:
        resolved_chapter_urls = [urljoin(resolved_series_url, u) for u in chapter_urls]
    else:
        resolved_chapter_urls = [
            urljoin(resolved_series_url, u) for u in series_test["chapter_urls"]
        ]
    if len(resolved_chapter_urls) < 2:
        # 1G.8.2 requires at least TWO chapter pages to test against.
        return _failure("insufficient_chapter_pages")
    chapter_urls = resolved_chapter_urls

    chapter_selectors: Optional[Dict[str, str]] = None
    chapter_tests: List[Dict[str, Any]] = []
    for chapter_url in chapter_urls[:2]:
        chapter_html = _fetch_html(chapter_url)
        if not chapter_html:
            return _failure("fetch_chapter_page")
        if chapter_selectors is None:
            chapter_selectors = scraper_ai_service.generate_selectors(
                chapter_html, "chapter"
            )
            if not chapter_selectors:
                return _failure("generate_chapter_selectors")
        test = _test_chapter_selectors(chapter_html, chapter_selectors)
        test["url"] = chapter_url
        chapter_tests.append(test)
        if not test["passed"]:
            # Passing on one chapter page and failing on another is a
            # failure, not a success (1G.9.4).
            return _failure("test_chapter_pages")

    definition = dict(series_selectors)
    definition.update(chapter_selectors or {})
    return {
        "possible": True,
        "domain": domain,
        "definition": definition,
        "test_results": {
            "listing_page": {
                "url": base_url,
                "series_links_found": series_links_found,
                "discovery": "operator_supplied" if series_url else "auto",
            },
            "series_page": {
                "url": resolved_series_url,
                "title": series_test["title"],
                "chapter_count": series_test["chapter_count"],
                "passed": True,
            },
            "chapter_pages": chapter_tests,
        },
    }


def attempt_generation(
    db: Session,
    *,
    domain: str,
    base_url: str,
    trigger: str = "website_saved",
    series_url: Optional[str] = None,
    chapter_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Invoke the scraper AI for a website and record the outcome (1G.6.0A).

    Every outcome notifies the Permanent Administrator — the admin is never
    left guessing. The output is only ever a *candidate* (1G.8.3).

    ``series_url`` / ``chapter_urls`` are the optional operator-supplied samples
    from the 1G.9 honest-failure report; when given, generation uses them
    instead of discovering pages from the homepage.
    """

    if not scraper_ai_service.is_configured():
        # 1G.8.8: with no scraper AI configured, the administrator is told a
        # parser must be supplied manually — the system never silently does
        # nothing. (The website-save path already writes this notification;
        # this covers the on-demand repair path.)
        notification_service.notify_async(
            type="parser.needed",
            title=f"{domain}: no scraper AI configured",
            body=(
                f"Parser generation for {domain} was requested but no "
                "scraper-generation AI is configured (Admin Panel -> API "
                "Management). Supply a parser manually or configure the AI "
                "and retry."
            ),
            data={"domain": domain, "trigger": trigger},
            target_type="website",
            target_id=domain,
        )
        return {"status": "not_configured"}

    result = generate_and_test(
        domain, base_url, series_url=series_url, chapter_urls=chapter_urls
    )

    if result.get("possible"):
        candidate = parser_versions_service.create_candidate(
            db,
            domain=domain,
            definition=result["definition"],
            source="ai_generated",
            test_results=result["test_results"],
            notes=f"Generated automatically ({trigger}).",
        )
        notification_service.notify_async(
            type="parser.candidate_ready",
            title=f"{domain}: generated parser ready for review",
            body=(
                f"A parser for {domain} was generated and passed its tests "
                "(listing page, series page, and two chapter pages). It is a "
                "CANDIDATE awaiting your approval — it will not activate on "
                "its own."
            ),
            data={
                "domain": domain,
                "version_id": candidate.id,
                "version": candidate.version,
            },
            target_type="parser",
            target_id=candidate.id,
        )
        db.commit()
        return {
            "status": "candidate",
            "version_id": candidate.id,
            "version": candidate.version,
            "test_results": result["test_results"],
        }

    # Honest failure (1G.9): the exact statement, the failing step, and the
    # specific inputs needed — to the PA's bell.
    notification_service.notify_async(
        type="parser.generation_failed",
        title=f"{domain}: automatic parser generation not possible",
        body=(
            result["message"]
            + " Needed: "
            + "; ".join(result["required_inputs"])
            + f" (failed step: {result.get('failed_step')})"
        ),
        data=result,
        target_type="website",
        target_id=domain,
    )
    return {"status": "failed", "report": result}
