"""Work out extraction rules from a page's structure alone (no AI, no
per-site knowledge).

A chapter list is the biggest group of similar links that look like chapters;
a reader's pages are the biggest group of similar, real images. Both are
turned into CSS selectors that are then checked against the page: the
selector must hit (nearly) exactly the elements it was derived from, so it
neither misses chapters nor sweeps in unrelated links.

This is what makes a site that moved to a new domain (or an unknown CMS) work
without anyone writing selectors. Results are still validated by the caller
before being trusted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from . import parsing

_BASE = "https://autodetect.invalid/"
_CHAPTER_HINT = re.compile(
    r"chap|ch[-_. ]?\d|episode|\bep[-_. ]?\d|第|话|話|화|章|capitulo|chapitre|kapitel|read", re.I
)
_UNSTABLE_CLASS = re.compile(
    r"^(active|current|selected|odd|even|first|last|hidden|show|open|is-|has-|js-|"
    r"col-|row$|clearfix|item-\d)|\d{2,}|^[a-z0-9]{10,}$",
    re.I,
)
_IGNORED_ANCESTORS = {"nav", "header", "footer", "aside", "form"}
_NOISE_IMG = re.compile(r"logo|avatar|icon|banner|sprite|emoji|button|badge|/ads?/|advert", re.I)


def _stable_classes(tag: Tag, limit: int = 2) -> List[str]:
    classes = tag.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    stable = [c for c in classes if c and not _UNSTABLE_CLASS.search(c)]
    return stable[:limit]


def _token(tag: Tag) -> str:
    identifier = tag.get("id")
    if identifier and not _UNSTABLE_CLASS.search(str(identifier)) and re.fullmatch(r"[A-Za-z][\w-]*", str(identifier)):
        return f"{tag.name}#{identifier}"
    classes = _stable_classes(tag)
    return tag.name + "".join(f".{c}" for c in classes if re.fullmatch(r"[A-Za-z_][\w-]*", c))


def _ancestors(tag: Tag, depth: int = 4) -> List[Tag]:
    chain: List[Tag] = []
    node = tag.parent
    while isinstance(node, Tag) and node.name not in ("[document]", "html", "body") and len(chain) < depth:
        chain.append(node)
        node = node.parent
    return chain


def _in_ignored(tag: Tag) -> bool:
    return any(a.name in _IGNORED_ANCESTORS for a in _ancestors(tag, 8))


def _href_shape(href: str) -> str:
    parsed = urlparse(href)
    path = re.sub(r"\d+", "#", parsed.path)
    query = re.sub(r"\d+", "#", parsed.query)
    return f"{path}?{query}" if query else path


def _candidate_selectors(node: Tag, leaf: str) -> List[str]:
    """Selectors that end at ``leaf`` (``a`` / ``img``), from loosest to
    tightest ancestor context."""

    own = _token(node)
    selectors: List[str] = []
    if own != node.name:
        selectors.append(own)
    tokens = [_token(a) for a in _ancestors(node, 4)]
    for depth in range(1, len(tokens) + 1):
        window = tokens[:depth][::-1]
        if all(t.split(".")[0].split("#")[0] == t for t in window):
            continue  # nothing distinguishing in this window
        selectors.append(" ".join(window + [own]))
        selectors.append(" > ".join(window[-1:] + [own]))
    selectors.append(own)
    seen: List[str] = []
    for selector in selectors:
        if selector not in seen:
            seen.append(selector)
    return seen


def _pick_selector(
    soup: BeautifulSoup, members: List[Tag], leaf: str
) -> Optional[str]:
    """First candidate selector that covers the group and little else."""

    wanted = {id(m) for m in members}
    exemplar = members[0]
    best: Tuple[float, Optional[str]] = (0.0, None)
    for selector in _candidate_selectors(exemplar, leaf):
        matched = parsing.select(soup, selector)
        if not matched:
            continue
        hits = sum(1 for m in matched if id(m) in wanted)
        coverage = hits / len(members)
        precision = hits / len(matched)
        if coverage >= 0.9 and precision >= 0.85:
            return selector
        score = coverage * precision
        if score > best[0]:
            best = (score, selector)
    return best[1] if best[0] >= 0.6 else None


def detect_chapter_list(soup: BeautifulSoup, base_url: str = _BASE) -> Optional[Dict[str, Any]]:
    """The chapter link group of a series page, as ``{"selector", "count"}``."""

    groups: Dict[Tuple[str, str], List[Tag]] = defaultdict(list)
    for anchor in soup.find_all("a", href=True):
        href = parsing.absolute(base_url, anchor.get("href"))
        if not href or _in_ignored(anchor):
            continue
        text = parsing.text_of(anchor)
        if not text and not anchor.find("img"):
            continue
        signature = "/".join(_token(a) for a in _ancestors(anchor, 3))
        groups[(signature, _href_shape(href))].append(anchor)

    best_group: Optional[List[Tag]] = None
    best_score = 0.0
    for members in groups.values():
        if len(members) < 3:
            continue
        numbered = sum(
            1
            for a in members
            if re.search(r"\d", parsing.text_of(a)) or re.search(r"\d", a.get("href", ""))
        )
        hinted = sum(
            1
            for a in members
            if _CHAPTER_HINT.search(parsing.text_of(a)) or _CHAPTER_HINT.search(a.get("href", ""))
        )
        number_fraction = numbered / len(members)
        if number_fraction < 0.6:
            continue
        score = len(members) * number_fraction * (1.0 + hinted / len(members))
        if score > best_score:
            best_score, best_group = score, members
    if not best_group:
        return None
    selector = _pick_selector(soup, best_group, "a")
    if not selector:
        return None
    return {"selector": selector, "count": len(parsing.select(soup, selector))}


def detect_series_definition(html: str, base_url: str = _BASE) -> Optional[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    chapters = detect_chapter_list(soup, base_url)
    if not chapters:
        return None
    title_selector = None
    h1 = soup.find("h1")
    if h1 is not None and parsing.text_of(h1):
        title_selector = _pick_selector(soup, [h1], "h1") or "h1"
    elif soup.select_one("meta[property='og:title']"):
        title_selector = "meta[property='og:title']"
    if not title_selector:
        return None
    definition: Dict[str, Any] = {
        "manga_title": title_selector,
        "chapter_list": chapters["selector"],
        "chapter_url": "a",
        "chapter_title": "a",
    }
    if soup.select_one("meta[property='og:description']"):
        definition["manga_description"] = "meta[property='og:description']"
    elif soup.select_one("meta[name='description']"):
        definition["manga_description"] = "meta[name='description']"
    if soup.select_one("meta[property='og:image']"):
        definition["manga_cover"] = "meta[property='og:image']"
    return definition


def detect_reader_definition(html: str, base_url: str = _BASE) -> Optional[Dict[str, Any]]:
    """The page-image group of a reader page."""

    soup = BeautifulSoup(html or "", "html.parser")

    groups: Dict[str, List[Tag]] = defaultdict(list)
    attr_used: Dict[str, str] = {}
    for tag in soup.find_all(["img", "amp-img"]):
        if _in_ignored(tag):
            continue
        url = parsing.image_url(tag, base_url)
        if not url or _NOISE_IMG.search(url) or _NOISE_IMG.search(" ".join(tag.get("class") or [])):
            continue
        try:
            width = int(str(tag.get("width") or "0").rstrip("px") or 0)
        except ValueError:
            width = 0
        if 0 < width < 150:
            continue
        signature = "/".join(_token(a) for a in _ancestors(tag, 3)) + "|" + tag.name
        groups[signature].append(tag)
        for attr in parsing.IMAGE_ATTRS:
            if tag.get(attr) and parsing.absolute(base_url, str(tag.get(attr))) == url:
                attr_used.setdefault(signature, attr)
                break

    if not groups:
        return None
    signature, members = max(groups.items(), key=lambda item: len(item[1]))
    selector = _pick_selector(soup, members, members[0].name)
    if not selector:
        return None
    definition: Dict[str, Any] = {"page_images": selector}
    attr = attr_used.get(signature)
    if attr and attr != "src":
        definition["image_attr"] = attr
    return definition
