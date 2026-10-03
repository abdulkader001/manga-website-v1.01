"""Scheduled new-chapter detection (SRS 1G.12A).

Phase 2 of scraping: after initial ingestion, each series is checked
periodically and lightly for chapters newer than the last known one — a
single request to the chapter-list page, never a full rescrape. Checks run
at Low priority (1C.5.3), are staggered per website, and are deferred (never
dropped) when the queue is saturated.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import structlog
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import ApprovedSourceDomain, Manga, Setting

logger = structlog.get_logger(__name__)

DEFAULT_INTERVAL_HOURS = 10  # midpoint of the 8-12h default window (1G.12A.2)
DEFAULT_JITTER_HOURS = 2
MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 24 * 7  # 7 days

# Global caps (1G.12A.4) — platform-wide, not per-website.
GLOBAL_MAX_SCHEDULED_CHECKS = 50
GLOBAL_CHECK_QUEUE_CAP = 500


def _website_settings(entry: Optional[ApprovedSourceDomain]) -> Dict[str, Any]:
    settings = dict((entry.check_settings or {}) if entry else {})
    settings.setdefault("interval_hours", DEFAULT_INTERVAL_HOURS)
    settings.setdefault("jitter_hours", DEFAULT_JITTER_HOURS)
    settings.setdefault("max_concurrent", 5)
    settings.setdefault("quiet_hours", None)  # e.g. [2, 6] (UTC hour range)
    settings.setdefault("enabled", True)
    return settings


def _website_for(db: Session, manga: Manga) -> Optional[ApprovedSourceDomain]:
    from urllib.parse import urlparse

    hostname = (urlparse(manga.source_url).hostname or "").strip().lower()
    if not hostname:
        return None
    for entry in db.query(ApprovedSourceDomain).all():
        domain = (entry.domain or "").strip().lower()
        if domain and (hostname == domain or hostname.endswith("." + domain)):
            return entry
    return None


def _effective_interval_hours(manga: Manga, website_settings: Dict[str, Any]) -> int:
    """Per-series override takes priority over the website default (1G.12A.5)."""

    if manga.check_interval_hours:
        return manga.check_interval_hours
    return int(website_settings.get("interval_hours") or DEFAULT_INTERVAL_HOURS)


def schedule_next_check(
    db: Session, manga: Manga, *, now: Optional[datetime] = None
) -> datetime:
    """Compute and persist ``next_check_at`` with jitter (1G.12A.2)."""

    now = now or datetime.utcnow()
    website = _website_for(db, manga)
    settings = _website_settings(website)
    interval = _effective_interval_hours(manga, settings)
    jitter = float(settings.get("jitter_hours") or 0)
    offset_hours = interval + random.uniform(-jitter, jitter) if jitter else interval
    offset_hours = max(0.25, offset_hours)
    manga.next_check_at = now + timedelta(hours=offset_hours)
    return manga.next_check_at


def set_website_check_settings(
    db: Session,
    entry: ApprovedSourceDomain,
    *,
    interval_hours: Optional[int] = None,
    jitter_hours: Optional[float] = None,
    max_concurrent: Optional[int] = None,
    quiet_hours: Optional[list] = None,
    enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    settings = _website_settings(entry)
    if interval_hours is not None:
        if not (MIN_INTERVAL_HOURS <= interval_hours <= MAX_INTERVAL_HOURS):
            raise ValueError(
                f"interval_hours must be between {MIN_INTERVAL_HOURS} and "
                f"{MAX_INTERVAL_HOURS}"
            )
        settings["interval_hours"] = interval_hours
    if jitter_hours is not None:
        settings["jitter_hours"] = jitter_hours
    if max_concurrent is not None:
        settings["max_concurrent"] = max_concurrent
    if quiet_hours is not None:
        settings["quiet_hours"] = quiet_hours
    if enabled is not None:
        settings["enabled"] = enabled
    entry.check_settings = settings
    return settings


def set_series_check_override(
    db: Session, manga: Manga, *, interval_hours: Optional[int]
) -> None:
    """Per-series override (1G.12A.5); ``None`` clears it (use website default)."""

    if interval_hours is not None and not (
        MIN_INTERVAL_HOURS <= interval_hours <= MAX_INTERVAL_HOURS
    ):
        raise ValueError(
            f"interval_hours must be between {MIN_INTERVAL_HOURS} and "
            f"{MAX_INTERVAL_HOURS}"
        )
    manga.check_interval_hours = interval_hours


def _in_quiet_hours(quiet_hours, now: datetime) -> bool:
    if not quiet_hours or len(quiet_hours) != 2:
        return False
    start, end = quiet_hours
    hour = now.hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight


def due_series(
    db: Session, *, now: Optional[datetime] = None, limit: int = 100
) -> list[Manga]:
    """Series whose scheduled check is due, honouring quiet hours and the
    website's master enabled toggle (1G.12A.4)."""

    now = now or datetime.utcnow()
    candidates = (
        db.query(Manga)
        .filter(
            Manga.next_check_at.isnot(None),
            Manga.next_check_at <= now,
            Manga.auto_scrape_enabled.isnot(False),
            # A taken-down series is not fetched again (plan.md P1-2).
            or_(Manga.takedown_status.is_(None), Manga.takedown_status != "taken_down"),
        )
        .order_by(Manga.next_check_at.asc())
        .limit(limit * 2)
        .all()
    )
    due: list[Manga] = []
    for manga in candidates:
        website = _website_for(db, manga)
        settings = _website_settings(website)
        if not settings.get("enabled", True):
            continue
        if _in_quiet_hours(settings.get("quiet_hours"), now):
            continue
        due.append(manga)
        if len(due) >= limit:
            break
    return due


def _stat_key(day: datetime) -> str:
    return f"check_stats_{day.strftime('%Y%m%d')}"


def _record_stat(db: Session, outcome: str) -> None:
    """Daily rollup counters for the 1G.12A.8 dashboard (checked / new_chapters
    / failed), stored one row per UTC day — no new table needed."""

    import json

    key = _stat_key(datetime.utcnow())
    row = db.query(Setting).filter(Setting.key == key).first()
    counts = {"checked": 0, "new_chapters": 0, "failed": 0}
    if row and row.value:
        try:
            counts.update(json.loads(row.value))
        except ValueError:
            pass
    counts["checked"] += 1
    if outcome == "new_chapters_found":
        counts["new_chapters"] += 1
    elif outcome == "failed":
        counts["failed"] += 1
    payload = json.dumps(counts)
    if row is None:
        db.add(Setting(key=key, value=payload))
    else:
        row.value = payload


def dashboard_stats(db: Session, *, days: int = 1) -> Dict[str, int]:
    """Aggregate checked/new_chapters/failed over the last ``days`` UTC days
    (1G.12A.8: 'how many scheduled checks ran in the last 24 hours...')."""

    import json

    now = datetime.utcnow()
    totals = {"checked": 0, "new_chapters": 0, "failed": 0}
    for offset in range(days):
        key = _stat_key(now - timedelta(days=offset))
        row = db.query(Setting).filter(Setting.key == key).first()
        if row and row.value:
            try:
                counts = json.loads(row.value)
            except ValueError:
                continue
            for field in totals:
                totals[field] += int(counts.get(field, 0))
    return totals


def website_check_summary(db: Session, entry: ApprovedSourceDomain) -> Dict[str, Any]:
    """Per-website visibility (1G.12A.8): last check, next check, new
    chapters found in the last 7 days (approximated across its series)."""

    series = db.query(Manga).filter(Manga.source_url.ilike(f"%{entry.domain}%")).all()
    next_checks = [m.next_check_at for m in series if m.next_check_at]
    return {
        "domain": entry.domain,
        "last_check": (
            entry.last_health_check.isoformat() if entry.last_health_check else None
        ),
        "next_check": min(next_checks).isoformat() if next_checks else None,
        "series_tracked": len(series),
    }


def run_check(db: Session, manga: Manga) -> Dict[str, Any]:
    """The lightweight check (1G.12A.3): one request to the chapter-list page,
    ingest only new chapters, notify followers, reschedule."""

    from ..scrapers.base_scraper import BaseScraper
    from ..scrapers.errors import error_details_for
    from ..models import Chapter
    from urllib.parse import urlparse

    domain = urlparse(manga.source_url).netloc

    from .scraper_health_service import is_halted

    if is_halted(db, domain):
        schedule_next_check(db, manga)
        db.commit()
        return {"status": "skipped", "reason": "website_disabled"}

    existing_numbers = {
        float(c[0])
        for c in db.query(Chapter.chapter_number).filter_by(manga_id=manga.id).all()
        if c[0] is not None
    }

    scraper = BaseScraper(domain)
    try:
        manga_data = scraper.scrape_manga(manga.source_url, list(existing_numbers))
    except Exception as exc:
        logger.info("scheduled_check_failed", manga_id=manga.id, error=str(exc)[:200])
        from .scraper_health_service import record_failure

        record_failure(db, domain, exc)
        schedule_next_check(db, manga)
        _record_stat(db, "failed")
        db.commit()
        return {"status": "failed", "error": error_details_for(exc)}

    from .scraper_health_service import record_success

    record_success(db, domain)

    from ..models import Chapter
    from ..tasks.scraper_tasks import process_chapter_scrape
    from .chapter_grouping import build_chapter_rows, effective_layout, known_source_urls

    known_urls = known_source_urls(db.query(Chapter).filter_by(manga_id=manga.id).all())
    layout = effective_layout(manga)
    status_value = getattr(manga.status, "value", manga.status)
    source_chapters = [
        c
        for c in (manga_data.get("chapters") or [])
        if c.get("number") is not None
        and (layout["group_size"] > 1 or float(c["number"]) not in existing_numbers)
        and c.get("url") not in known_urls
    ]
    rows = build_chapter_rows(
        manga.id,
        source_chapters,
        group_size=layout["group_size"],
        consumed_urls=known_urls,
        flush=str(status_value or "") == "completed",
    )
    manga.last_scraped = datetime.utcnow()
    schedule_next_check(db, manga)

    if not rows:
        _record_stat(db, "no_new_chapters")
        db.commit()
        return {"status": "no_new_chapters"}

    created_ids = []
    for row in rows:
        chapter = Chapter(**row)
        db.add(chapter)
        db.flush()
        created_ids.append(chapter.id)
    db.commit()

    from ..utils.cache_invalidation import invalidate_manga_caches_sync

    invalidate_manga_caches_sync(manga.id)

    for chapter_id in created_ids:
        process_chapter_scrape.delay(chapter_id)

    from .series_alerts import notify_followers_of_new_chapters

    notify_followers_of_new_chapters(db, manga, (r["chapter_number"] for r in rows))
    _record_stat(db, "new_chapters_found")
    db.commit()
    return {"status": "new_chapters_found", "count": len(rows)}
