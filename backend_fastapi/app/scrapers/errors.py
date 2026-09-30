"""Typed scraper errors (SRS 1G.5.4 / 1G.7.4).

A scraper module returns a typed error, never an anonymous exception. The
structured detail — which field could not be extracted, from which URL, with
which selector, by which module — is what turns "scraping failed" into
something an engineer can act on immediately, and what feeds the
structure-change detector (1G.7.8).
"""

from __future__ import annotations

from typing import Optional

from .base_scraper import ScraperError


class ExtractionError(ScraperError):
    """Extraction failed at a specific step of a specific page.

    Subclasses ``ScraperError`` so every existing containment boundary that
    catches the base class also contains the typed form.
    """

    def __init__(
        self,
        message: str,
        *,
        url: Optional[str] = None,
        missing_field: Optional[str] = None,
        selector_used: Optional[str] = None,
        scraper_module: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.url = url
        self.missing_field = missing_field
        self.selector_used = selector_used
        self.scraper_module = scraper_module

    def to_details(self) -> dict:
        """The 1G.5.4 details payload."""

        return {
            "url": self.url,
            "missing_field": self.missing_field,
            "selector_used": self.selector_used,
            "scraper_module": self.scraper_module,
        }


def error_details_for(exc: Exception, *, url: Optional[str] = None) -> dict:
    """Structured detail for any scraper failure, typed or not (1G.5.3)."""

    if isinstance(exc, ExtractionError):
        details = exc.to_details()
        if details.get("url") is None:
            details["url"] = url
        details["message"] = exc.message
        return details
    return {
        "url": url,
        "missing_field": None,
        "selector_used": None,
        "scraper_module": None,
        "message": str(exc),
    }
