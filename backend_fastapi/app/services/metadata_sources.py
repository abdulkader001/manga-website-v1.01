"""Series metadata links: MangaUpdates or Anime-Planet.

One entry point for the import flow so the rest of the code never needs to
know which site a link belongs to. Both produce the same ``SeriesMetadata``.
"""

from __future__ import annotations

from typing import Tuple
from urllib.parse import urlparse

from . import animeplanet_service, mangaupdates_service
from .mangaupdates_service import SeriesMetadata


class MetadataLinkError(ValueError):
    """The link is not usable as a metadata source (message is user-facing)."""


def _host(url: str) -> str:
    return (urlparse((url or "").strip()).hostname or "").lower()


def source_name(url: str) -> str:
    host = _host(url)
    if host in mangaupdates_service.ALLOWED_HOSTS:
        return "mangaupdates"
    if host in animeplanet_service.ALLOWED_HOSTS:
        return "animeplanet"
    raise MetadataLinkError(
        "Metadata links must come from MangaUpdates (mangaupdates.com/series/…) "
        "or Anime-Planet (anime-planet.com/manga/…)."
    )


def identity(url: str) -> Tuple[str, str]:
    """(source, stable id) -- the same series always yields the same pair,
    whatever the URL spelling, so one series can't be imported twice."""

    name = source_name(url)
    try:
        if name == "mangaupdates":
            return name, str(mangaupdates_service.series_id_from_url(url))
        return name, animeplanet_service.slug_from_url(url)
    except (mangaupdates_service.MangaUpdatesError, animeplanet_service.AnimePlanetError) as exc:
        raise MetadataLinkError(str(exc)) from exc


def label(url: str) -> str:
    return "MangaUpdates" if source_name(url) == "mangaupdates" else "Anime-Planet"


def fetch(url: str) -> SeriesMetadata:
    """Load metadata from whichever site the link belongs to."""

    name = source_name(url)
    try:
        if name == "mangaupdates":
            return mangaupdates_service.fetch_series(url)
        return animeplanet_service.fetch_series(url)
    except (mangaupdates_service.MangaUpdatesError, animeplanet_service.AnimePlanetError) as exc:
        raise MetadataLinkError(str(exc)) from exc


__all__ = ["MetadataLinkError", "fetch", "identity", "label", "source_name"]
