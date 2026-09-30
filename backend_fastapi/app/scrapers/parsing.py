"""Extraction helpers shared by the scraper, parser tests and presets.

Every function is pure (HTML/strings in, values out) so parser behaviour can
be tested against saved pages without the network.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

# Attributes lazy-loading libraries use for the real image URL, most specific
# first. ``src`` is last because lazy loaders put a placeholder there.
IMAGE_ATTRS = (
    "data-src",
    "data-original",
    "data-lazy-src",
    "data-lazy",
    "data-url",
    "data-echo",
    "data-cfsrc",
    "data-image",
    "src",
)
SRCSET_ATTRS = ("data-srcset", "srcset")

_PLACEHOLDER_RE = re.compile(
    r"(loading|lazy|placeholder|blank|spacer|pixel|1x1|grey|gray)\.(gif|png|svg|jpg)",
    re.I,
)

_CJK_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CJK_UNITS = {"十": 10, "百": 100, "千": 1000}

# Ordered: explicit chapter markers beat bare numbers (so "Vol.2 Ch.15" is
# chapter 15, not 2).
_NUMBER_PATTERNS = [
    re.compile(r"(?:chapter|chap|ch|episode|ep|capitulo|capítulo|chapitre|kapitel)\s*[.#:：-]?\s*(\d+(?:\.\d+)?)", re.I),
    re.compile(r"第\s*(\d+(?:\.\d+)?)\s*[话話回章集卷]"),
    re.compile(r"(\d+(?:\.\d+)?)\s*[화話话回]"),
    re.compile(r"#\s*(\d+(?:\.\d+)?)"),
]
_URL_NUMBER_PATTERNS = [
    re.compile(r"(?:chapter|chap|ch|episode|ep)[-_/]?(\d+(?:[._-]\d+)?)", re.I),
    re.compile(r"[?&](?:no|ep|episode|chapter|chapter_slot)=(\d+)", re.I),
    re.compile(r"/(\d+(?:[._]\d+)?)/?(?:\.html?)?$"),
]
_VOLUME_RE = re.compile(r"\b(?:vol(?:ume)?|v)\s*\.?\s*\d+", re.I)


def _cjk_to_int(text: str) -> Optional[int]:
    if not text or any(ch not in _CJK_DIGITS and ch not in _CJK_UNITS for ch in text):
        return None
    total, current = 0, 0
    for ch in text:
        if ch in _CJK_DIGITS:
            current = _CJK_DIGITS[ch]
        else:
            unit = _CJK_UNITS[ch]
            total += (current or 1) * unit
            current = 0
    return total + current


def parse_chapter_number(*candidates: Optional[str]) -> Optional[float]:
    """Best chapter number found in the given strings (link text, title,
    URL...), or ``None``. Never returns a volume number."""

    for raw in candidates:
        if not raw:
            continue
        text = " ".join(str(raw).split())
        for pattern in _NUMBER_PATTERNS:
            match = pattern.search(text)
            if match:
                return float(match.group(1))
        cjk = re.search(r"第\s*([零〇一二两兩三四五六七八九十百千]+)\s*[话話回章集]", text)
        if cjk:
            value = _cjk_to_int(cjk.group(1))
            if value is not None:
                return float(value)
        stripped = _VOLUME_RE.sub(" ", text)
        bare = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", stripped)
        if bare:
            return float(bare.group(1))
        numbers = re.findall(r"\d+(?:\.\d+)?", stripped)
        if len(numbers) == 1:
            return float(numbers[0])
    return None


def chapter_number_from_url(url: Optional[str]) -> Optional[float]:
    if not url:
        return None
    for pattern in _URL_NUMBER_PATTERNS:
        match = pattern.search(url)
        if match:
            value = re.sub(r"[_-]", ".", match.group(1))
            try:
                return float(value)
            except ValueError:
                continue
    return None


def absolute(base_url: str, href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("javascript:", "data:", "mailto:", "#")):
        return None
    url = urljoin(base_url, href)
    return url if urlparse(url).scheme in {"http", "https"} else None


def _largest_from_srcset(value: str) -> Optional[str]:
    best, best_size = None, -1.0
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        size = 0.0
        if len(bits) > 1:
            try:
                size = float(bits[1].rstrip("wx"))
            except ValueError:
                size = 0.0
        if size >= best_size:
            best, best_size = bits[0], size
    return best


def image_url(tag: Tag, base_url: str, preferred_attr: Optional[str] = None) -> Optional[str]:
    """The real image URL of an ``<img>``/``<amp-img>``/``<source>`` tag."""

    attrs = ((preferred_attr,) if preferred_attr else ()) + IMAGE_ATTRS
    for attr in attrs:
        value = tag.get(attr)
        if isinstance(value, list):
            value = " ".join(value)
        if not value:
            continue
        value = value.strip()
        if value.startswith("data:") or _PLACEHOLDER_RE.search(value):
            continue
        url = absolute(base_url, value)
        if url:
            return url
    for attr in SRCSET_ATTRS:
        value = tag.get(attr)
        if value:
            candidate = _largest_from_srcset(str(value))
            url = absolute(base_url, candidate)
            if url:
                return url
    return None


def select(soup: BeautifulSoup | Tag, selector: Optional[str]) -> List[Tag]:
    if not selector or not selector.strip():
        return []
    try:
        return soup.select(selector)
    except Exception:  # invalid selector from a bad config/AI answer
        return []


def select_one(soup: BeautifulSoup | Tag, selector: Optional[str]) -> Optional[Tag]:
    if not selector or not selector.strip():
        return None
    try:
        return soup.select_one(selector)
    except Exception:  # invalid selector from a bad config/AI answer
        return None


def text_of(tag: Optional[Tag]) -> str:
    """Visible text of a tag (``content`` for ``<meta>``). Duck-typed so the
    scraper works against any object exposing ``.get``/``.text``."""

    if tag is None:
        return ""
    if getattr(tag, "name", None) == "meta":
        return str(tag.get("content") or "").strip()
    getter = getattr(tag, "get_text", None)
    raw = getter(" ", strip=True) if callable(getter) else getattr(tag, "text", "")
    return " ".join(str(raw or "").split())


def dig(data: Any, path: Optional[str]) -> Any:
    """Follow a dotted path (``props.pageProps.chapters`` / ``sources.0.images``)."""

    if not path:
        return data
    current = data
    for key in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None
        if current is None:
            return None
    return current


def _balanced_json(text: str, start: int) -> Optional[str]:
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def json_from_scripts(
    soup: BeautifulSoup,
    *,
    script_selector: Optional[str] = None,
    marker: Optional[str] = None,
) -> Any:
    """JSON embedded in the page: either the whole text of ``script_selector``
    (``script#__NEXT_DATA__``) or the first object/array literal following
    ``marker`` in any script (``ts_reader.run(``, ``window.__DATA__ =``)."""

    scripts = select(soup, script_selector) if script_selector else soup.find_all("script")
    for script in scripts:
        body = script.string or script.get_text() or ""
        if not body.strip():
            continue
        if marker is None:
            try:
                return json.loads(body)
            except ValueError:
                continue
        position = body.find(marker)
        if position < 0:
            continue
        brace = min(
            (i for i in (body.find("{", position), body.find("[", position)) if i >= 0),
            default=-1,
        )
        if brace < 0:
            continue
        literal = _balanced_json(body, brace)
        if literal is None:
            continue
        try:
            return json.loads(literal)
        except ValueError:
            continue
    return None


_PAGE_STEM = re.compile(r"(?:p|pg|page|img|image)?[-_]?0*(\d{1,4})", re.I)


def order_pages(urls: List[str]) -> List[str]:
    """Reading order for a chapter's page images.

    Sources normally list pages in order, and that order is kept. But when
    *every* image sits in one folder and is named by its own page number
    (``003.jpg``, ``page-12.webp``) and the list is out of order (lazy-load
    scripts sometimes shuffle it), the numbers win. Anything ambiguous -- mixed
    folders, unnumbered names, repeated numbers -- is left exactly as found.
    """

    if len(urls) < 2:
        return urls
    numbers: List[int] = []
    folders = set()
    for url in urls:
        path = urlparse(url).path
        folder, _, name = path.rpartition("/")
        stem = name.rsplit(".", 1)[0]
        match = _PAGE_STEM.fullmatch(stem)
        if not match:
            return urls
        folders.add(folder)
        numbers.append(int(match.group(1)))
    if len(folders) != 1 or len(set(numbers)) != len(numbers) or numbers == sorted(numbers):
        return urls
    return [url for _, url in sorted(zip(numbers, urls))]


def dedupe(urls: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    ordered = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered
