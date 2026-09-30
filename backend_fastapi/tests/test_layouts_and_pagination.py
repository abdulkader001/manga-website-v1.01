"""Series layouts: grouping one-page chapters, splitting book-format spreads
into vertical pages, and following chapters that span several HTML pages."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from backend_fastapi.app.scrapers import autodetect
from backend_fastapi.app.scrapers.base_scraper import BaseScraper
from backend_fastapi.app.services import chapter_grouping as cg
from backend_fastapi.app.services import page_image_service as pis
from backend_fastapi.app.services.scraper_workflow_service import ScraperWorkflowService


# ------------------------------------------------------------------ grouping
def _source(n: int):
    return [{"number": float(i), "url": f"https://s.example/ch-{i}", "title": f"Ch {i}"} for i in range(1, n + 1)]


def test_one_page_chapters_are_merged_in_full_groups_and_the_rest_is_held():
    rows = cg.build_chapter_rows(1, _source(12), group_size=5, consumed_urls=set(), flush=False)
    assert [r["chapter_title"] for r in rows] == ["Chapters 1-5", "Chapters 6-10"]
    assert [r["chapter_number"] for r in rows] == [1.0, 6.0]
    assert [m["number"] for m in rows[1]["group_urls"]] == [6.0, 7.0, 8.0, 9.0, 10.0]
    assert rows[0]["chapter_url"] == "https://s.example/ch-1"


def test_a_finished_series_publishes_its_shorter_last_group():
    rows = cg.build_chapter_rows(1, _source(12), group_size=5, consumed_urls=set(), flush=True)
    assert [r["chapter_title"] for r in rows] == ["Chapters 1-5", "Chapters 6-10", "Chapters 11-12"]


def test_new_source_chapters_continue_from_the_held_ones():
    stored = cg.build_chapter_rows(1, _source(12), group_size=5, consumed_urls=set(), flush=False)
    consumed = cg.known_source_urls(SimpleNamespace(**r) for r in [{**r, "group_urls": r["group_urls"]} for r in stored])
    assert "https://s.example/ch-7" in consumed and "https://s.example/ch-11" not in consumed
    more = cg.build_chapter_rows(1, _source(16), group_size=5, consumed_urls=consumed, flush=False)
    assert [r["chapter_title"] for r in more] == ["Chapters 11-15"]  # 16 waits for its group


def test_without_grouping_every_source_chapter_is_a_chapter():
    rows = cg.build_chapter_rows(1, _source(3), group_size=1, consumed_urls={"https://s.example/ch-2"}, flush=False)
    assert [r["chapter_number"] for r in rows] == [1.0, 3.0]
    assert all("group_urls" not in r for r in rows)


def test_grouped_members_follow_a_domain_change():
    chapter = SimpleNamespace(
        group_urls=[{"url": "https://old.example/1", "number": 1.0}, {"url": "https://old.example/2", "number": 2.0}]
    )
    assert cg.remap_members(chapter, {1.0: "https://new.example/1", 2.0: "https://new.example/2"})
    assert [m["url"] for m in chapter.group_urls] == ["https://new.example/1", "https://new.example/2"]


def test_layout_defaults_follow_the_series_type():
    assert cg.effective_layout(SimpleNamespace(scrape_layout=None, type="manga")) == {
        "group_size": 1, "spread_mode": "auto", "reading_direction": "rtl"}
    assert cg.effective_layout(SimpleNamespace(scrape_layout={"group_size": 10, "split_spreads": False}, type="manhwa")) == {
        "group_size": 10, "spread_mode": "never", "reading_direction": "ltr"}
    assert cg.normalize_layout({"group_size": 9999, "bogus": 1, "reading_direction": "up"}) == {"group_size": 50}


def test_a_grouped_chapter_scrapes_every_member_in_order_without_duplicates():
    pages = {
        "https://s.example/ch-1": ["a1", "a2"],
        "https://s.example/ch-2": ["b1"],
        "https://s.example/ch-3": ["b1", "c1"],
    }

    class FakeScraper:
        def scrape_chapter(self, url):
            return {"pages": list(pages[url])}

    chapter = SimpleNamespace(
        chapter_url="https://s.example/ch-1",
        group_urls=[{"url": u, "number": i} for i, u in enumerate(pages, 1)],
    )
    out = ScraperWorkflowService._scrape_chapter_pages(FakeScraper(), chapter)
    assert out["pages"] == ["a1", "a2", "b1", "c1"]


# ------------------------------------------------------------------ spreads
def _spread(gutter_at=None, size=(2400, 1700)) -> Image.Image:
    import random

    rng = random.Random(4)
    image = Image.new("RGB", size, (200, 30, 30))  # left page red
    draw = ImageDraw.Draw(image)
    draw.rectangle([size[0] // 2, 0, size[0], size[1]], fill=(30, 30, 200))  # right page blue
    for _ in range(1500):  # "artwork": every page column has texture, unlike a blank gutter
        x, y = rng.randint(0, size[0] - 40), rng.randint(0, size[1] - 10)
        draw.rectangle([x, y, x + rng.randint(10, 40), y + rng.randint(3, 10)], fill=(0, 0, 0))
    if gutter_at:
        draw.rectangle([gutter_at - 6, 0, gutter_at + 6, size[1]], fill="white")
    return image


def _dominant(piece: pis.EncodedPage) -> str:
    from PIL import ImageStat

    r, _, b = ImageStat.Stat(Image.open(io.BytesIO(piece.data)).convert("RGB")).mean
    return "red" if r > b else "blue"


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_a_book_format_spread_becomes_two_vertical_pages_in_reading_order():
    raw = _png(_spread())
    rtl = pis.compress_page(raw, {"spread_mode": "auto", "reading_direction": "rtl"})
    ltr = pis.compress_page(raw, {"spread_mode": "auto", "reading_direction": "ltr"})
    assert len(rtl) == len(ltr) == 2
    assert [_dominant(p) for p in rtl] == ["blue", "red"]  # right-hand page first
    assert [_dominant(p) for p in ltr] == ["red", "blue"]
    assert all(p.height > p.width for p in rtl)  # now portrait


def test_the_cut_follows_the_gutter_not_the_exact_centre():
    pieces = pis.compress_page(_png(_spread(gutter_at=1110)), {"spread_mode": "auto", "reading_direction": "ltr"})
    assert abs(pieces[0].width - 1110) <= 14


def test_single_pages_and_strips_are_never_split_and_splitting_can_be_off():
    portrait = _png(Image.new("RGB", (1200, 1800), "white"))
    assert len(pis.compress_page(portrait, {"spread_mode": "auto"})) == 1
    wide = _png(_spread())
    assert len(pis.compress_page(wide, {"spread_mode": "never"})) == 1
    assert len(pis.compress_page(wide)) == 1


# ------------------------------------------------------------------ pagination
CHAPTER = "https://s.example/ch/12"


def _scraper(monkeypatch, mapping, config):
    def fetch(self, url):
        html = mapping.get(url)
        return BeautifulSoup(html, "html.parser") if html is not None else None

    monkeypatch.setattr(BaseScraper, "_fetch_html", fetch)
    scraper = BaseScraper(domain="s.example")
    scraper.config = config
    return scraper


def _page(n: int, extra: str = "") -> str:
    return f'<div class="rd"><img class="pg" src="/img/{n}.jpg"></div>{extra}'


def test_a_page_dropdown_is_followed_in_numeric_order(monkeypatch):
    options = "".join(f'<option value="/ch/12/{n}">{n}</option>' for n in (3, 1, 2, 4))
    mapping = {CHAPTER: _page(1, f"<select>{options}</select>")}
    for n in (1, 2, 3, 4):
        mapping[f"https://s.example/ch/12/{n}"] = _page(n)
    scraper = _scraper(monkeypatch, mapping, {"page_images": "div.rd img.pg", "page_list": "select option"})
    pages = scraper.scrape_chapter(CHAPTER)["pages"]
    assert [p.rsplit("/", 1)[1] for p in pages] == ["1.jpg", "2.jpg", "3.jpg", "4.jpg"]


def test_numbered_urls_are_followed_until_a_page_has_nothing_new(monkeypatch):
    mapping = {CHAPTER: _page(1), f"{CHAPTER}?page=2": _page(2), f"{CHAPTER}?page=3": _page(3),
               f"{CHAPTER}?page=4": _page(3)}  # a site that repeats its last page
    scraper = _scraper(monkeypatch, mapping, {"page_images": "div.rd img.pg", "page_url_template": "{url}?page={n}"})
    pages = scraper.scrape_chapter(CHAPTER)["pages"]
    assert [p.rsplit("/", 1)[1] for p in pages] == ["1.jpg", "2.jpg", "3.jpg"]


def test_a_listed_page_that_cannot_be_fetched_fails_the_chapter_instead_of_dropping_it(monkeypatch):
    from backend_fastapi.app.scrapers.errors import ExtractionError

    options = "".join(f'<option value="/ch/12/{n}">{n}</option>' for n in (1, 2, 3))
    mapping = {CHAPTER: _page(1, f"<select>{options}</select>"),
               "https://s.example/ch/12/1": _page(1), "https://s.example/ch/12/3": _page(3)}  # page 2 is down
    scraper = _scraper(monkeypatch, mapping, {"page_images": "div.rd img.pg", "page_list": "select option"})
    with pytest.raises(ExtractionError):
        scraper.scrape_chapter(CHAPTER)


def test_pagination_guards_stop_a_site_that_loops(monkeypatch):
    mapping = {CHAPTER: _page(1, '<select><option value="/ch/12/2">2</option></select>'),
               "https://s.example/ch/12/2": _page(2, '<select><option value="/ch/12">1</option></select>')}
    scraper = _scraper(monkeypatch, mapping, {"page_images": "div.rd img.pg", "page_list": "select option"})
    assert len(scraper.scrape_chapter(CHAPTER)["pages"]) == 2


def test_numbered_page_links_of_the_same_chapter_are_detected():
    html = (
        '<div class="rd"><img class="pg" src="/img/1.jpg"></div>'
        '<div class="pager">' + "".join(f'<a href="/ch/12/{n}">{n}</a>' for n in (2, 3, 4)) + "</div>"
    )
    found = autodetect.detect_pagination(BeautifulSoup(html, "html.parser"), CHAPTER)
    assert found and "a" in found["page_list"]
    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select(found["page_list"])) == 3


def test_a_dropdown_of_other_chapters_is_not_mistaken_for_pages():
    html = "<select>" + "".join(f'<option value="/ch/{n}">{n}</option>' for n in (11, 12, 13)) + "</select>"
    assert autodetect.detect_pagination(BeautifulSoup(html, "html.parser"), CHAPTER) is None


@pytest.mark.parametrize(
    "first,second", [("/ch/12?page=2", "/ch/12?page=3"), ("/ch/12_2.html", "/ch/12_3.html"), ("/ch/12/2", "/ch/12/3")]
)
def test_common_page_url_shapes_are_recognised(first, second):
    html = f'<a href="{first}">2</a><a href="{second}">3</a>'
    assert autodetect.detect_pagination(BeautifulSoup(html, "html.parser"), CHAPTER)


def test_a_series_with_only_two_chapters_is_still_detected_but_two_nav_links_are_not():
    two = (
        "<h1>New Series</h1><ul>"
        '<li class="c"><a href="/m/x/chapter-2/">Chapter 2</a></li>'
        '<li class="c"><a href="/m/x/chapter-1/">Chapter 1</a></li></ul>'
    )
    assert autodetect.detect_series_definition(two, "https://s.example/m/x/")
    nav = '<h1>Site</h1><nav><a href="/top10">Top 10</a><a href="/new2">New 2</a></nav>'
    assert autodetect.detect_series_definition(nav, "https://s.example/") is None


# ------------------------------------------------------------------ manual source format
def test_declaring_a_source_format_fills_in_the_layout():
    assert cg.normalize_layout({"source_format": "vertical"}) == {"source_format": "vertical", "spread_mode": "never"}
    assert cg.normalize_layout({"source_format": "double"}) == {"source_format": "double", "spread_mode": "always"}
    assert cg.normalize_layout({"source_format": "single"}) == {"source_format": "single", "group_size": 10}
    # anything chosen explicitly beside it wins
    assert cg.normalize_layout({"source_format": "single", "group_size": 5})["group_size"] == 5
    assert cg.normalize_layout({"source_format": "double", "spread_mode": "auto"})["spread_mode"] == "auto"
    assert cg.normalize_layout({"source_format": "nonsense"}) == {}


def test_build_options_carries_the_manual_layout_to_the_job():
    from backend_fastapi.app.services.series_import import build_options

    payload = SimpleNamespace(
        type="manga", title=None, custom_description=None, author=None, custom_cover_image=None,
        mangaupdates_url=None, scrape_interval_value=None, scrape_interval_unit=None,
        auto_scrape_enabled=None, chapters_to_scrape=None, base_url=None,
        chapter_group_size=5, split_spreads=None, spread_mode=None, source_format="single", reading_direction="rtl",
    )
    assert build_options(payload)["layout"] == {
        "source_format": "single", "group_size": 5, "reading_direction": "rtl"}


def test_a_source_known_to_publish_two_pages_per_picture_is_always_split():
    square = _png(Image.new("RGB", (1000, 1000), "white"))  # not wide enough for auto
    assert len(pis.compress_page(square, {"spread_mode": "auto"})) == 1
    both = pis.compress_page(square, {"spread_mode": "always", "reading_direction": "ltr"})
    assert len(both) == 2 and sum(p.width for p in both) <= 1000 + 2


# ------------------------------------------------------------------ serial page order
def test_pages_named_by_number_are_put_in_serial_order():
    from backend_fastapi.app.scrapers import parsing

    shuffled = [f"https://c.example/x/{n:03d}.jpg" for n in (3, 1, 10, 2)]
    assert [u.rsplit("/", 1)[1] for u in parsing.order_pages(shuffled)] == ["001.jpg", "002.jpg", "003.jpg", "010.jpg"]
    assert parsing.order_pages([f"https://c.example/p-{n}.webp" for n in (2, 1)])[0].endswith("p-1.webp")


def test_page_order_is_left_alone_unless_it_is_unambiguous():
    from backend_fastapi.app.scrapers import parsing

    in_order = [f"https://c.example/x/{n}.jpg" for n in (1, 2, 3)]
    assert parsing.order_pages(in_order) == in_order
    hashed = ["https://c.example/x/9f2a.jpg", "https://c.example/x/13ab.jpg"]
    assert parsing.order_pages(hashed) == hashed
    mixed_folders = ["https://c.example/a/2.jpg", "https://c.example/b/1.jpg"]
    assert parsing.order_pages(mixed_folders) == mixed_folders
    repeated = ["https://c.example/x/2.jpg", "https://c.example/x/2.png", "https://c.example/x/1.jpg"]
    assert parsing.order_pages(repeated) == repeated


def test_the_scraper_returns_shuffled_numbered_images_in_serial_order(monkeypatch):
    html = '<div class="rd">' + "".join(f'<img class="pg" src="/img/{n}.jpg">' for n in (3, 1, 2)) + "</div>"
    scraper = _scraper(monkeypatch, {CHAPTER: html}, {"page_images": "div.rd img.pg"})
    assert [p.rsplit("/", 1)[1] for p in scraper.scrape_chapter(CHAPTER)["pages"]] == ["1.jpg", "2.jpg", "3.jpg"]


# ------------------------------------------------------------------ layout hint from a real sample
def _hint(monkeypatch, counts, total=12, image_size=None):
    from backend_fastapi.app.scrapers import source_pipeline

    chapters = [{"url": f"https://s.example/c{i}", "number": float(i)} for i in range(1, total + 1)]
    seq = iter(counts)

    class FakeScraper:
        def __init__(self, *_a, **_k): ...
        def scrape_chapter(self, _url):
            return {"pages": [f"https://c.example/{i}.jpg" for i in range(next(seq))]}

    monkeypatch.setattr("backend_fastapi.app.scrapers.base_scraper.BaseScraper", FakeScraper)
    if image_size:
        out = io.BytesIO()
        Image.new("RGB", image_size).save(out, "PNG")
        monkeypatch.setattr(pis, "_download", lambda *a, **k: out.getvalue())
    else:
        monkeypatch.setattr(pis, "_download", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    return source_pipeline.sample_layout("https://s.example/series", chapters, total)


def test_one_page_per_chapter_is_recognised_from_the_sample(monkeypatch):
    hint = _hint(monkeypatch, [1, 1, 1])
    assert hint["suggested_source_format"] == "single" and hint["suggested_group_size"] == 10


def test_a_few_pages_per_chapter_suggests_smaller_groups(monkeypatch):
    assert _hint(monkeypatch, [2, 3, 2])["suggested_group_size"] == 5


def test_normal_chapters_get_no_grouping_suggestion(monkeypatch):
    hint = _hint(monkeypatch, [24, 31, 18])
    assert hint["suggested_group_size"] is None and hint["suggested_source_format"] is None


def test_wide_first_pictures_are_recognised_as_book_format(monkeypatch):
    assert _hint(monkeypatch, [12, 14, 13], image_size=(2400, 1700))["suggested_source_format"] == "double"
