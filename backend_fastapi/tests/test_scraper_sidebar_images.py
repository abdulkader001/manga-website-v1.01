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


def test_a_single_selector_keeps_every_page_but_not_site_chrome():
    # Since 2026-10-03 a single selector (admin or Scraper AI) also drops
    # pictures in nav/header/footer/aside; every page in the reader stays,
    # even one in a wrapper of its own.
    html = (
        '<div class="r"><img src="https://img.example/1.jpg"></div>'
        '<div class="r2"><img src="https://img.example/1b.jpg"></div>'
        '<aside><img src="https://img.example/2.jpg"></aside>'
    )
    config = {"page_images": "img"}
    images = _scraper(config, "site.example")._extract_page_images(
        _soup(html), "img", "https://site.example/ch/1.html", config
    )
    assert images == ["https://img.example/1.jpg", "https://img.example/1b.jpg"]


def test_structure_detection_prefers_the_sinmh_script_over_thumbnails():
    assert autodetect.detect_reader_definition(SINMH_READER) == {
        "image_source": {"decoder": "auto_script"}
    }


def test_a_single_selector_parser_also_drops_linked_sidebar_thumbnails():
    from backend_fastapi.app.scrapers.autodetect import drop_thumbnails
    from bs4 import BeautifulSoup

    html = (
        '<div class="reader">'
        + "".join(f'<div class="pg"><img src="https://img.example/p{n}.jpg"></div>' for n in range(1, 6))
        + '</div><div class="related">'
        + "".join(f'<a href="/manga/other-{n}"><img src="https://img.example/cover{n}.jpg"></a>' for n in range(3))
        + '</div><header><img src="https://img.example/logo.png"></header>'
        + '<div class="first"><img src="https://img.example/p0.jpg"></div>'
    )
    soup = BeautifulSoup(html, "html.parser")
    kept = drop_thumbnails(soup.select("img"), "https://site.example/c/1")
    urls = [t["src"] for t in kept]
    assert "https://img.example/p0.jpg" in urls  # a lone plain page in its own wrapper stays
    assert all("cover" not in u and "logo" not in u for u in urls)
    assert len(urls) == 6


# The owner's second report (2026-10-03, wujinmh.com chapter 561): the reader
# shows one page at a time ("1/25"), so the page holds ONE page picture while
# the "猜你喜欢" (you may like) box beside it holds many covers. The biggest
# group was the covers, and they were saved as the chapter. Fillers are now
# recognised by their box's heading or name, or by linking to another series.
GUESS_YOU_LIKE = """
<div class="box">
  <div class="title">猜你喜欢</div>
  <ul>
""" + "".join(
    f'<li><a href="/{500 + n}/"><img data-original="https://img.example/cover/{n}.jpg"></a></li>'
    for n in range(8)
) + """
  </ul>
</div>
"""

ONE_PAGE_READER = f"""
{GUESS_YOU_LIKE}
<div class="main"><div id="images"><img data-original="https://img.example/p/1.jpg"></div></div>
"""

CHAPTER_URL = "https://www.wujinmh.com/418992-225607.html"


def test_one_page_reader_keeps_its_page_not_the_guess_you_like_covers():
    config = presets.preset_for_domain("www.wujinmh.com")
    images = _scraper(config, "www.wujinmh.com")._extract_page_images(
        _soup(ONE_PAGE_READER), config["page_images"], CHAPTER_URL, config
    )
    assert images == ["https://img.example/p/1.jpg"]


def test_a_page_with_only_fillers_gives_no_pages_rather_than_covers():
    config = presets.preset_for_domain("www.wujinmh.com")
    images = _scraper(config, "www.wujinmh.com")._extract_page_images(
        _soup(GUESS_YOU_LIKE), config["page_images"], CHAPTER_URL, config
    )
    assert images == []


def test_fillers_are_recognised_in_several_languages_and_by_name():
    for heading in ("猜你喜欢", "相关推荐", "おすすめ", "추천 웹툰", "You may also like"):
        html = f'<div><h3>{heading}</h3><div><img src="https://img.example/c.jpg"></div></div>'
        tag = _soup(html).img
        assert autodetect.is_filler(tag, CHAPTER_URL), heading
    for name in ("guess-like", "recommend-list", "related", "rank-box"):
        tag = _soup(f'<div class="{name}"><img src="https://img.example/c.jpg"></div>').img
        assert autodetect.is_filler(tag, CHAPTER_URL), name


def test_pages_that_link_to_the_next_page_or_full_size_stay():
    html = (
        '<div id="images">'
        '<a href="/418992-225607-2.html"><img src="https://img.example/p/1.jpg"></a>'
        '<a href="/418992-225608.html"><img src="https://img.example/p/2.jpg"></a>'
        '<a href="https://img.example/full/3.jpg"><img src="https://img.example/p/3.jpg"></a>'
        "</div>"
    )
    for tag in _soup(html).select("img"):
        assert not autodetect.is_filler(tag, CHAPTER_URL), tag["src"]


def test_a_page_title_mentioning_popular_is_not_mistaken_for_a_filler_heading():
    html = '<div class="main"><h1>第五百六十一回</h1><div class="reader"><img src="https://img.example/p/1.jpg"></div></div>'
    assert not autodetect.is_filler(_soup(html).img, CHAPTER_URL)
