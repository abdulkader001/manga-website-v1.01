"""Content-rights resolution and gates (SRS Part 1J).

Rights are recorded at two levels — per website (``ApprovedSourceDomain``) and
per series (``Manga``) — and ``may_host`` / ``may_translate`` are *separate*
permissions. A NoDerivatives licence, for example, permits hosting but forbids
translation, so the two flags move independently.

Effective rights AND the website default with the series value: a series can
never be hosted or translated beyond what its source website grants. A series
whose effective ``may_translate`` is False (or that is taken down) cannot be
translated by any path or any role, including the Permanent Administrator.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from ..core.api_errors import ApiError, ErrorCode

# User-facing messages (kept as constants so tests pin the wording).
MSG_HOST_FORBIDDEN = "This website is not licensed for hosting"
MSG_TRANSLATE_FORBIDDEN = "This series is not licensed for translation"
MSG_TAKEN_DOWN = "This series has been taken down"


def _host_of(url: str) -> str:
    return (urlparse(url or "").hostname or "").strip().lower()


def approved_domain_for_url(db_session, url: str):
    """Return the ``ApprovedSourceDomain`` governing ``url`` (subdomain-aware)."""

    from ..models import ApprovedSourceDomain

    hostname = _host_of(url)
    if not hostname:
        return None
    for entry in db_session.query(ApprovedSourceDomain).all():
        domain = (entry.domain or "").strip().lower()
        if not domain:
            continue
        if hostname == domain or hostname.endswith("." + domain):
            return entry
    return None


def _website_defaults(entry) -> tuple[bool, bool, Optional[str]]:
    """(may_host, may_translate, attribution) for a website, defaulting open."""

    if entry is None:
        return True, True, None
    may_host = True if entry.may_host is None else bool(entry.may_host)
    may_translate = True if entry.may_translate is None else bool(entry.may_translate)
    return may_host, may_translate, entry.attribution


def resolve_series_rights(db_session, manga) -> dict:
    """Resolve effective rights for a series.

    The series flags are ANDed with its source website's defaults, and a
    taken-down series is denied both host and translate regardless of flags.
    """

    site_host, site_translate, site_attribution = _website_defaults(
        approved_domain_for_url(db_session, getattr(manga, "source_url", None))
    )

    series_host = True if manga.may_host is None else bool(manga.may_host)
    series_translate = (
        True if manga.may_translate is None else bool(manga.may_translate)
    )
    taken_down = (manga.takedown_status or "none") == "taken_down"

    effective_host = series_host and site_host and not taken_down
    effective_translate = series_translate and site_translate and not taken_down

    return {
        "manga_id": manga.id,
        "may_host": effective_host,
        "may_translate": effective_translate,
        "attribution": manga.attribution or site_attribution,
        "takedown_status": manga.takedown_status or "none",
        "series_may_host": series_host,
        "series_may_translate": series_translate,
        "website_may_host": site_host,
        "website_may_translate": site_translate,
    }


def assert_may_host_url(db_session, url: str) -> None:
    """Ingestion gate: raise ``ApiError`` if the website forbids hosting.

    Only checks the website-level ``may_host`` flag; the *approval* check
    (whether the website is approved at all) lives in the ingestion path.
    """

    entry = approved_domain_for_url(db_session, url)
    if entry is not None and entry.may_host is not None and not entry.may_host:
        raise ApiError(
            ErrorCode.CONTENT_HOST_FORBIDDEN,
            MSG_HOST_FORBIDDEN,
            field="manga_url",
            details={"url": url},
        )


def assert_series_hostable(db_session, manga) -> None:
    """Read/rescrape gate: raise ``ApiError`` when the series may not be hosted.

    F-18: ``resolve_series_rights`` computed ``effective_host`` correctly but
    nothing consulted it on a read path -- a taken-down series remained
    fully browsable, and a rescrape could overwrite its stored pages with a
    freshly re-fetched copy. This is the series-level counterpart to
    ``assert_series_translatable``, applied to ``GET /manga/{id}``, its
    chapter-list/chapter-content siblings, and the rescrape endpoints.
    """

    rights = resolve_series_rights(db_session, manga)
    if rights["takedown_status"] == "taken_down":
        raise ApiError(
            ErrorCode.CONTENT_TAKEN_DOWN,
            MSG_TAKEN_DOWN,
            details={"manga_id": manga.id},
        )
    if not rights["may_host"]:
        raise ApiError(
            ErrorCode.CONTENT_HOST_FORBIDDEN,
            MSG_HOST_FORBIDDEN,
            details={"manga_id": manga.id},
        )


def assert_series_translatable(db_session, manga) -> None:
    """Translation gate: raise ``ApiError`` when translation is denied.

    Absolute — applies to every path and role, including the Permanent
    Administrator.
    """

    rights = resolve_series_rights(db_session, manga)
    if rights["takedown_status"] == "taken_down":
        raise ApiError(
            ErrorCode.CONTENT_TAKEN_DOWN,
            MSG_TAKEN_DOWN,
            details={"manga_id": manga.id},
        )
    if not rights["may_translate"]:
        raise ApiError(
            ErrorCode.CONTENT_TRANSLATE_FORBIDDEN,
            MSG_TRANSLATE_FORBIDDEN,
            details={"manga_id": manga.id},
        )
