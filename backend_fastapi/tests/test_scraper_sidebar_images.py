"""Reader pages whose sidebar thumbnails look like page images.

The owner's report: importing a wujinmh.com series stored the sidebar's
"related series" pictures instead of the chapter's pages. SinMH sites (and
many Chinese/Korean aggregators) keep the real page list in a script and show
lazy-loaded thumbnails of other series with the same ``data-original``
attribute the page selector looks for.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from backend_fastapi.app.scrapers import autodetect, presets
from backend_fastapi.app.scrapers.base_scraper import BaseScraper

SIDEBAR = """
<div class="sidebar-hot"><ul>
  <li><a href="/comic/1/"><img class="lazy" data-original="https://img.example/cover/1.jpg"></a></li>
  <li><a href="/comic/2/"><img class="lazy" data-original="https://img.example/cover/2.jpg"></a></li>
  <li><a href="/comic/3/"><img class="lazy" data-original="https://img.example/cover/3.jpg"></a></li>
</ul></div>
"""

SINMH_READER = f"""
<div id="images"></div>
{SIDEBAR}
<script>;var chapterImages = ["001.jpg","002.jpg"];var chapterPath = "images/comic/9/77/";</script>
<script>var SinConf = {{"resHost":[{{"domain":["https://res.example"]}}]}};</script>
"""


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _scraper(config: dict, domain: str) -> BaseScraper:
    scraper = BaseScraper.__new__(BaseScraper)
    scraper.domain = domain
    scraper.config = config
    return scraper


def test_wujinmh_reads_the_script_page_list_not_the_sidebar():
    config = presets.preset_for_domain("www.wujinmh.com")
    scraper = _scraper(config, "www.wujinmh.com")
    images = scraper._extract_page_images(
        _soup(SINMH_READER), config["page_images"], "https://www.wujinmh.com/comic/9/77.html", config
    )
    assert images == [
        "https://res.example/images/comic/9/77/001.jpg",
        "https://res.example/images/comic/9/77/002.jpg",
    ]


def test_union_selector_keeps_the_reader_group_and_drops_sidebar_thumbnails():
    html = f"""
    <div id="cp_img">
      <img data-original="https://img.example/p/1.jpg">
      <img data-original="https://img.example/p/2.jpg">
      <img data-original="https://img.example/p/3.jpg">
      <img data-original="https://img.example/p/4.jpg">
    </div>
    {SIDEBAR}
    """
    selector = "img[data-original], #cp_img img"
    config = {"page_images": selector, "image_attr": "data-original"}
    images = _scraper(config, "site.example")._extract_page_images(
        _soup(html), selector, "https://site.example/ch/1.html", config
    )
    assert images == [f"https://img.example/p/{n}.jpg" for n in range(1, 5)]


def test_union_selector_drops_header_and_footer_pictures():
    html = """
    <header><img class="lazy" src="https://img.example/top.jpg"></header>
    <div class="comicpage"><img class="lazy" src="https://img.example/p/1.jpg"><img class="lazy" src="https://img.example/p/2.jpg"></div>
    <footer><img class="lazy" src="https://img.example/qr.jpg"></footer>
    """
    selector = "img.lazy, .comicpage img"
    images = _scraper({"page_images": selector}, "site.example")._extract_page_images(
        _soup(html), selector, "https://site.example/ch/1.html", {"page_images": selector}
    )
    assert images == ["https://img.example/p/1.jpg", "https://img.example/p/2.jpg"]


def test_a_single_selector_is_used_as_written():
    html = '<div class="r"><img src="https://img.example/1.jpg"></div><aside><img src="https://img.example/2.jpg"></aside>'
    config = {"page_images": "img"}
    images = _scraper(config, "site.example")._extract_page_images(
        _soup(html), "img", "https://site.example/ch/1.html", config
    )
    assert images == ["https://img.example/1.jpg", "https://img.example/2.jpg"]


def test_structure_detection_prefers_the_sinmh_script_over_thumbnails():
    assert autodetect.detect_reader_definition(SINMH_READER) == {
        "image_source": {"decoder": "auto_script"}
    }
