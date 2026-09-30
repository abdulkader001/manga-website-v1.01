"""Within-chapter pagination for BaseScraper.scrape_chapter.

Covers the two real-world chapter layouts and the guardrails:
  * single-URL chapter (all page images on one page) — unchanged behavior
  * multi-URL chapter (pages split across "next page" links) — followed in full
  * looping pagination — stopped by the visited-URL cycle guard
  * runaway pagination — stopped by MAX_PAGES_PER_CHAPTER
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from backend_fastapi.app.scrapers.base_scraper import (
    MAX_PAGES_PER_CHAPTER,
    BaseScraper,
)

CONFIG = {"page_images": "div.reader img.page", "next_page": "a.next"}


def _fetcher(mapping):
    """Return a _fetch_html stand-in that serves fixture HTML by URL."""

    def _fetch(self, url):  # noqa: ANN001
        html = mapping.get(url)
        return BeautifulSoup(html, "html.parser") if html is not None else None

    return _fetch


def _scraper(monkeypatch, mapping):
    monkeypatch.setattr(BaseScraper, "_fetch_html", _fetcher(mapping))
    sc = BaseScraper(domain="s.example.com")
    sc.config = CONFIG
    return sc


def test_single_url_chapter_unchanged(monkeypatch):
    html = (
        '<div class="reader">'
        '<img class="page" src="https://cdn/p/1.jpg"/>'
        '<img class="page" src="https://cdn/p/2.jpg"/>'
        '<img class="page" src="https://cdn/p/3.jpg"/>'
        "</div>"
    )
    sc = _scraper(monkeypatch, {"https://s.example.com/ch": html})
    result = sc.scrape_chapter("https://s.example.com/ch")
    assert len(result["pages"]) == 3
    assert result["pages"][0].endswith("/p/1.jpg")


def test_multi_url_chapter_followed_in_full(monkeypatch):
    mapping = {
        "https://s.example.com/ch": (
            '<div class="reader"><img class="page" src="/p/1.jpg"/>'
            '<img class="page" src="/p/2.jpg"/></div>'
            '<a class="next" href="/ch?p=2">Next</a>'
        ),
        "https://s.example.com/ch?p=2": (
            '<div class="reader"><img class="page" src="/p/3.jpg"/>'
            '<img class="page" src="/p/4.jpg"/></div>'
            '<a class="next" href="/ch?p=3">Next</a>'
        ),
        "https://s.example.com/ch?p=3": (
            '<div class="reader"><img class="page" src="/p/5.jpg"/>'
            '<img class="page" src="/p/6.jpg"/></div>'
        ),
    }
    sc = _scraper(monkeypatch, mapping)
    result = sc.scrape_chapter("https://s.example.com/ch")
    pages = result["pages"]
    assert len(pages) == 6
    # order preserved across pages; relative URLs resolved to absolute
    assert pages[0] == "https://s.example.com/p/1.jpg"
    assert pages[5] == "https://s.example.com/p/6.jpg"
    assert len(set(pages)) == 6  # no duplicates


def test_pagination_cycle_is_broken(monkeypatch):
    mapping = {
        "https://s.example.com/a": (
            '<div class="reader"><img class="page" src="/a.jpg"/></div>'
            '<a class="next" href="/b">Next</a>'
        ),
        "https://s.example.com/b": (
            '<div class="reader"><img class="page" src="/b.jpg"/></div>'
            '<a class="next" href="/a">Next</a>'  # points back -> cycle
        ),
    }
    sc = _scraper(monkeypatch, mapping)
    result = sc.scrape_chapter("https://s.example.com/a")
    assert len(result["pages"]) == 2  # visited-URL guard stops the loop


def test_runaway_pagination_capped(monkeypatch):
    # Every page links to a brand-new URL forever; only the page cap stops it.
    class InfiniteMap(dict):
        def get(self, url, default=None):  # noqa: ANN001
            n = int(url.rsplit("=", 1)[-1]) if "=" in url else 0
            return (
                f'<div class="reader"><img class="page" src="/p/{n}.jpg"/></div>'
                f'<a class="next" href="/ch?p={n + 1}">Next</a>'
            )

    monkeypatch.setattr(BaseScraper, "_fetch_html", _fetcher(InfiniteMap()))
    sc = BaseScraper(domain="s.example.com")
    sc.config = CONFIG
    result = sc.scrape_chapter("https://s.example.com/ch?p=0")
    assert len(result["pages"]) <= MAX_PAGES_PER_CHAPTER
