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
# "Fillers": what a site puts around the reader that isn't the chapter, such as
# a "you may like" / 猜你喜欢 box of other series' covers, rankings, adverts.
# They often use the same lazy-load attributes as the pages, so a selector
# alone can't tell them apart; their container's name or heading can.
_FILLER_HINT = re.compile(
    r"recommend|related|similar|guess|you-?may|youlike|maylike|popular|hot-?(list|comic|manga|book)|"
    r"\brank|top-?\d|suggest|sidebar|side-?bar|promo|advert|\bads?\b|other-?(comic|manga|series|book)|"
    r"more-?(comic|manga|series)|tuijian|cainixihuan",
    re.I,
)
_FILLER_TEXT = re.compile(
    r"猜你喜[欢歡]|相[关關]推[荐薦]|推[荐薦]|[热熱]门|[热熱]門|人[气氣]|排行|大家都在看|看了[这這]|"
    r"おすすめ|関連|人気|ランキング|추천|인기|관련|"
    r"you (may|might) (also )?like|recommended|related|popular|trending|more like this|similar",
    re.I,
)
_IMAGE_FILE = re.compile(r"\.(jpe?g|png|webp|gif|avif|bmp)(\?|$)", re.I)


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
        if len(members) < 2:
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
        # A brand-new series can have just two chapters. With so little to go
        # on, require every link to say "chapter"/"episode"/... so a pair of
        # navigation links is never taken for a chapter list.
        if len(members) < 3 and hinted < len(members):
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


_PAGE_PARAMS = re.compile(r"^(page|p|pg|pageno|page_no|index)$", re.I)


def _page_stem(url: str) -> str:
    """Chapter URL without a trailing slash or ``.html``-style extension, the
    part every page of the same chapter shares."""

    parsed = urlparse(url)
    path = re.sub(r"\.(html?|php|aspx?)$", "", parsed.path.rstrip("/"), flags=re.I)
    return f"{parsed.netloc}{path}"


def detect_pagination(soup: BeautifulSoup, url: str) -> Optional[Dict[str, Any]]:
    """Numbered links to the other pages of *this* chapter, as ``page_list``.

    Deliberately conservative: a link counts only when it extends the chapter's
    own URL (``/ch/12`` -> ``/ch/12/2``, ``/ch/12_2.html``) or adds a ``page=``
    style parameter to it, and its label is a bare page number. A dropdown of
    *chapters* therefore never qualifies.
    """

    stem = _page_stem(url)
    if not stem:
        return None
    members: List[Tag] = []
    numbers: List[int] = []
    for tag in soup.find_all(["a", "option"]):
        raw = tag.get("href") if tag.name == "a" else tag.get("value")
        label = parsing.text_of(tag)
        if not raw or not re.fullmatch(r"\d{1,3}", label or ""):
            continue
        absolute = parsing.absolute(url, raw)
        if not absolute or absolute == url:
            continue
        candidate = urlparse(absolute)
        candidate_stem = _page_stem(absolute)
        query_pages = [k for k in re.findall(r"([A-Za-z_]+)=\d+", candidate.query) if _PAGE_PARAMS.match(k)]
        extends = candidate_stem != stem and candidate_stem.startswith(stem) and re.fullmatch(
            r"[/_\-]?\d{1,3}", candidate_stem[len(stem):]
        )
        same_with_param = candidate_stem == stem and bool(query_pages)
        if extends or same_with_param:
            members.append(tag)
            numbers.append(int(label))
    if len(members) < 1 or len(set(numbers)) != len(numbers):
        return None
    selector = _pick_selector(soup, members, members[0].name)
    return {"page_list": selector} if selector else None


def _labelled_filler(node: Tag) -> bool:
    """True when ``node`` is a box headed "猜你喜欢", "Recommended"... : a
    short text child (or the element just before it) with no image in it."""

    near = [c for c in node.find_all(recursive=False) if isinstance(c, Tag)][:3]
    prev = node.find_previous_sibling()
    if isinstance(prev, Tag):
        near.append(prev)
    for el in near:
        if el.name == "img" or el.find("img") is not None:
            continue
        text = el.get_text(" ", strip=True)
        if text and len(text) <= 24 and _FILLER_TEXT.search(text):
            return True
    return False


_FIRST_NUMBER = re.compile(r"\d+")


def _same_series(target, here) -> bool:
    """Whether a link from a page image stays within this series: the next
    page, the next chapter or the series page, not another title."""

    if target.netloc and target.netloc != here.netloc:
        return False
    if here.path.startswith(target.path.rstrip("/") + "/") or target.path == here.path:
        return True
    a, b = _FIRST_NUMBER.search(target.path), _FIRST_NUMBER.search(here.path)
    if a and b:
        return a.group() == b.group()
    # No ids in the addresses: same series when they share all but the
    # last part (/manga/slug/ch-1 and /manga/slug/ch-2).
    return target.path.rstrip("/").rsplit("/", 1)[0] == here.path.rstrip("/").rsplit("/", 1)[0]


def is_filler(tag: Tag, page_url: Optional[str] = None) -> bool:
    """True for an image the site put around the chapter rather than in it:
    another series' cover in a "you may like" box, a ranking, an advert.

    Signs, any one is enough: a container named like one (``recommend``,
    ``related``, ``sidebar``...), a box headed like one (猜你喜欢, 推荐,
    おすすめ, 추천, "You may also like"), or a link from the image to a page
    shaped differently from this chapter (another series), not to the next
    page or to the full-size picture.
    """

    for anc in _ancestors(tag, 6):
        name = " ".join([str(anc.get("id") or "")] + list(anc.get("class") or []))
        if name.strip() and _FILLER_HINT.search(name):
            return True
    if any(_labelled_filler(anc) for anc in _ancestors(tag, 3)):
        return True
    if page_url and not page_url.startswith(_BASE):
        link = tag.find_parent("a", href=True)
        if link is not None and any(a is link for a in _ancestors(tag, 3)):
            href = str(link.get("href") or "").strip()
            if href and not href.startswith(("#", "javascript:")) and not _IMAGE_FILE.search(href):
                target = urlparse(parsing.absolute(page_url, href) or href)
                if not _same_series(target, urlparse(page_url)):
                    return True
    return False


def _is_page_candidate(tag: Tag, url: Optional[str], page_url: Optional[str] = None) -> bool:
    """False for images that are plainly not chapter pages: site chrome
    (nav/header/footer/aside), logos and badges, small thumbnails and
    fillers (see ``is_filler``)."""

    if not url or _in_ignored(tag):
        return False
    if is_filler(tag, page_url):
        return False
    if _NOISE_IMG.search(url) or _NOISE_IMG.search(" ".join(tag.get("class") or [])):
        return False
    try:
        width = int(str(tag.get("width") or "0").rstrip("px") or 0)
    except ValueError:
        width = 0
    return not 0 < width < 150


def _group_signature(tag: Tag) -> str:
    return "/".join(_token(a) for a in _ancestors(tag, 3)) + "|" + tag.name


def main_image_group(tags: List[Tag], base_url: str, preferred_attr: Optional[str] = None) -> List[Tag]:
    """The reader's page images among ``tags``: the biggest group of images
    sharing one container, after dropping site chrome and thumbnails.

    A selector that is a union of alternatives (``img[data-original], #cp_img
    img``) also matches the lazy-loaded "related series" thumbnails in a
    sidebar, which use the same attributes as the pages. Those sit in a
    different container, so keeping only the largest same-container group
    removes them. Ties keep the group that appears first on the page.
    """

    groups: Dict[str, List[Tag]] = defaultdict(list)
    for tag in tags:
        if _is_page_candidate(tag, parsing.image_url(tag, base_url, preferred_attr), base_url):
            groups[_group_signature(tag)].append(tag)
    if not groups:
        return []
    return max(groups.values(), key=len)


def drop_thumbnails(tags: List[Tag], base_url: str, preferred_attr: Optional[str] = None) -> List[Tag]:
    """The page images among ``tags`` for a parser with ONE selector (an
    admin's or the Scraper AI's), which is trusted more than a union.

    Always dropped: site chrome (nav/header/footer/aside), logos and badges,
    and images under 150 px wide. When the matches fall into several
    containers, a smaller group whose images are links (the "related series"
    thumbnails a sidebar shows) is dropped too; a smaller group of plain
    images (a first page in its own wrapper) is kept.
    """

    candidates = [t for t in tags if _is_page_candidate(t, parsing.image_url(t, base_url, preferred_attr), base_url)]
    if not candidates:
        return []
    groups: Dict[str, List[Tag]] = defaultdict(list)
    for tag in candidates:
        groups[_group_signature(tag)].append(tag)
    if len(groups) == 1:
        return candidates
    largest = max(groups.values(), key=len)
    dropped = set()
    for members in groups.values():
        if members is largest:
            continue
        if all(member.find_parent("a", href=True) is not None for member in members):
            dropped.update(id(member) for member in members)
    return [t for t in candidates if id(t) not in dropped]


def detect_reader_definition(html: str, base_url: str = _BASE) -> Optional[Dict[str, Any]]:
    """The page-image group of a reader page."""

    soup = BeautifulSoup(html or "", "html.parser")

    from . import script_images

    if script_images.cms_images(soup, base_url):
        # SinMH / qTcms readers: the page list in the script is the real one.
        # Their HTML still has lazy-loaded thumbnails of other series, which
        # would otherwise be taken for the pages.
        return {"image_source": {"decoder": "auto_script"}}

    groups: Dict[str, List[Tag]] = defaultdict(list)
    attr_used: Dict[str, str] = {}
    for tag in soup.find_all(["img", "amp-img"]):
        url = parsing.image_url(tag, base_url)
        if not _is_page_candidate(tag, url, base_url):
            continue
        signature = _group_signature(tag)
        groups[signature].append(tag)
        for attr in parsing.IMAGE_ATTRS:
            if tag.get(attr) and parsing.absolute(base_url, str(tag.get(attr))) == url:
                attr_used.setdefault(signature, attr)
                break

    if not groups:
        # No usable <img>: the page list may live in a script instead.
        if script_images.auto_images(soup, base_url):
            return {"image_source": {"decoder": "auto_script"}}
        return None
    signature, members = max(groups.items(), key=lambda item: len(item[1]))
    selector = _pick_selector(soup, members, members[0].name)
    if not selector:
        return None
    definition: Dict[str, Any] = {"page_images": selector}
    attr = attr_used.get(signature)
    if attr and attr != "src":
        definition["image_attr"] = attr
    # A chapter spread over several HTML pages: follow them in order.
    pagination = detect_pagination(soup, base_url)
    if pagination:
        definition.update(pagination)
    return definition
