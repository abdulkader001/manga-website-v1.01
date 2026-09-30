"""Operator-supplied sample URLs for AI parser generation (SRS 1G.9.3).

When homepage auto-discovery cannot find a series page — a site whose URLs
don't match the usual ``/manga/`` hints — the honest-failure report asks the
Permanent Administrator for a real series page and real chapter pages. These
tests cover that the supplied samples are actually used, take precedence over
discovery, and still enforce the two-chapter-page rule.
"""
from __future__ import annotations

import pytest

from backend_fastapi.app.services import parser_generation_service as gen
from backend_fastapi.app.services import scraper_ai_service as ai

SERIES_HTML = (
    '<h1 class="entry-title">Hero</h1><div class="summary">x</div>'
    '<img class="cover" src="/c.jpg"/>'
    '<ul class="chapters">'
    '<li class="wp-manga-chapter"><a href="/x/hero/c1">1</a></li>'
    '<li class="wp-manga-chapter"><a href="/x/hero/c2">2</a></li>'
    "</ul>"
)
CHAPTER_HTML = (
    '<div class="reading-content">'
    '<img class="wp-manga-chapter-img" src="/p/1.jpg"/>'
    '<img class="wp-manga-chapter-img" src="/p/2.jpg"/>'
    "</div>"
)
SERIES_SELECTORS = {
    "manga_title": "h1.entry-title",
    "manga_description": "div.summary",
    "manga_cover": "img.cover",
    "chapter_list": "ul.chapters li.wp-manga-chapter",
    "chapter_url": "a",
    "chapter_title": "a",
    "chapter_number": "a",
}
CHAPTER_SELECTORS = {"page_images": "div.reading-content img.wp-manga-chapter-img"}

# A site whose URLs contain no recognizable series hint (/x/... not /manga/...).
ODD_PAGES = {
    "https://odd.example.com/x/hero": SERIES_HTML,
    "https://odd.example.com/x/hero/c1": CHAPTER_HTML,
    "https://odd.example.com/x/hero/c2": CHAPTER_HTML,
}


@pytest.fixture
def stub_generation(monkeypatch):
    monkeypatch.setattr(gen, "_fetch_html", lambda url: ODD_PAGES.get(url))
    monkeypatch.setattr(
        ai, "get_config", lambda: {"provider": "mock", "api_url": "http://m", "api_key": "k"}
    )
    monkeypatch.setattr(
        ai,
        "generate_selectors",
        lambda html, kind: dict(SERIES_SELECTORS) if kind == "manga" else dict(CHAPTER_SELECTORS),
    )


def test_auto_discovery_fails_honestly_on_odd_urls(stub_generation):
    result = gen.generate_and_test("odd.example.com", "https://odd.example.com/")
    assert result["possible"] is False
    assert result["failed_step"] in ("fetch_homepage", "discover_series_page")
    assert result["required_inputs"]  # honest report names what is needed


def test_generation_succeeds_with_sample_urls(stub_generation):
    result = gen.generate_and_test(
        "odd.example.com",
        "https://odd.example.com/",
        series_url="https://odd.example.com/x/hero",
        chapter_urls=[
            "https://odd.example.com/x/hero/c1",
            "https://odd.example.com/x/hero/c2",
        ],
    )
    assert result["possible"] is True
    assert result["test_results"]["listing_page"]["discovery"] == "operator_supplied"
    # Full definition: series + chapter selectors merged.
    assert "manga_title" in result["definition"]
    assert "page_images" in result["definition"]
    # Both supplied chapter pages were tested and passed.
    assert len(result["test_results"]["chapter_pages"]) == 2


def test_single_sample_chapter_still_requires_two(stub_generation):
    result = gen.generate_and_test(
        "odd.example.com",
        "https://odd.example.com/",
        series_url="https://odd.example.com/x/hero",
        chapter_urls=["https://odd.example.com/x/hero/c1"],
    )
    assert result["possible"] is False
    assert result["failed_step"] == "insufficient_chapter_pages"
