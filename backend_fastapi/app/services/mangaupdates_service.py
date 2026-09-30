"""Series metadata from MangaUpdates (title, description, genres, authors,
cover, type, status).

MangaUpdates is the single source of truth for a series' *metadata*; the
source website is only used for chapters. Errors are raised, never papered
over with placeholder data.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)

API_BASE = "https://api.mangaupdates.com/v1"
ALLOWED_HOSTS = {"www.mangaupdates.com", "mangaupdates.com"}

_ID_RE = re.compile(r"/series/([a-z0-9]+)", re.I)
_LEGACY_ID_RE = re.compile(r"[?&]id=(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")


class MangaUpdatesError(Exception):
    """A user-facing reason the metadata could not be loaded."""


@dataclass
class SeriesMetadata:
    series_id: int
    url: str
    title: str
    alt_titles: List[str] = field(default_factory=list)
    description: str = ""
    genres: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    authors: List[str] = field(default_factory=list)
    artists: List[str] = field(default_factory=list)
    cover_url: str = ""
    type: Optional[str] = None  # manga | manhwa | manhua
    status: str = "ongoing"  # ongoing | completed | hiatus | cancelled
    publisher: str = ""
    year: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def series_id_from_url(url: str) -> int:
    """Numeric series id from a MangaUpdates URL.

    New-style links carry the id in base 36 (``/series/pi4azuo/solo-leveling``);
    legacy links carry it in decimal (``series.html?id=15180124``).
    """

    parsed = urlparse((url or "").strip())
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS or parsed.scheme not in {
        "http",
        "https",
    }:
        raise MangaUpdatesError(
            "That is not a MangaUpdates link. Use https://www.mangaupdates.com/series/<id>/<name>."
        )
    legacy = _LEGACY_ID_RE.search("?" + (parsed.query or ""))
    if legacy:
        return int(legacy.group(1))
    match = _ID_RE.search(parsed.path)
    if not match:
        raise MangaUpdatesError(
            "That MangaUpdates link has no series id. Use https://www.mangaupdates.com/series/<id>/<name>."
        )
    try:
        # Path-style ids are always base 36 (an all-digit one is still base 36).
        return int(match.group(1).lower(), 36)
    except ValueError:
        raise MangaUpdatesError("That MangaUpdates series id could not be read.")


def _clean(text: Any) -> str:
    value = html.unescape(_TAG_RE.sub(" ", str(text or "")))
    return " ".join(value.split())


def _description(raw: Any) -> str:
    text = str(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = html.unescape(_TAG_RE.sub("", text))
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def _map_type(raw: Optional[str]) -> Optional[str]:
    value = (raw or "").strip().lower()
    if value in {"manga", "doujinshi", "oel"}:
        return "manga"
    if value in {"manhwa"}:
        return "manhwa"
    if value in {"manhua"}:
        return "manhua"
    return None


def _map_status(payload: Dict[str, Any]) -> str:
    text = str(payload.get("status") or "").lower()
    if payload.get("completed") or "complete" in text:
        return "completed"
    if "hiatus" in text:
        return "hiatus"
    if "cancel" in text or "drop" in text or "discontinu" in text:
        return "cancelled"
    return "ongoing"


def parse_series(payload: Dict[str, Any], url: str) -> SeriesMetadata:
    """Build metadata from a ``GET /v1/series/{id}`` response."""

    title = _clean(payload.get("title"))
    if not title:
        raise MangaUpdatesError("MangaUpdates returned no title for that series.")

    authors: List[str] = []
    artists: List[str] = []
    for person in payload.get("authors") or []:
        name = _clean(person.get("name") if isinstance(person, dict) else person)
        if not name:
            continue
        kind = str(person.get("type") if isinstance(person, dict) else "").lower()
        (artists if kind == "artist" else authors).append(name)

    image = payload.get("image") or {}
    urls = image.get("url") if isinstance(image, dict) else {}
    cover = ""
    if isinstance(urls, dict):
        cover = str(urls.get("original") or urls.get("thumb") or "")

    publisher = ""
    for entry in payload.get("publishers") or []:
        if isinstance(entry, dict) and str(entry.get("type", "")).lower() == "original":
            publisher = _clean(entry.get("publisher_name"))
            break

    def names(items: Any, key: str) -> List[str]:
        out = []
        for item in items or []:
            value = item.get(key) if isinstance(item, dict) else item
            value = _clean(value)
            if value and value not in out:
                out.append(value)
        return out

    return SeriesMetadata(
        series_id=int(payload.get("series_id") or 0),
        url=url,
        title=title,
        alt_titles=names(payload.get("associated"), "title")[:30],
        description=_description(payload.get("description")),
        genres=names(payload.get("genres"), "genre"),
        categories=names(payload.get("categories"), "category")[:30],
        authors=list(dict.fromkeys(authors)),
        artists=list(dict.fromkeys(artists)),
        cover_url=cover,
        type=_map_type(payload.get("type")),
        status=_map_status(payload),
        publisher=publisher,
        year=str(payload.get("year") or "") or None,
    )


def fetch_series(url: str) -> SeriesMetadata:
    """Load a series from MangaUpdates. Raises :class:`MangaUpdatesError`."""

    series_id = series_id_from_url(url)

    from ..scrapers.http_client import RequestWrapper

    try:
        response = RequestWrapper.get(
            f"{API_BASE}/series/{series_id}",
            timeout=15,
            headers={"Accept": "application/json", "User-Agent": "MangaReader/1.0"},
            max_bytes=2 * 1024 * 1024,
        )
    except Exception as exc:
        logger.warning("mangaupdates_fetch_failed", series_id=series_id, error=str(exc)[:200])
        raise MangaUpdatesError(
            "MangaUpdates could not be reached. Try again in a moment."
        ) from exc

    if response.status_code == 404:
        raise MangaUpdatesError("MangaUpdates has no series with that id.")
    if response.status_code == 429:
        raise MangaUpdatesError("MangaUpdates is rate limiting us. Try again in a minute.")
    if response.status_code != 200:
        raise MangaUpdatesError(f"MangaUpdates answered with HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise MangaUpdatesError("MangaUpdates returned an unreadable response.") from exc
    if not isinstance(payload, dict):
        raise MangaUpdatesError("MangaUpdates returned an unexpected response.")

    payload.setdefault("series_id", series_id)
    return parse_series(payload, url)
