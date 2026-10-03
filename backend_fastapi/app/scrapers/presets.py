"""Built-in parsers.

Two kinds:

* ``FAMILIES`` -- CMS themes shared by hundreds of manga sites (Madara,
  MangaStream). ``detect_family`` tries each against a fetched page and keeps
  the first that actually extracts a title and chapters, so an unknown
  WordPress-based site often works with no AI at all.
* ``SITE_PRESETS`` -- per-website parsers keyed by domain.

Selectors here come from public knowledge of each site's markup and could not
be checked against the live sites from the build environment; every scrape
validates its own result (a selector that extracts nothing is a typed
failure, never a silent success) and the admin's Preview shows exactly what
was found before anything is imported. When a site changes, the
scraper-generation AI (Admin -> Series -> Scraper AI) writes a replacement.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from . import parsing

Definition = Dict[str, Any]

MADARA: Definition = {
    "manga_title": ".post-title h1, .post-title h3, h1.entry-title",
    "manga_description": ".description-summary .summary__content, .summary__content, div[itemprop='description']",
    "manga_cover": ".summary_image img, .tab-summary img",
    "manga_author": ".author-content a",
    "manga_genres": ".genres-content a",
    "chapter_list": "li.wp-manga-chapter",
    "chapter_url": "a",
    "chapter_title": "a",
    "page_images": ".reading-content img, .page-break img",
    # Madara 1.6.5+ leaves the chapter list empty and loads it with
    # POST <series>/ajax/chapters/ (or admin-ajax.php on older installs).
    "chapter_ajax": {"kind": "madara"},
    "ajax_marker": "#manga-chapters-holder",
}

MANGASTREAM: Definition = {
    "manga_title": "h1.entry-title",
    "manga_description": ".entry-content[itemprop='description'], .entry-content-single, .desc",
    "manga_cover": ".thumb img, .infomanga img",
    "manga_genres": ".mgen a, .genxed a",
    "chapter_list": "#chapterlist li",
    "chapter_url": "a",
    "chapter_title": ".chapternum",
    "chapter_number": ".chapternum",
    # The reader page ships its images as JSON (ts_reader.run({...})); the
    # <img> tags inside #readerarea are added by JavaScript.
    "image_source": {"marker": "ts_reader.run(", "path": "sources.0.images"},
    "page_images": "#readerarea img",
}

# Manganato / Mangakakalot / Mangabuddy-style sites.
MANGABOX: Definition = {
    "manga_title": ".story-info-right h1, .manga-info-text h1, h1",
    "manga_description": "#panel-story-info-description, #noidungm, .summary-content",
    "manga_cover": ".info-image img, .manga-info-pic img, .story-info-left img",
    "manga_author": ".variations-tableInfo td.table-value a[href*='author'], .manga-info-text li a[href*='author']",
    "manga_genres": ".variations-tableInfo td.table-value a[href*='genre'], .manga-info-text li a[href*='genre']",
    "chapter_list": "ul.row-content-chapter li, .chapter-list .row",
    "chapter_url": "a",
    "chapter_title": "a",
    "page_images": ".container-chapter-reader img, #vungdoc img",
    "image_referer": "page",
}

GENERIC: Definition = {
    "manga_title": "h1, meta[property='og:title']",
    "manga_description": "[itemprop='description'], .summary, .description, meta[property='og:description']",
    "manga_cover": "meta[property='og:image'], .cover img, .thumb img",
    "chapter_list": "ul.chapters li, .chapter-list li, .chapters li, #chapters li",
    "chapter_url": "a",
    "chapter_title": "a",
    "page_images": "#readerarea img, .reading-content img, .chapter-content img, .reader img",
}

FAMILIES: List[Tuple[str, Definition]] = [
    ("madara", MADARA),
    ("mangastream", MANGASTREAM),
    ("mangabox", MANGABOX),
    ("generic", GENERIC),
]

SITE_PRESETS: Dict[str, Definition] = {}


def _register(domains: List[str], definition: Definition) -> None:
    for domain in domains:
        SITE_PRESETS[domain] = definition


_register(
    ["rawkuma.com", "rawkuma.net", "rawkuma.org"],
    {**MANGASTREAM, "headers": {"Accept-Language": "ja,en;q=0.8"}},
)

_register(
    ["baozimh.com", "www.baozimh.com", "twmanga.com", "www.twmanga.com", "webmota.com", "www.webmota.com"],
    {
        "manga_title": "h1.comics-detail__title",
        "manga_description": "p.comics-detail__desc",
        "manga_cover": ".comics-detail amp-img, .l-content amp-img",
        "manga_author": "h2.comics-detail__author",
        "manga_genres": ".tag-list .tag",
        "chapter_list": "#chapter-items a.comics-chapters__item, #chapters_other_list a.comics-chapters__item, .comics-chapters a.comics-chapters__item",
        "chapter_url": "a",
        "chapter_title": "span",
        "page_images": ".comic-contain amp-img, .comic-contain img",
        # Chapter links go through /user/page_direct?... which redirects to
        # /comic/chapter/<slug>/0_5.html; long chapters continue on
        # 0_5_2.html, 0_5_3.html ... (built from the redirected URL; a page
        # past the end redirects away and stops the walk).
        "page_url_template": "{stem}_{n}{ext}",
        "headers": {"Accept-Language": "zh-TW,zh;q=0.9"},
        "image_referer": "page",
    },
)

_register(
    ["comic.naver.com"],
    {
        "manga_title": "meta[property='og:title']",
        "manga_description": "meta[property='og:description']",
        "manga_cover": "meta[property='og:image']",
        # The episode list is served by a JSON API, 20 per page.
        "chapter_api": {
            "url": "https://comic.naver.com/api/article/list?titleId={series_id}&page=1",
            "path": "articleList",
            "fields": {"number": "no", "title": "subtitle"},
            "url_template": "https://comic.naver.com/webtoon/detail?titleId={series_id}&no={number}",
            "skip_if": {"field": "charge", "equals": True},
            "paginate": {"param": "page", "total_path": "pageInfo.totalPages"},
        },
        "series_id_regex": r"titleId=(\d+)",
        "page_images": ".wt_viewer img",
        "image_referer": "https://comic.naver.com/",
        "headers": {"Accept-Language": "ko,en;q=0.8"},
    },
)


# Ported from the v1.01 draft parsers. Static-HTML sites only; they are tried
# first for their domain and, like every parser, validated on each scrape.
_ZH = {"Accept-Language": "zh-CN,zh;q=0.9"}


def _static(
    chapters: str, images: str, *, attr: Optional[str] = None, headers: Optional[Dict[str, str]] = None
) -> Definition:
    definition: Definition = {
        "manga_title": "h1, meta[property='og:title']",
        "manga_description": "meta[property='og:description'], .intro, .summary, #intro",
        "manga_cover": "meta[property='og:image']",
        "chapter_list": chapters,
        "chapter_url": "a",
        "chapter_title": "a",
        "page_images": images,
        "image_referer": "page",
    }
    if attr:
        definition["image_attr"] = attr
    if headers:
        definition["headers"] = headers
    return definition


# Reader pages on these sites usually carry no <img> for the pages: the list
# sits in a script (SinMH ``chapterImages``, qTcms base64, packed eval). The
# engine reads those automatically when the selector finds nothing.
_register(["wujinmh.com", "www.wujinmh.com", "m.wujinmh.com"], _static("#chapter-list a, .chapter-list a, #chapter-list-1 a", "img[data-original], #cp_img img, #images img", attr="data-original", headers=_ZH))
_register(["m.yueman1.cc", "yueman1.cc", "www.yueman1.cc"], _static(".chapter-list a, #chlist a, .list_chapter a, #mh-chapter-list-ol-0 a", ".reader-img-box img, #cp_img img, .comicpage img", attr="data-src", headers=_ZH))
_register(
    ["mkzhan.com", "www.mkzhan.com", "m.mkzhan.com"],
    {
        **_static(".chapter__list a, #chapter-list a, a.j-chapter-link", "img.lazy-read, .rd-article__pic img", attr="data-src", headers=_ZH),
        # The reader builds its pages from a JSON API keyed by the ids in
        # the chapter URL: /<comic_id>/<chapter_id>/ on the 2026 site (seen
        # in the owner's saved homepage), /<comic_id>/<chapter_id>.html before.
        "image_api": {
            "url": "https://comic.mkzhan.com/chapter/content/v1/?chapter_id={chapter_id}&comic_id={comic_id}&format=1&quality=1&type=1",
            "params_regex": r"/(?P<comic_id>\d+)/(?P<chapter_id>\d+)(?:\.html|/|$)",
            "path": "data.page",
            "field": "image",
        },
    },
)
# Sen Manga shows one page per URL (/<series>/<chapter>/<page>); on chapters
# that show everything at once, page 2 adds nothing new and the walk stops.
_register(
    ["raw.senmanga.com", "senmanga.com"],
    {**_static(".element a, ul.chapter-list a, .list .series a", "img.picture, .reader img"), "page_url_template": "{url}/{n}"},
)
_register(["mangaz.com", "www.mangaz.com"], _static(".chapter-list a, #ch-list a", "#viewer img"))


# manhuagui: chapter images sit in a packed + LZString-compressed script.
_register(
    ["manhuagui.com", "www.manhuagui.com", "m.manhuagui.com", "tw.manhuagui.com"],
    {
        "manga_title": ".book-title h1, .main-bar h1, h1",
        "manga_description": "#intro-all, #intro-cut, .book-intro, meta[property='og:description']",
        "manga_cover": ".book-cover img, .thumb img, meta[property='og:image']",
        "manga_author": ".detail-list a[href*='/author/']",
        "manga_genres": ".detail-list a[href*='/list/']",
        "chapter_list": "#chapterList a, .chapter-list a",
        # Age-gated series keep the list LZString-compressed in a hidden field.
        "hidden_chapter_list": "#__VIEWSTATE",
        "chapter_url": "a",
        "chapter_title": "a",
        "image_source": {"decoder": "manhuagui", "host": "https://i.hamreus.com"},
        "page_images": "#mangaFile",
        "image_referer": "https://www.manhuagui.com/",
        "headers": _ZH,
    },
)

# Chinese / Korean aggregator sites with plain HTML chapter lists and
# hotlink-protected, lazy-loaded page images. Selectors are the union of the
# class names these templates commonly use; the pipeline validates them and
# falls back to structure detection, then the AI, when a site differs.
_COMMON_CHAPTERS = (
    ".chapter-list a, #chapter-list a, .comic-chapters a, ul.list-chapter a, "
    ".catalog-list a, #chapterList a, .chapterlist a, .chapters a, .comic-chapter a"
)
_COMMON_IMAGES = (
    "img.lazy, #cp_img img, .comic-contain img, .reader-img img, .chapter-content img, "
    ".read-content img, #images img, .view_img img, .comicpage img, .mh_comicpic img"
)
_register(
    ["51manga.com", "www.51manga.com", "m.51manga.com"],
    _static(_COMMON_CHAPTERS, _COMMON_IMAGES, headers=_ZH),
)
_register(["m.zymk.cn", "zymk.cn", "www.zymk.cn"], _static(_COMMON_CHAPTERS, _COMMON_IMAGES, headers=_ZH))
_register(["mh03.com", "www.mh03.com", "m.mh03.com"], _static(_COMMON_CHAPTERS, _COMMON_IMAGES, headers=_ZH))
_register(
    ["mh160mh.com", "www.mh160mh.com", "m.mh160mh.com"], _static(_COMMON_CHAPTERS, _COMMON_IMAGES, headers=_ZH)
)
_KO = {"Accept-Language": "ko,en;q=0.8"}
_register(["wfwf505.com", "www.wfwf505.com"], _static(_COMMON_CHAPTERS + ", .chapter_list a, #chapter_list a", _COMMON_IMAGES, headers=_KO))

# Sites that keep the same software but rotate their domain name. A page on any
# matching host gets that site's parser, so a rename needs no admin action.
DOMAIN_PATTERNS: List[Tuple[str, List[str]]] = [
    (r"^(www\.|m\.)?wfwf\d+\.com$", ["wfwf505.com"]),
    (r"^(www\.|m\.)?rawkuma\.[a-z]+$", ["rawkuma.com"]),
    (r"^(www\.|m\.)?baozimh\.[a-z]+$", ["baozimh.com"]),
    (r"^(www\.|m\.|tw\.)?manhuagui\.[a-z]+$", ["manhuagui.com"]),
    (r"^(www\.|m\.)?mh\d+(mh)?\.(com|net|cc)$", ["mh03.com"]),
]

# comic.naver.com is the webtoon site; naver.com is only the portal.
_register(["m.comic.naver.com"], SITE_PRESETS["comic.naver.com"])

# Sites that cannot be read by fetching HTML. Reported honestly instead of
# producing empty imports.
UNSUPPORTED_SITES: Dict[str, str] = {
    "tonarinoyj.jp": "serves scrambled page images through the GigaViewer reader",
    "comic-days.com": "serves scrambled page images through the GigaViewer reader",
    "sunday-webry.com": "serves scrambled page images through the GigaViewer reader",
    "pocket.shonenmagazine.com": "serves scrambled page images through the GigaViewer reader",
    "shonenjumpplus.com": "serves scrambled page images through the GigaViewer reader",
    "comic-walker.com": "delivers pages through an encrypted viewer API",
    "kuaikanmanhua.com": "requires a signed mobile-app API",
}

# Addresses that are not a manga site themselves but point to one.
WRONG_HOSTS: Dict[str, str] = {
    "naver.com": (
        "naver.com is Naver's portal, not its webtoon site. Use a series page on "
        "comic.naver.com, for example https://comic.naver.com/webtoon/list?titleId=123456"
    ),
    "www.naver.com": (
        "naver.com is Naver's portal, not its webtoon site. Use a series page on "
        "comic.naver.com, for example https://comic.naver.com/webtoon/list?titleId=123456"
    ),
    "m.naver.com": (
        "naver.com is Naver's portal, not its webtoon site. Use a series page on "
        "comic.naver.com, for example https://comic.naver.com/webtoon/list?titleId=123456"
    ),
}


def unsupported_reason(domain: str) -> Optional[str]:
    host = (domain or "").strip().lower().split(":")[0]
    for known, reason in UNSUPPORTED_SITES.items():
        if host == known or host.endswith("." + known):
            return reason
    return None


def wrong_host_hint(domain: str) -> Optional[str]:
    host = (domain or "").strip().lower().split(":")[0]
    return WRONG_HOSTS.get(host)


def known_definitions() -> List[Definition]:
    """Every distinct built-in definition (site presets, then CMS families).

    Used to recognise a site that moved to a new domain: its page is tried
    against each of these and the first that extracts real data wins.
    """

    seen: List[Definition] = []
    for definition in list(SITE_PRESETS.values()) + [d for _, d in FAMILIES]:
        if definition not in seen:
            seen.append(definition)
    return seen


def preset_for_domain(domain: str) -> Optional[Definition]:
    host = (domain or "").strip().lower().split(":")[0]
    if not host:
        return None
    if host in SITE_PRESETS:
        return dict(SITE_PRESETS[host])
    for known, definition in SITE_PRESETS.items():
        bare = known[4:] if known.startswith("www.") else known
        if host == bare or host.endswith("." + bare):
            return dict(definition)
    for pattern, templates in DOMAIN_PATTERNS:
        if re.match(pattern, host) and templates[0] in SITE_PRESETS:
            return dict(SITE_PRESETS[templates[0]])
    return None


def detect_family(
    html: str, kind: str, pool: Optional[List[Definition]] = None
) -> Optional[Definition]:
    """First known definition whose selectors extract real data from ``html``.

    ``pool`` defaults to the CMS families; pass ``known_definitions()`` plus any
    stored parsers to also recognise a known site on a new domain.

    ``kind`` is ``"manga"`` (series page: title + at least one chapter link)
    or ``"chapter"`` (reader page: at least one page image).
    """

    soup = BeautifulSoup(html or "", "html.parser")
    candidates = pool if pool is not None else [d for _, d in FAMILIES]
    for definition in candidates:
        if kind == "manga":
            title = parsing.select_one(soup, definition.get("manga_title"))
            items = parsing.select(soup, definition.get("chapter_list"))
            has_link = any(
                (item.name == "a" and item.get("href")) or item.select_one("a[href]")
                for item in items[:5]
            )
            # A theme that loads its chapter list by AJAX is recognised by
            # its empty list container; the scrape then fetches the list.
            loads_later = bool(definition.get("chapter_ajax")) and parsing.select_one(
                soup, definition.get("ajax_marker")
            ) is not None
            if title is not None and parsing.text_of(title) and (has_link or loads_later):
                return dict(definition)
        else:
            source = definition.get("image_source")
            if isinstance(source, dict) and source.get("decoder"):
                from . import packed_scripts, script_images

                if source["decoder"] == "manhuagui":
                    found = packed_scripts.manhuagui_images(soup)
                else:
                    found = script_images.decode(source["decoder"], soup, "https://example.invalid/")
                if found:
                    return dict(definition)
            elif isinstance(source, dict):
                data = parsing.json_from_scripts(
                    soup,
                    script_selector=source.get("script_selector"),
                    marker=source.get("marker"),
                )
                if parsing.dig(data, source.get("path")):
                    return dict(definition)
            if any(
                parsing.image_url(tag, "https://example.invalid/")
                for tag in parsing.select(soup, definition.get("page_images"))
            ):
                return dict(definition)
    return None
