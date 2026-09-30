"""Selector extraction via the PA-configured scraper-creation AI (SRS 1G.8.7).

This is the ONLY consumer of ``scraper_ai_service.generate_selectors`` — the
scraper AI has no other entry point in the system (1G.8.8): it generates and
repairs parsers, nothing else.

When no scraper AI is configured, a conservative structural heuristic is
attempted instead. Both paths feed the same validation gate in
``BaseScraper`` — selectors that extract nothing are a failure (1G.9.4),
never silently accepted.
"""

import structlog
from typing import Dict, Optional

logger = structlog.get_logger(__name__)


class AIFallbackService:
    _KEEP_ATTRS = {
        "id", "class", "href", "src", "data-src", "data-original", "data-lazy-src",
        "srcset", "itemprop", "property", "content", "rel", "name", "alt", "title",
    }
    MAX_HTML_CHARS = 24000
    MAX_SIBLING_RUN = 3

    @staticmethod
    def _simplify_dom(html_content: str) -> str:
        """Shrink a page to what selector-writing needs.

        Real series pages are hundreds of KB, and a chapter list is usually far
        past the first few thousand characters, so a plain truncation hides
        exactly what the AI has to find. Drop scripts/styles, keep only
        structural attributes, shorten text, and collapse long runs of
        identical siblings (a 600-chapter list) to a few examples.
        """
        from bs4 import BeautifulSoup, Comment, NavigableString, Tag

        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "svg", "path", "form", "noscript", "iframe", "link", "head"]):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        for tag in soup.find_all(True):
            tag.attrs = {
                key: (" ".join(value) if isinstance(value, list) else value)
                for key, value in tag.attrs.items()
                if key in AIFallbackService._KEEP_ATTRS
            }
            for key in ("href", "src", "data-src", "data-original", "data-lazy-src"):
                if key in tag.attrs and len(str(tag.attrs[key])) > 140:
                    tag.attrs[key] = str(tag.attrs[key])[:140]
            for child in list(tag.children):
                if isinstance(child, NavigableString):
                    text = " ".join(str(child).split())
                    if not text:
                        child.extract()
                    elif len(text) > 80:
                        child.replace_with(text[:80] + "…")

        def signature(node: Tag) -> tuple:
            return (node.name, tuple(sorted((node.attrs.get("class") or "").split())))

        for parent in soup.find_all(True):
            run: list = []
            for child in list(parent.children):
                if not isinstance(child, Tag):
                    continue
                if run and signature(child) == signature(run[0]):
                    run.append(child)
                    continue
                for extra in run[AIFallbackService.MAX_SIBLING_RUN:]:
                    extra.decompose()
                run = [child]
            for extra in run[AIFallbackService.MAX_SIBLING_RUN:]:
                extra.decompose()

        return str(soup)

    @staticmethod
    def _validated(html_content: str, definition: Optional[Dict[str, str]], type: str):
        """``definition`` only if it extracts real data from this page."""
        if not definition:
            return None
        from ..services import parser_generation_service as gen

        if type == "manga":
            return definition if gen._test_series_selectors(html_content, definition)["passed"] else None
        return definition if gen._test_chapter_selectors(html_content, definition)["passed"] else None

    @staticmethod
    def extract_selectors(html_content: str, type: str) -> Optional[Dict[str, str]]:
        """Selectors for this page, cheapest trustworthy source first:
        known parsers (presets, parsers approved for other domains -- this is
        what recognises a site on a new domain), structure detection, then
        the scraper AI. Each candidate is tested against ``html_content``
        before it is returned."""
        from ..core.db import SessionLocal
        from ..services import scraper_ai_service
        from . import autodetect, presets

        kind = "manga" if type == "manga" else "chapter"

        pool = presets.known_definitions()
        try:
            from ..models import ParserVersion

            with SessionLocal() as session:
                for version in session.query(ParserVersion).filter(ParserVersion.status == "active"):
                    if isinstance(version.definition, dict) and version.definition not in pool:
                        pool.append(version.definition)
        except Exception:  # the pool is an optimisation, never a requirement
            logger.warning("known_parser_pool_unavailable")

        for finder in (
            lambda: presets.detect_family(html_content, kind, pool),
            lambda: (
                autodetect.detect_series_definition(html_content)
                if kind == "manga"
                else autodetect.detect_reader_definition(html_content)
            ),
        ):
            found = AIFallbackService._validated(html_content, finder(), type)
            if found:
                return found

        if scraper_ai_service.get_config() is None:
            logger.info(
                "No scraper AI configured (Admin Panel -> Series -> Scraper AI API); "
                "no parser could be detected for this page."
            )
            return None

        selectors = scraper_ai_service.generate_selectors(html_content, type)
        found = AIFallbackService._validated(html_content, selectors, type)
        if found:
            return found
        logger.warning("Scraper AI produced no usable selectors for this page.")
        return None

    @staticmethod
    def _structural_heuristic(html_content: str, type: str) -> Optional[Dict[str, str]]:
        """Non-AI fallback: the first known CMS theme family (Madara,
        MangaStream, generic) whose selectors extract real data from this page.

        ``None`` when none of them do. Never a guess: BaseScraper validates the
        result and raises a typed failure otherwise (1G.9.4).
        """
        from ..scrapers.presets import detect_family

        return detect_family(html_content, "manga" if type == "manga" else "chapter")
