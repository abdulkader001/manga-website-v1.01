"""The owner's reference sites, checked against their saved homepages.

The owner saved the homepages of the sites the project should read
(``scrapers/reference/pages``). These tests keep the engine honest about
them: every page is still there, series discovery finds real series pages
(not list or category pages), each supported site gets its built-in parser
and each unsupported one says why, and the Scraper AI is given the site's
notes.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

from backend_fastapi.app.scrapers import ai_playbook, presets
from backend_fastapi.app.scrapers.reference import SITES, load_page, notes_for, site_for
from backend_fastapi.app.scrapers.reference.sites import all_pages
from backend_fastapi.app.services import parser_generation_service, scraper_ai_service


def _saved_url(html: str) -> str:
    return re.search(r"saved from (\S+) on", html).group(1)


@pytest.mark.parametrize("site,page", all_pages(), ids=[site.name for site, _ in all_pages()])
def test_homepage_discovery_finds_series_pages(site, page):
    html = load_page(page)
    url = _saved_url(html)
    links = parser_generation_service._find_series_links(url, html, limit=5)
    assert len(links) >= 3, links
    for link in links:
        assert re.search(site.series_url, link), (link, site.series_url)


def test_list_pages_lose_to_series_pages():
    # Pages whose first links point at list pages that share a series word.
    yueman = load_page("m.yueman1.cc.html.gz")
    assert all("/manhua/o/" not in link for link in parser_generation_service._find_series_links("http://m.yueman1.cc/", yueman))
    zymk = load_page("m.zymk.cn.html.gz")
    assert all("/book/" not in link for link in parser_generation_service._find_series_links("https://m.zymk.cn/", zymk))
    listing = load_page("m.manhuagui.com-list-lianzai.html.gz")
    links = parser_generation_service._find_series_links("https://m.manhuagui.com/list/lianzai/", listing)
    assert links and all(re.search(r"/comic/\d+/$", link) for link in links)


@pytest.mark.parametrize("site", SITES, ids=[site.name for site in SITES])
def test_each_site_has_its_parser_or_a_reason(site):
    host = site.hosts[0]
    if site.status == "supported":
        assert presets.preset_for_domain(host), host
        assert presets.unsupported_reason(host) is None
    elif site.status == "unsupported":
        assert presets.unsupported_reason(host), host
    else:
        assert site.status == "ai"
        assert presets.preset_for_domain(host) is None


def test_every_saved_page_is_present_and_readable():
    names = {site.page for site in SITES if site.page}
    assert len(names) == len(list(SITES))
    for name in names:
        html = load_page(name)
        assert "<title" in html
        assert urlparse(_saved_url(html)).hostname


def test_gigaviewer_pages_are_recognised_as_scrambled():
    html = load_page("www.sunday-webry.com.html.gz")
    assert any("GigaViewer" in line for line in ai_playbook.site_signals(html, "https://www.sunday-webry.com/"))


def test_site_lookup_follows_mobile_hosts_and_rotated_domains():
    assert site_for("m.manhuagui.com").name.startswith("ManHuaGui")
    assert site_for("wfwf777.com").name.startswith("Wolf.com")
    assert site_for("www.example.com") is None
    assert notes_for("www.example.com") == ""


def test_mkzhan_chapter_links_on_the_saved_page_fit_the_image_api():
    html = load_page("www.mkzhan.com.html.gz")
    chapter = re.search(r'href="(https://www\.mkzhan\.com/\d+/\d+/)"', html).group(1)
    pattern = presets.preset_for_domain("www.mkzhan.com")["image_api"]["params_regex"]
    match = re.search(pattern, chapter)
    assert match and match.group("comic_id") and match.group("chapter_id")


def test_the_ai_prompt_carries_the_site_notes_and_the_built_in_parser():
    html = "<html><body><h1>T</h1></body></html>"
    prompt = scraper_ai_service.build_prompt(html, "chapter", page_url="https://www.mkzhan.com/208645/1067202/")
    assert "WHAT WE ALREADY KNOW ABOUT THIS SITE" in prompt
    assert "comic.mkzhan.com/chapter/content/v1" in prompt
    assert "Built-in parser for this site" in prompt
    unknown = scraper_ai_service.build_prompt(html, "chapter", page_url="https://unknown.example/c/1")
    assert "WHAT WE ALREADY KNOW ABOUT THIS SITE" not in unknown
