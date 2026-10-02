"""Rescrape flows: the chapter Fix button and staged full-series rescrape
(SRS 1G.12).

Chapter Fix (1G.12.2): one chapter only, deduplicated atomically (1G.12.2A),
with the "source may be broken" warning window (1G.12.2B). Everyone who
clicked is subscribed to the completion notification.

Full-series rescrape (1G.12.3/1G.12.4): staged, validated, snapshot-backed
replacement that can never empty a series. Chapter rows are updated in place
keyed by chapter number, so reading history and bookmarks — which reference
chapter rows, not page records — survive untouched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import structlog
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models import AdminAuditLog, Chapter, Manga, ScrapingJob, Setting
from ..scrapers.concurrency import acquire_lock

logger = structlog.get_logger(__name__)

# How soon after a successful rescrape a second Fix click triggers the
# "source may be broken" banner instead of silently re-running (1G.12.2B).
# Admin-configurable via the fix_rebanner_window_minutes setting.
DEFAULT_REBANNER_WINDOW_MINUTES = 60
# Rescrape-then-still-broken cycles before the single consolidated PA alert.
CONSOLIDATED_ALERT_AFTER = 3

_ACTIVE_STATUSES = ("queued", "in_progress", "processing")


def _rebanner_window(db: Session) -> timedelta:
    row = db.query(Setting).filter(Setting.key == "fix_rebanner_window_minutes").first()
    try:
        minutes = int(row.value) if row and row.value else None
    except (TypeError, ValueError):
        minutes = None
    if not minutes or minutes < 1:
        minutes = DEFAULT_REBANNER_WINDOW_MINUTES
    return timedelta(minutes=minutes)


def _active_job_for_chapter(db: Session, chapter: Chapter) -> Optional[ScrapingJob]:
    return (
        db.query(ScrapingJob)
        .filter(
            ScrapingJob.source_url == chapter.chapter_url,
            ScrapingJob.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(ScrapingJob.id.desc())
        .first()
    )


def _fix_count_key(chapter_id: int) -> str:
    return f"fix_cycle_count_{chapter_id}"


def _bump_fix_cycles(db: Session, chapter: Chapter) -> int:
    """Count rescrape-then-fix-again cycles inside the banner window and send
    ONE consolidated PA alert when they pile up (1G.12.2B)."""

    key = _fix_count_key(chapter.id)
    row = db.query(Setting).filter(Setting.key == key).first()
    try:
        count = int(row.value) if row and row.value else 0
    except (TypeError, ValueError):
        count = 0
    count += 1
    if row is None:
        db.add(Setting(key=key, value=str(count)))
    else:
        row.value = str(count)

    if count == CONSOLIDATED_ALERT_AFTER:
        from .notification_service import notify_async

        notify_async(
            type="chapter.repeatedly_broken",
            title=f"Chapter {chapter.chapter_number} rescripted repeatedly",
            body=(
                f"Chapter {chapter.chapter_number} (id {chapter.id}) has been "
                f"rescripted {count} times in quick succession and is still "
                "being reported broken. The source images themselves may be "
                "damaged or scrambled — inspect the source page directly: "
                f"{chapter.chapter_url}"
            ),
            data={
                "chapter_id": chapter.id,
                "cycles": count,
                "manga_id": chapter.manga_id,
            },
            target_type="chapter",
            target_id=chapter.id,
        )
    return count


def _reset_fix_cycles(db: Session, chapter_id: int) -> None:
    row = db.query(Setting).filter(Setting.key == _fix_count_key(chapter_id)).first()
    if row is not None:
        row.value = "0"


def fix_chapter(
    db: Session,
    chapter: Chapter,
    *,
    actor_id: int,
    force: bool = False,
) -> Dict[str, Any]:
    """The Fix button (1G.12.2). Returns one of:

    - ``{"status": "already_in_progress", ...}`` — an active job exists; the
      clicker is subscribed to its completion notification, no second job is
      created (1G.12.2A).
    - ``{"status": "recently_fixed", "banner": ...}`` — a successful rescrape
      finished inside the configurable window; the banner warns but does not
      block (pass ``force=True`` to rescrape anyway) (1G.12.2B).
    - ``{"status": "queued", "job": ...}`` — a single high-priority job was
      created; the clicker will be notified on completion.
    """

    # Atomic dedupe (1G.12.2A): one lock per chapter so two simultaneous
    # clicks cannot both pass the existence check.
    with acquire_lock(f"fix_click:{chapter.id}", timeout=30, wait_for=5) as acquired:
        if not acquired:
            raise ApiError(
                ErrorCode.RATE_LIMITED,
                "Another Fix request for this chapter is being processed; "
                "try again in a moment.",
            )

        existing = _active_job_for_chapter(db, chapter)
        if existing is not None:
            subscribers = list(existing.subscribers or [])
            if actor_id not in subscribers:
                subscribers.append(actor_id)
                existing.subscribers = subscribers
                db.commit()
            return {
                "status": "already_in_progress",
                "message": (
                    "This chapter is already being rescripted. You'll be "
                    "notified when it's done."
                ),
                "job_id": existing.id,
            }

        # 1G.12.2B: recently rescripted successfully? Warn, don't block.
        window = _rebanner_window(db)
        recently_fixed = (
            chapter.scraped_at is not None
            and (chapter.ingestion_status or "") == "complete"
            and datetime.utcnow() - chapter.scraped_at < window
        )
        if recently_fixed and not force:
            return {
                "status": "recently_fixed",
                "banner": (
                    "This chapter was rescripted "
                    f"{int((datetime.utcnow() - chapter.scraped_at).total_seconds() // 60)} "
                    "minutes ago and the images were fetched successfully. If "
                    "the content still appears broken, the source images "
                    "themselves may be damaged or scrambled. You can rescrape "
                    "again, or check the source website directly."
                ),
                "options": ["rescrape_anyway", "view_source_page", "dismiss"],
                "source_url": chapter.chapter_url,
            }

        if recently_fixed and force:
            _bump_fix_cycles(db, chapter)

        job = ScrapingJob(
            manga_id=chapter.manga_id,
            source_url=chapter.chapter_url,
            status="queued",
            last_chapter_number=(
                str(chapter.chapter_number)
                if chapter.chapter_number is not None
                else None
            ),
            subscribers=[actor_id],
        )
        db.add(job)
        db.commit()
        db.refresh(job)

    # Queued at HIGH priority — a person is waiting (1C.5.3).
    from ..tasks.scraper_tasks import process_chapter_scrape

    process_chapter_scrape.apply_async(args=[chapter.id], priority=0)

    return {
        "status": "queued",
        "job_id": job.id,
        "message": "Re-fetching this chapter from the source.",
    }


def notify_fix_subscribers(
    db: Session, chapter: Chapter, *, success: bool, error: Optional[str] = None
) -> None:
    """Completion notification to EVERYONE who clicked Fix (1G.12.2A), and
    job bookkeeping for the chapter's active rescrape job."""

    job = _active_job_for_chapter(db, chapter)
    if job is None:
        return
    job.status = "success" if success else "failed"
    if error:
        job.error = error

    from .notification_service import notify_async

    for user_id in job.subscribers or []:
        if success:
            notify_async(
                type="chapter.fix_completed",
                title=f"Chapter {chapter.chapter_number} was rescripted",
                body=(
                    f"Chapter {chapter.chapter_number} has been re-fetched "
                    "from the source. Refresh to see the fixed chapter."
                ),
                user_id=user_id,
                data={
                    "chapter_id": chapter.id,
                    "success": True,
                    "manga_id": chapter.manga_id,
                },
                target_type="chapter",
                target_id=chapter.id,
            )
        else:
            notify_async(
                type="chapter.fix_failed",
                title=f"Chapter {chapter.chapter_number} rescrape failed",
                body=(
                    f"Re-fetching chapter {chapter.chapter_number} failed: "
                    f"{error or 'unknown error'}. Existing pages were left "
                    "untouched. The parser may need repair."
                ),
                user_id=user_id,
                data={
                    "chapter_id": chapter.id,
                    "success": False,
                    "manga_id": chapter.manga_id,
                },
                target_type="chapter",
                target_id=chapter.id,
            )
    if success:
        _reset_fix_cycles(db, chapter.id)
    db.commit()


# ---------------------------------------------------------------------------
# Full-series staged rescrape (1G.12.3 / 1G.12.4)
# ---------------------------------------------------------------------------


def _queue_mirroring(manga_id: int) -> None:
    """Compress and self-host the (new) pictures of a series in the background."""

    try:
        from ..tasks.scraper_tasks import mirror_series_pages

        mirror_series_pages.delay(manga_id)
    except Exception:  # pragma: no cover - broker unavailable
        pass


def _snapshot_key(manga_id: int) -> str:
    return f"series_snapshot_{manga_id}"


def _store_snapshot(db: Session, manga: Manga) -> None:
    """Keep ONE prior snapshot for rollback (1G.12.4)."""

    chapters = (
        db.query(Chapter)
        .filter(Chapter.manga_id == manga.id)
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    snapshot = {
        "taken_at": datetime.utcnow().isoformat(),
        "chapters": [
            {
                "chapter_number": str(c.chapter_number),
                "chapter_title": c.chapter_title,
                "chapter_url": c.chapter_url,
                "pages": c.pages or [],
                "source_pages": c.source_pages or [],
            }
            for c in chapters
        ],
    }
    key = _snapshot_key(manga.id)
    row = db.query(Setting).filter(Setting.key == key).first()
    payload = json.dumps(snapshot)
    if row is None:
        db.add(Setting(key=key, value=payload))
    else:
        row.value = payload


def rollback_series(db: Session, manga: Manga) -> Dict[str, Any]:
    """Restore the prior snapshot (Permanent Administrator action, 1G.12.4)."""

    row = db.query(Setting).filter(Setting.key == _snapshot_key(manga.id)).first()
    if row is None or not row.value:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No prior snapshot exists for this series.",
            field="series_id",
        )
    snapshot = json.loads(row.value)
    restored = 0
    by_number = {
        str(c.chapter_number): c
        for c in db.query(Chapter).filter(Chapter.manga_id == manga.id).all()
    }
    for entry in snapshot.get("chapters", []):
        chapter = by_number.get(str(entry["chapter_number"]))
        if chapter is None:
            continue
        # Prefer the source URLs: our stored copies may have been replaced by
        # the rescrape being rolled back. They are re-mirrored afterwards.
        restored_pages = entry.get("source_pages") or entry.get("pages") or []
        chapter.pages = restored_pages
        chapter.source_pages = None
        chapter.pages_bytes = None
        chapter.chapter_title = entry.get("chapter_title")
        chapter.ingestion_status = "complete" if restored_pages else "queued"
        restored += 1
    db.commit()
    _queue_mirroring(manga.id)
    return {"restored_chapters": restored, "taken_at": snapshot.get("taken_at")}


def _audit_rescrape_outcome(
    db: Session,
    *,
    actor_id: Optional[int],
    manga: Manga,
    chapter_count: int,
    outcome: str,
    detail: str,
) -> None:
    """Every full rescrape audited with actor, series, chapter count, outcome
    (1G.12.3). Written directly (no HTTP Request available inside the Celery
    task that drives this), mirroring the request-free pattern already used
    by ``log_role_change``."""

    db.add(
        AdminAuditLog(
            user_id=actor_id,
            action="RESCRAPE_SERIES_OUTCOME",
            metadata_json={
                "series_id": manga.id,
                "series_title": manga.title,
                "chapter_count": chapter_count,
                "outcome": outcome,
                "detail": detail,
            },
            operator="admin_router",
        )
    )


def run_staged_rescrape(
    db: Session, manga_id: int, *, actor_id: Optional[int] = None
) -> Dict[str, Any]:
    """Scrape into a staging area, validate, then swap (1G.12.4).

    Validation: the rescrape must produce at least as many chapters as exist,
    and every staged chapter must have pages. On failure NOTHING is changed
    and the report says exactly what was wrong. On success, chapter rows are
    updated in place (bookmarks/history preserved) and one prior snapshot is
    kept for rollback. ``actor_id`` is the administrator who initiated the
    rescrape (1G.12.3: "notification to the initiating administrator" and
    the audit trail's actor) — it is not necessarily the Permanent
    Administrator, so completion is routed to that specific person rather
    than only the PA's bell.
    """

    from ..scrapers.base_scraper import BaseScraper
    from urllib.parse import urlparse

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Series not found", field="series_id")

    domain = urlparse(manga.source_url).netloc
    existing_chapters = db.query(Chapter).filter(Chapter.manga_id == manga.id).count()

    manga.ingestion_status = "scraping"
    db.commit()

    scraper = BaseScraper(domain)
    if actor_id is not None:
        # Started by a person: the Scraper AI only helps the main admin.
        from ..models import User
        from ..scrapers.source_pipeline import may_use_scraper_ai

        scraper.allow_ai = may_use_scraper_ai(db, db.get(User, actor_id))

    def _abort(reason: str) -> Dict[str, Any]:
        manga.ingestion_status = "complete"
        manga.last_error = reason
        from .notification_service import notify_async
        from .scraper_health_service import record_failure

        notify_async(
            type="series.rescrape_aborted",
            title=f"Rescrape of '{manga.title}' aborted — no data changed",
            body=reason,
            user_id=actor_id,
            data={"series_id": manga.id},
            target_type="series",
            target_id=manga.id,
        )
        record_failure(db, domain, Exception(reason))
        _audit_rescrape_outcome(
            db,
            actor_id=actor_id,
            manga=manga,
            chapter_count=existing_chapters,
            outcome="aborted",
            detail=reason,
        )
        db.commit()
        return {"status": "aborted", "reason": reason}

    # ---- Stage 1: metadata + chapter list -------------------------------
    try:
        manga_data = scraper.scrape_manga(manga.source_url)
    except Exception as exc:
        return _abort(f"Series page scrape failed: {exc}. No data was changed.")

    staged_chapters = manga_data.get("chapters") or []
    if len(staged_chapters) < existing_chapters:
        return _abort(
            f"Rescrape produced {len(staged_chapters)} chapters where "
            f"{existing_chapters} exist. The parser is likely broken. "
            "No data was changed."
        )

    # ---- Stage 2: fetch every chapter's pages into staging --------------
    staged_pages: Dict[str, Dict[str, Any]] = {}
    for idx, c_data in enumerate(staged_chapters, start=1):
        c_url = c_data.get("url")
        if not c_url:
            return _abort(
                f"Chapter {idx} of {len(staged_chapters)} has no URL in the "
                "chapter list. No data was changed."
            )
        try:
            chapter_data = scraper.scrape_chapter(c_url)
        except Exception as exc:
            return _abort(
                f"Rescrape failed at chapter {idx} of {len(staged_chapters)} "
                f"({c_url}): {exc}. No data was changed."
            )
        pages = chapter_data.get("pages") or []
        if not pages:
            return _abort(
                f"Chapter {idx} of {len(staged_chapters)} produced no pages. "
                "No data was changed."
            )
        staged_pages[str(c_data.get("number", 0.0))] = {
            "url": c_url,
            "title": c_data.get("title", ""),
            "pages": pages,
        }

    # ---- Validation passed: snapshot, then swap in place ----------------
    _store_snapshot(db, manga)

    by_number = {
        str(float(c.chapter_number)) if c.chapter_number is not None else "0.0": c
        for c in db.query(Chapter).filter(Chapter.manga_id == manga.id).all()
    }
    updated = 0
    created = 0
    for number, staged in staged_pages.items():
        key = str(float(number))
        chapter = by_number.get(key)
        if chapter is None:
            chapter = Chapter(
                manga_id=manga.id,
                chapter_number=float(number),
                chapter_url=staged["url"],
                chapter_title=staged["title"],
            )
            db.add(chapter)
            created += 1
        else:
            # In-place update: the row (and its id) survives, so reading
            # history and bookmarks that reference it are preserved.
            updated += 1
        chapter.pages = staged["pages"]
        chapter.source_pages = None
        chapter.pages_bytes = None
        chapter.chapter_title = staged["title"] or chapter.chapter_title
        chapter.scraped_at = datetime.utcnow()
        chapter.ingestion_status = "complete"

    manga.ingestion_status = "complete"
    manga.last_scraped = datetime.utcnow()
    manga.last_error = None
    db.commit()
    _queue_mirroring(manga.id)

    from .notification_service import notify_async
    from .scraper_health_service import record_success

    record_success(db, domain)
    notify_async(
        type="series.rescraped",
        title=f"'{manga.title}' was fully rescripted",
        body=(
            f"All {len(staged_pages)} chapters of '{manga.title}' were "
            "re-fetched and replaced. Reading history and bookmarks are "
            "preserved. One prior snapshot is retained for rollback."
        ),
        user_id=actor_id,
        data={"series_id": manga.id, "chapters": len(staged_pages)},
        target_type="series",
        target_id=manga.id,
    )
    _audit_rescrape_outcome(
        db,
        actor_id=actor_id,
        manga=manga,
        chapter_count=len(staged_pages),
        outcome="success",
        detail=f"updated={updated} created={created}",
    )
    db.commit()
    return {
        "status": "success",
        "chapters_total": len(staged_pages),
        "chapters_updated": updated,
        "chapters_created": created,
    }
