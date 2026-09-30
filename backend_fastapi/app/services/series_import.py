"""Queueing a series import from the admin "Import & Scrape" form.

This runs in the API process and never scrapes: it validates the request,
approves the source website for administrators who may, and hands a job (with
the MangaUpdates link, series type, schedule and chapter cap attached) to the
Celery worker, which does the fetching.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import structlog
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models import ApprovedSourceDomain, Manga, User
from .manga_service import (
    MSG_DUPLICATE_MANGA_URL,
    MSG_UNAPPROVED_URL,
    _approved_entry_for_host,
    _host_is_approved,
    _url_dedupe_variants,
    schedule_series_scrape,
)

logger = structlog.get_logger(__name__)

SERIES_TYPES = {"manga", "manhwa", "manhua"}


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or "").strip().lower()


def is_approved(db: Session, url: str) -> bool:
    host = _host(url)
    return bool(host) and _host_is_approved(db, host)


def ensure_website_approved(
    db: Session,
    actor: Optional[User],
    url: str,
    *,
    base_url: Optional[str] = None,
    can_approve: Optional[bool] = None,
) -> None:
    """Make sure the site hosting ``url`` is approved for scraping.

    Approval is the Permanent Administrator's decision (SRS 1G.6.0), but it is
    delegable per person. Someone who holds ``approve_website`` and submits a
    site they typed in has approved it; anyone else gets the standard
    "website not approved" error.
    """

    host = _host(url)
    if not host:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "The series URL is not valid.", field="manga_url")
    if _host_is_approved(db, host):
        return

    if can_approve is None and actor is not None:
        from .permissions_service import has_permission

        can_approve = has_permission(db, actor, "approve_website")
    # A site an administrator already decided about (pending, testing or
    # disabled) is never silently switched on by a submission.
    already_decided = _approved_entry_for_host(db, host) is not None
    if not can_approve or actor is None or already_decided:
        raise ApiError(
            ErrorCode.WEBSITE_NOT_APPROVED,
            MSG_UNAPPROVED_URL,
            field="manga_url",
            details={"url": url, "domain": host},
        )

    domain = host[4:] if host.startswith("www.") else host
    parsed = urlparse(base_url or url)
    origin = f"{parsed.scheme or 'https'}://{parsed.netloc or host}"
    db.add(
        ApprovedSourceDomain(
            base_url=origin,
            domain=domain,
            label=domain,
            status="active",
            approved_by=actor.id,
            approved_at=datetime.utcnow(),
        )
    )
    db.commit()
    logger.info("website_approved_on_import", domain=domain, by=actor.id)


def interval_hours(value: Optional[int], unit: Optional[str]) -> Optional[int]:
    if not value:
        return None
    from .scheduled_checks_service import MAX_INTERVAL_HOURS, MIN_INTERVAL_HOURS

    hours = int(value) * (24 if (unit or "days") == "days" else 1)
    return max(MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, hours))


def build_options(payload: Any) -> Dict[str, Any]:
    """The job options the worker applies when it creates the series."""

    series_type = (payload.type or "").strip().lower()
    options: Dict[str, Any] = {
        "type": series_type if series_type in SERIES_TYPES else None,
        "title": (payload.title or "").strip() or None,
        "description": (payload.custom_description or "").strip() or None,
        "author": (payload.author or "").strip() or None,
        "cover_override": (payload.custom_cover_image or "").strip() or None,
        "mangaupdates_url": (payload.mangaupdates_url or "").strip() or None,
        "interval_hours": interval_hours(payload.scrape_interval_value, payload.scrape_interval_unit),
        "auto_scrape_enabled": payload.auto_scrape_enabled,
        "chapters_to_scrape": payload.chapters_to_scrape,
        "base_url": (payload.base_url or "").strip() or None,
        "ensure_parser": True,
    }
    return {k: v for k, v in options.items() if v is not None}


def queue_series_import(
    db: Session, actor: User, url: str, payload: Any, *, can_approve: bool
) -> Dict[str, Any]:
    from ..scrapers import presets

    host = _host(url)
    blocked = presets.unsupported_reason(host)
    if blocked:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"{host} cannot be scraped: it {blocked}.",
            field="manga_url",
            details={"url": url, "domain": host},
        )

    mu = (payload.mangaupdates_url or "").strip()
    if mu:
        from .mangaupdates_service import MangaUpdatesError, series_id_from_url

        try:
            series_id_from_url(mu)
        except MangaUpdatesError as exc:
            raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), field="mangaupdates_url")

    # Cheap duplicate check first, before anything is approved or queued.
    existing = db.query(Manga).filter(Manga.source_url.in_(_url_dedupe_variants(url))).first()
    if existing is not None:
        raise ApiError(
            ErrorCode.DUPLICATE_MANGA_URL,
            MSG_DUPLICATE_MANGA_URL,
            field="manga_url",
            details={"url": url, "existing_series_id": existing.id, "manga_id": existing.id},
        )

    # Approval is the admin saving the site's homepage (SRS 1G.6.0): a bare
    # series URL from an unknown site is still rejected; supplying the site's
    # base URL alongside it is the act of approving it (for people allowed to).
    base_url = (payload.base_url or "").strip()
    ensure_website_approved(
        db, actor, url, base_url=base_url or None, can_approve=bool(can_approve and base_url)
    )
    job = schedule_series_scrape(db, url, added_by=actor.id, options=build_options(payload))
    job["message"] = (
        "Import started. Chapters are being fetched from the source"
        + (" and metadata from MangaUpdates" if mu else "")
        + ". The series appears in the catalogue as soon as its chapter list is read; "
        "you will be notified when every chapter is in."
    )
    return job
