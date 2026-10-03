"""What each reference site looks like (see ``__init__``).

Each ``Site`` is plain data. ``seen`` facts were read from the owner's saved
homepage (``pages/<page>``); ``known`` facts come from public scraper
projects and were not checked against a live page, so a parser built from
them must still pass the engine's tests on real pages.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

PAGES = Path(__file__).resolve().parent / "pages"


@dataclass(frozen=True)
class Site:
    name: str
    hosts: Tuple[str, ...]
    language: str
    # "supported": a built-in parser exists and should work;
    # "ai": no built-in parser, the Scraper AI writes one;
    # "unsupported": a deliberate access control stops plain HTTP reading.
    status: str
    family: str
    series_url: str  # regex a series page address matches
    chapter_url: Optional[str] = None  # regex a chapter address matches
    page: Optional[str] = None  # saved homepage, under pages/
    seen: Tuple[str, ...] = field(default_factory=tuple)
    known: Tuple[str, ...] = field(default_factory=tuple)
    obstacles: Tuple[str, ...] = field(default_factory=tuple)


_GIGAVIEWER = (
    "GigaViewer (Hatena) publisher site: episode pages /episode/<id>, pictures on "
    "cdn-scissors.gigaviewer.com or the site's own CDN.",
)
_GIGAVIEWER_STOP = (
    "Page pictures are cut into tiles and shuffled; the reader puts them back with a key. "
    "That is a deliberate access control: report it, do not work around it.",
)

SITES: Tuple[Site, ...] = (
    Site(
        name="ManHuaGui (看漫画)",
        hosts=("manhuagui.com", "www.manhuagui.com", "m.manhuagui.com", "tw.manhuagui.com"),
        language="zh",
        status="supported",
        family="manhuagui packed reader",
        series_url=r"/comic/\d+/?$",
        chapter_url=r"/comic/\d+/\d+\.html",
        page="m.manhuagui.com.html.gz",
        seen=(
            "Series pages are /comic/<id>/ (53 on the mobile homepage, 20 on /list/lianzai/).",
            "Covers are lazy-loaded: data-src on cf.mhgui.com (//cf.mhgui.com/cpic/m/<id>_65.jpg).",
            "List pages are /list/<filter>/, /rank/, /update/: not series.",
        ),
        known=(
            "Chapter pages carry the page list in a packed eval() whose data is LZString-compressed "
            "(SMH.imgData). The engine's 'manhuagui' decoder reads it.",
            "Pictures are on i.hamreus.com and need Referer https://www.manhuagui.com/.",
            "Adult series hide the chapter list LZString-compressed in input#__VIEWSTATE.",
        ),
        obstacles=("Bans IP addresses that read fast; keep the default pacing.",),
    ),
    Site(
        name="Baozi Manhua (包子漫畫)",
        hosts=("baozimh.com", "www.baozimh.com", "twmanga.com", "webmota.com"),
        language="zh",
        status="supported",
        family="AMP pages",
        series_url=r"/comic/[a-z0-9-]+/?$",
        chapter_url=r"/comic/chapter/[a-z0-9-]+/\d+_\d+(?:_\d+)?\.html|/user/page_direct\?",
        page="www.baozimh.com.html.gz",
        seen=(
            "AMP site: pictures are <amp-img>, not <img>.",
            "Series pages are /comic/<pinyin-slug>; the list page uses .comics-card a.comics-card__poster.",
            "Covers are on static-tw.baozimh.com.",
        ),
        known=(
            "Chapter links go through /user/page_direct?... and land on "
            "/comic/chapter/<slug>/0_<n>.html; long chapters continue on 0_<n>_2.html, _3...",
            "Page pictures are amp-img inside .comic-contain.",
        ),
    ),
    Site(
        name="Mankezhan (漫客栈)",
        hosts=("mkzhan.com", "www.mkzhan.com", "m.mkzhan.com"),
        language="zh",
        status="supported",
        family="JSON image API",
        series_url=r"mkzhan\.com/\d+/?$",
        chapter_url=r"mkzhan\.com/\d+/\d+(?:\.html|/)",
        page="www.mkzhan.com.html.gz",
        seen=(
            "Series pages are /<comic_id>/; chapter links are /<comic_id>/<chapter_id>/ (no .html).",
            "Covers are lazy-loaded: img.lazy with data-src on oss.mkzcdn.com.",
            "The page loads AliyunCaptcha.js: a CAPTCHA can appear when reading fast.",
            "Some links are Vue templates (href=\"/{{ item.comic_id }}/\"): ignore those.",
        ),
        known=(
            "Page pictures come from https://comic.mkzhan.com/chapter/content/v1/?chapter_id=<id>&comic_id=<id>"
            "&format=1&quality=1&type=1 (data.page[].image).",
            "Paid chapters answer with no pages; they are skipped, not worked around.",
        ),
        obstacles=("Aliyun CAPTCHA when rate limits are hit: slow down, never solve it.",),
    ),
    Site(
        name="Zhiyin Manke (知音漫客, m.zymk.cn)",
        hosts=("zymk.cn", "m.zymk.cn", "www.zymk.cn"),
        language="zh",
        status="supported",
        family="Vue app with server-rendered lists",
        series_url=r"zymk\.cn/\d+/?$",
        chapter_url=r"zymk\.cn/\d+/\d+\.html",
        page="m.zymk.cn.html.gz",
        seen=(
            "Series pages are /<id>/ (155 links on the homepage).",
            "/book/<n>.html and /sort/<n>.html are category tabs, not series.",
            "Covers are a CSS background on chapter-cover.yyhao.com; the <img> src is space.gif "
            "and data-id holds the series id.",
            "The site is a Vue app (entry.index.*.js).",
        ),
        known=(
            "Chapter pages are /<id>/<chapter_id>.html; the page list is built by a script "
            "(the engine's script decoders look for it).",
        ),
        obstacles=("The owner called this site 'jymk.cn'; the address is m.zymk.cn.",),
    ),
    Site(
        name="mh03 (漫画manga)",
        hosts=("mh03.com", "www.mh03.com", "m.mh03.com"),
        language="zh",
        status="supported",
        family="static HTML",
        series_url=r"/comic_[a-z0-9]+\.html$",
        page="www.mh03.com.html.gz",
        seen=(
            "Series pages are /comic_<pinyin>.html; cards are .comic-list .comic-item a.comic-cover.",
            "Covers are same-site .webp with loading=lazy (no data-src).",
            "/category/..., /custom/new, /custom/top are list pages.",
        ),
    ),
    Site(
        name="Yueman (漫画大全, m.yueman1.cc)",
        hosts=("yueman1.cc", "m.yueman1.cc", "www.yueman1.cc"),
        language="zh",
        status="supported",
        family="static HTML, GBK",
        series_url=r"/manhua/\d+\.html$",
        page="m.yueman1.cc.html.gz",
        seen=(
            "The page is GBK-encoded (declared in <meta>).",
            "Series pages are /manhua/<id>.html; /manhua/o/m_wap*.html are list pages.",
            "The reader script is m_reader.js.",
        ),
    ),
    Site(
        name="51 Manga (51漫画)",
        hosts=("51manga.com", "www.51manga.com", "m.51manga.com"),
        language="zh",
        status="supported",
        family="static HTML",
        series_url=r"/mh/[A-Za-z0-9]+/?$",
        page="www.51manga.com.html.gz",
        seen=(
            "Series pages are /mh/<short-id> (letters and digits).",
            "Pictures use jquery.lazyload.",
        ),
    ),
    Site(
        name="Wolf.com (늑대닷컴, wfwf<number>.com)",
        hosts=("wfwf510.com", "wfwf505.com"),
        language="ko",
        status="supported",
        family="static HTML, EUC-KR",
        series_url=r"/list\?toon=\d+",
        chapter_url=r"/view\?toon=\d+",
        page="wfwf510.com.html.gz",
        seen=(
            "The page is EUC-KR-encoded (declared in <meta>).",
            "Series pages are /list?toon=<id>; /ing?... pages are filtered lists.",
            "The domain number changes often (wfwf505, wfwf510...); any wfwf<number>.com gets the same parser.",
            "Ad banners link to unrelated sites.",
        ),
        known=("Chapter pages are /view?toon=<id>&num=<n>.",),
    ),
    Site(
        name="Rawkuma",
        hosts=("rawkuma.net", "rawkuma.com", "rawkuma.org"),
        language="ja",
        status="supported",
        family="WordPress, custom 'rawkuma' theme (Tailwind + htmx)",
        series_url=r"/manga/[^/]+/?$",
        chapter_url=r"/manga/[^/]+/chapter-[\d.]+/?$",
        page="rawkuma.net.html.gz",
        seen=(
            "Series pages are /manga/<slug>/; chapters are /manga/<slug>/chapter-<n>.<post-id>/.",
            "The theme is now 'rawkuma' (Tailwind classes, htmx), not the plain MangaStream theme "
            "the built-in parser was written for: if the built-in parser finds nothing, let the "
            "Scraper AI write a new one.",
            "Covers use srcset (the engine takes the largest).",
        ),
        known=("Older versions of the site used ts_reader.run({...}) on chapter pages.",),
    ),
    Site(
        name="Sen Manga (raw)",
        hosts=("raw.senmanga.com", "senmanga.com"),
        language="ja",
        status="supported",
        family="React Router app",
        series_url=r"senmanga\.com/[^/]+/?$",
        chapter_url=r"senmanga\.com/[^/]+/\d+(?:\.\d+)?/?$",
        page="raw.senmanga.com.html.gz",
        seen=(
            "Series pages are /<slug>; chapters are /<slug>/<number>.",
            "Built with React Router (links carry data-discover); covers are lazy-load spans.",
        ),
        known=("A chapter can show one page per address: /<slug>/<number>/<page>.",),
    ),
    Site(
        name="Mangaraw4u",
        hosts=("mangaraw4u.com", "www.mangaraw4u.com"),
        language="ja",
        status="ai",
        family="custom site with a JSON search API",
        series_url=r"/manga/[a-z0-9-]+/?$",
        page="mangaraw4u.com.html.gz",
        seen=(
            "Series pages are /manga/<slug>; homepage cards are a.popular-card with .card-image img.",
            "Some cards are drawn by a script template (href=\"/manga/'+m.slug+'\").",
            "The site has a JSON search endpoint /api/search?q=<text>.",
            "There is no built-in parser: the Scraper AI writes one from a series page.",
        ),
    ),
    Site(
        name="Manga Library Z (マンガ図書館Z)",
        hosts=("mangaz.com", "www.mangaz.com"),
        language="ja",
        status="supported",
        family="static HTML lists, script viewer",
        series_url=r"/series/detail/\d+",
        chapter_url=r"/book/detail/\d+",
        page="www.mangaz.com.html.gz",
        seen=(
            "Series pages are /series/detail/<id>; single volumes are /book/detail/<id>.",
            "Covers are lazy-loaded (lazysizes, data-src) on mangaz-books.j-comi.jp.",
            "The reader opens through open-viewer.js.",
        ),
        obstacles=(
            "If the viewer only delivers encrypted page data, report the site as unsupported.",
        ),
    ),
    Site(
        name="Tonari no Young Jump",
        hosts=("tonarinoyj.jp",),
        language="ja",
        status="unsupported",
        family="GigaViewer",
        series_url=r"/episode/\d+",
        page="tonarinoyj.jp.html.gz",
        seen=_GIGAVIEWER,
        obstacles=_GIGAVIEWER_STOP,
    ),
    Site(
        name="Comic DAYS",
        hosts=("comic-days.com",),
        language="ja",
        status="unsupported",
        family="GigaViewer",
        series_url=r"/episode/\d+",
        page="comic-days.com.html.gz",
        seen=_GIGAVIEWER,
        obstacles=_GIGAVIEWER_STOP,
    ),
    Site(
        name="Sunday Webry",
        hosts=("sunday-webry.com", "www.sunday-webry.com"),
        language="ja",
        status="unsupported",
        family="GigaViewer",
        series_url=r"/episode/\d+",
        page="www.sunday-webry.com.html.gz",
        seen=_GIGAVIEWER,
        obstacles=_GIGAVIEWER_STOP,
    ),
    Site(
        name="Shonen Jump+",
        hosts=("shonenjumpplus.com",),
        language="ja",
        status="unsupported",
        family="GigaViewer",
        series_url=r"/episode/\d+",
        page="shonenjumpplus.com.html.gz",
        seen=_GIGAVIEWER,
        obstacles=_GIGAVIEWER_STOP,
    ),
    Site(
        name="Magazine Pocket (マガポケ)",
        hosts=("pocket.shonenmagazine.com",),
        language="ja",
        status="unsupported",
        family="GigaViewer",
        series_url=r"/title/\d+/episode/\d+",
        page="pocket.shonenmagazine.com.html.gz",
        seen=(
            "Episode pages are /title/<id>/episode/<id>; the page loads reCAPTCHA.",
        ),
        obstacles=_GIGAVIEWER_STOP,
    ),
)


def site_for(host: str) -> Optional[Site]:
    """The reference entry for a host (``www.``/``m.`` and rotated wfwf
    numbers included), or None."""

    import re

    host = (host or "").strip().lower().split(":")[0]
    if re.fullmatch(r"(www\.|m\.)?wfwf\d+\.com", host):
        host = "wfwf510.com"
    for site in SITES:
        for known in site.hosts:
            if host == known or host.endswith("." + known):
                return site
    return None


def notes_for(host: str) -> str:
    """Plain-text notes for the Scraper AI's prompt ("" for unknown hosts)."""

    site = site_for(host)
    if site is None:
        return ""
    lines = [f"Site: {site.name} ({site.language}); family: {site.family}; status: {site.status}."]
    lines.append(f"Series page addresses match: {site.series_url}")
    if site.chapter_url:
        lines.append(f"Chapter addresses match: {site.chapter_url}")
    lines += [f"- seen on the site: {fact}" for fact in site.seen]
    lines += [f"- known from public scrapers (unverified): {fact}" for fact in site.known]
    lines += [f"- obstacle: {fact}" for fact in site.obstacles]
    return "\n".join(lines)


def load_page(name: str) -> str:
    """A saved reference page's HTML (UTF-8 text)."""

    return gzip.decompress((PAGES / name).read_bytes()).decode("utf-8")


def all_pages() -> List[Tuple[Site, str]]:
    return [(site, site.page) for site in SITES if site.page]
