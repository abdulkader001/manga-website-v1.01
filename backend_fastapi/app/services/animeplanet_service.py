"""Series metadata from Anime-Planet's manga section.

Only https://www.anime-planet.com/manga/<slug> pages are accepted, and only
when the entry is a manga, manhwa or manhua: light novels, web novels and
anything outside /manga/ (anime included) are refused with a clear reason.

Anime-Planet has no public API, so the page is read from the structured data
it embeds (schema.org JSON-LD, Open Graph tags) with visible-page fallbacks.
Errors are raised, never papered over with placeholder data.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import structlog
from bs4 import BeautifulSoup

from .mangaupdates_service import SeriesMetadata

logger = structlog.get_logger(__name__)

ALLOWED_HOSTS = {"www.anime-planet.com", "anime-planet.com"}
_SLUG_RE = re.compile(r"^/manga/([a-z0-9][a-z0-9\-_.%]*)/?$", re.I)
# Directory/listing pages under /manga/ that are not a single series.
_RESERVED = {"all", "top-manga", "recommendations", "tags", "authors", "read", "popular", "new"}

_TYPE_WORDS = {
    "manga": "manga",
    "one shot": "manga",
    "one-shot": "manga",
    "doujinshi": "manga",
    "manhwa": "manhwa",
    "webtoon": "manhwa",
    "manhua": "manhua",
}
_REJECT_WORDS = ("light novel", "web novel", "novel", "anime", "tv series", "movie", "ova")


class AnimePlanetError(Exception):
    """A user-facing reason the metadata could not be loaded."""


def slug_from_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise AnimePlanetError(
            "That is not an Anime-Planet link. Use https://www.anime-planet.com/manga/<name>."
        )
    match = _SLUG_RE.match(parsed.path or "")
    if not match or match.group(1).lower() in _RESERVED:
        raise AnimePlanetError(
            "Use the page of one manga on Anime-Planet (https://www.anime-planet.com/manga/<name>), "
            "not a list. Anime pages are not accepted."
        )
    return match.group(1).lower()


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(text or ""))).strip()


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _names(value: Any) -> List[str]:
    out: List[str] = []
    for item in _as_list(value):
        name = _clean(item.get("name") if isinstance(item, dict) else item)
        if name and name not in out:
            out.append(name)
    return out


def _jsonld_objects(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    objects: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "null")
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                if "@graph" in node:
                    stack.extend(_as_list(node["@graph"]))
                objects.append(node)
    return objects


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return _clean(tag["content"])
    return ""


def _map_type(text: str) -> Optional[str]:
    lowered = text.lower()
    for word, mapped in _TYPE_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return mapped
    return None


def _entry_type(soup: BeautifulSoup, ld: Dict[str, Any]) -> tuple[Optional[str], str]:
    """(manga|manhwa|manhua|None, rejected-kind). The second item is non-empty
    when the entry is something this site must not import (a novel, anime)."""

    candidates: List[str] = []
    for label in soup.find_all(string=re.compile(r"^\s*Type\s*:?\s*$", re.I)):
        sibling = label.parent.find_next_sibling() if label.parent else None
        if sibling:
            candidates.append(_clean(sibling.get_text(" ")))
        parent_text = _clean(label.parent.parent.get_text(" ")) if label.parent and label.parent.parent else ""
        if parent_text:
            candidates.append(parent_text)
    for node in soup.select('[class*="type"], .entryBar, .pure-1.md-1-5'):
        candidates.append(_clean(node.get_text(" "))[:80])
    candidates.append(" ".join(_names(ld.get("additionalType"))))
    for text in candidates:
        lowered = text.lower()
        for bad in _REJECT_WORDS:
            if re.search(rf"\b{re.escape(bad)}s?\b", lowered):
                return None, bad
        mapped = _map_type(text)
        if mapped:
            return mapped, ""
    return None, ""


def _status(soup: BeautifulSoup) -> str:
    text = _clean(soup.get_text(" "))[:20000].lower()
    for word, mapped in (
        ("hiatus", "hiatus"),
        ("cancelled", "cancelled"),
        ("canceled", "cancelled"),
        ("completed", "completed"),
        ("ongoing", "ongoing"),
    ):
        if re.search(rf"\b(?:status|release)\b[^.]{{0,40}}\b{word}\b", text):
            return mapped
    return "ongoing"


def parse_page(markup: str, url: str) -> SeriesMetadata:
    slug = slug_from_url(url)
    soup = BeautifulSoup(markup, "html.parser")

    ld: Dict[str, Any] = {}
    for obj in _jsonld_objects(soup):
        kind = " ".join(str(t) for t in _as_list(obj.get("@type"))).lower()
        if any(k in kind for k in ("book", "comic", "creativeworkseries", "periodical", "creativework")):
            ld = obj
            break

    title = _clean(ld.get("name")) or _meta(soup, "og:title", "twitter:title")
    title = re.sub(r"\s*\|\s*(?:Manga|Manhwa|Manhua|Webtoon)?\s*\|?\s*Anime-Planet\s*$", "", title, flags=re.I).strip()
    if not title:
        h1 = soup.find("h1")
        title = _clean(h1.get_text(" ")) if h1 else ""
    if not title:
        raise AnimePlanetError("Anime-Planet returned a page without a title (it may be blocking automated access).")

    kind, rejected = _entry_type(soup, ld)
    if rejected:
        raise AnimePlanetError(
            f"“{title}” is a {rejected} on Anime-Planet. Only manga, manhwa and manhua can be imported."
        )

    genres = _names(ld.get("genre"))
    if not genres:
        genres = [_clean(a.get_text()) for a in soup.select('a[href*="/manga/tags/"]')]
    authors = _names(ld.get("author")) or [
        _clean(a.get_text()) for a in soup.select('a[href*="/manga/authors/"]')
    ]
    artists = _names(ld.get("illustrator")) or _names(ld.get("creator"))
    alt = _names(ld.get("alternateName"))
    if not alt:
        alt_node = soup.find(class_=re.compile(r"alt", re.I))
        if alt_node:
            alt = [p.strip() for p in re.split(r"[,;]", _clean(alt_node.get_text(" "))) if p.strip()][:10]
    cover = ld.get("image")
    if isinstance(cover, dict):
        cover = cover.get("url")
    if isinstance(cover, list):
        cover = cover[0] if cover else ""
    cover = _clean(cover) or _meta(soup, "og:image")
    description = _clean(ld.get("description")) or _meta(soup, "og:description", "description")
    year_match = re.search(r"\b(19|20)\d{2}\b", _clean(ld.get("datePublished")) or "")

    uniq = lambda items: list(dict.fromkeys(i for i in items if i))  # noqa: E731
    return SeriesMetadata(
        series_id=0,
        url=f"https://www.anime-planet.com/manga/{slug}",
        title=title,
        alt_titles=[a for a in uniq(alt) if a.lower() != title.lower()],
        description=description,
        genres=uniq(genres),
        authors=uniq(authors),
        artists=uniq(artists),
        cover_url=cover,
        type=kind,
        status=_status(soup),
        year=year_match.group(0) if year_match else None,
    )


def fetch_series(url: str) -> SeriesMetadata:
    """Load a manga from Anime-Planet. Raises :class:`AnimePlanetError`."""

    slug_from_url(url)  # validate before any request

    from ..scrapers.http_client import RequestWrapper

    try:
        response = RequestWrapper.get(
            f"https://www.anime-planet.com/manga/{slug_from_url(url)}",
            timeout=20,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en",
                "User-Agent": "Mozilla/5.0 (compatible; MangaReader/1.0)",
            },
            max_bytes=3 * 1024 * 1024,
        )
    except Exception as exc:
        logger.warning("animeplanet_fetch_failed", error=str(exc)[:200])
        raise AnimePlanetError("Anime-Planet could not be reached. Try again in a moment.") from exc
    if response.status_code == 404:
        raise AnimePlanetError("Anime-Planet has no manga at that address.")
    if response.status_code in (403, 429, 503):
        raise AnimePlanetError(
            f"Anime-Planet refused the request (HTTP {response.status_code}); it may be rate limiting or "
            "blocking automated access. Try again later, or use a MangaUpdates link."
        )
    if response.status_code != 200:
        raise AnimePlanetError(f"Anime-Planet answered with HTTP {response.status_code}.")
    return parse_page(response.text, url)
