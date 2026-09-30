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
    @staticmethod
    def _simplify_dom(html_content: str) -> str:
        """Simplify DOM by removing scripts, styles, etc."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "svg", "path", "form"]):
            tag.decompose()
        return str(soup)

    @staticmethod
    def extract_selectors(html_content: str, type: str) -> Optional[Dict[str, str]]:
        from ..services import scraper_ai_service

        config = scraper_ai_service.get_config()
        if config is None:
            logger.info(
                "No scraper AI configured (Admin Panel -> API Management). "
                "Using structural fallback heuristic."
            )
            return AIFallbackService._structural_heuristic(html_content, type)

        simplified_html = AIFallbackService._simplify_dom(html_content)
        # Limit HTML size for context
        simplified_html = simplified_html[:15000]

        selectors = scraper_ai_service.generate_selectors(simplified_html, type)
        if selectors:
            return selectors
        logger.warning("Scraper AI produced no usable selectors; using heuristic.")
        return AIFallbackService._structural_heuristic(html_content, type)

    @staticmethod
    def _structural_heuristic(html_content: str, type: str) -> Dict[str, str]:
        """A heuristic fallback if AI fails or is not configured.

        These guesses are never trusted blindly: BaseScraper validates that
        they extract real data and raises a typed failure otherwise (1G.9.4).
        """
        if type == "manga":
            return {
                "manga_title": "h1",
                "manga_description": ".summary, .description, [itemprop='description']",
                "manga_cover": ".summary_image img, .cover img",
                "chapter_list": ".wp-manga-chapter, .chapter-list li",
                "chapter_url": "a",
                "chapter_title": "a",
                "chapter_number": "a",
            }
        else:
            return {"page_images": ".reading-content img, .page-break img"}
