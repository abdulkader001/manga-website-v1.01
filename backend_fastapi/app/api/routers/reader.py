"""Reader engagement endpoints: ratings, chapter likes, broken-chapter
reports, site announcements, bookmark import and the signed image proxy."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.site_functions import require_function
from ...dependencies.auth import (
    get_current_user,
    get_optional_user,
    is_secondary_or_higher,
)
from ...models import (
    Announcement,
    Bookmark,
    Chapter,
    ChapterLike,
    ChapterReport,
    Manga,
    MangaRating,
    User,
)
from ...services import image_proxy
from ...utils.cache_invalidation import ainvalidate_manga_caches
from ...utils.endpoint_limiter import async_endpoint_limiter

logger = structlog.get_logger("backend_fastapi.reader")

router = APIRouter(tags=["reader"])

REPORT_TYPES = {
    "Broken Chapter",
    "Missing Pages",
    "Wrong Page Order",
    "Wrong Chapter",
    "Low Quality Images",
    "Duplicate Chapter",
    "Translation Issue",
    # Options the reader UI offers.
    "Missing Images",
    "Missing Text",
    "Slow Loading",
    "Other",
}


# ---------------------------------------------------------------------------
# Ratings & likes
# ---------------------------------------------------------------------------


class RatingPayload(BaseModel):
    rating: int = Field(..., ge=1, le=10)


def _rating_summary(db: Session, manga_id: int) -> Dict[str, Any]:
    avg, count = (
        db.query(func.avg(MangaRating.score), func.count(MangaRating.id))
        .filter(MangaRating.manga_id == manga_id)
        .one()
    )
    return {"rating": round(float(avg or 0), 1), "rating_count": int(count or 0)}


@router.post("/manga/{manga_id}/rate")
async def rate_manga(
    request: Request,
    manga_id: int,
    payload: RatingPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"rate_manga:{current_user.id}", limit=60, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _save() -> None:
        if db.get(Manga, manga_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found")

        row = (
            db.query(MangaRating)
            .filter(MangaRating.manga_id == manga_id, MangaRating.user_id == current_user.id)
            .first()
        )
        if row is None:
            db.add(MangaRating(manga_id=manga_id, user_id=current_user.id, score=payload.rating))
        else:
            row.score = payload.rating
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            db.query(MangaRating).filter(
                MangaRating.manga_id == manga_id, MangaRating.user_id == current_user.id
            ).update({MangaRating.score: payload.rating})
            db.commit()

    await run_in_db_threadpool(_save)
    await ainvalidate_manga_caches(getattr(request.app.state, "redis", None), manga_id)

    def _work():
        summary = _rating_summary(db, manga_id)
        return {
            "success": True,
            "user_rating": payload.rating,
            **summary,
            "message": f"You rated {payload.rating} / 10!",
        }

    return await run_in_db_threadpool(_work)


@router.post("/chapters/{chapter_id}/like")
async def toggle_chapter_like(
    request: Request,
    chapter_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"like_chapter:{current_user.id}", limit=300, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        if db.get(Chapter, chapter_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

        existing = (
            db.query(ChapterLike)
            .filter(ChapterLike.chapter_id == chapter_id, ChapterLike.user_id == current_user.id)
            .first()
        )
        if existing is not None:
            db.delete(existing)
            liked = False
        else:
            db.add(ChapterLike(chapter_id=chapter_id, user_id=current_user.id))
            liked = True
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            liked = True
        likes = (
            db.query(func.count(ChapterLike.id))
            .filter(ChapterLike.chapter_id == chapter_id)
            .scalar()
            or 0
        )
        return {"success": True, "liked": liked, "likes": int(likes)}

    return await run_in_db_threadpool(_work)


# ---------------------------------------------------------------------------
# Broken-chapter reports
# ---------------------------------------------------------------------------


class ChapterReportPayload(BaseModel):
    report_type: str = Field("Broken Chapter", max_length=64)
    details: Optional[str] = Field(None, max_length=2000)


def report_to_dict(report: ChapterReport, db: Session) -> Dict[str, Any]:
    chapter = db.get(Chapter, report.chapter_id)
    manga = db.get(Manga, report.manga_id)
    reporter = db.get(User, report.user_id) if report.user_id else None
    from ...models.manga import chapter_number_value

    return {
        "id": report.id,
        "chapter_id": report.chapter_id,
        "manga_id": report.manga_id,
        "manga_title": manga.title if manga else None,
        "chapter_number": chapter_number_value(chapter.chapter_number) if chapter else None,
        "chapter_title": chapter.chapter_title if chapter else None,
        "report_type": report.report_type,
        "details": report.details,
        "status": report.status,
        "reporter": (reporter.username or reporter.name) if reporter else None,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "resolved_at": report.resolved_at.isoformat() if report.resolved_at else None,
    }


@router.post(
    "/chapters/{chapter_id}/report",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_function("chapter_reports"))],
)
async def report_chapter(
    request: Request,
    chapter_id: int,
    payload: ChapterReportPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"report_chapter:{current_user.id}", limit=20, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        chapter = db.get(Chapter, chapter_id)
        if chapter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

        report_type = payload.report_type if payload.report_type in REPORT_TYPES else "Other"
        details = (payload.details or "").strip() or None

        duplicate = (
            db.query(ChapterReport)
            .filter(
                ChapterReport.chapter_id == chapter_id,
                ChapterReport.user_id == current_user.id,
                ChapterReport.status == "open",
            )
            .first()
        )
        if duplicate is not None:
            duplicate.report_type = report_type
            duplicate.details = details
            report = duplicate
        else:
            report = ChapterReport(
                chapter_id=chapter_id,
                manga_id=chapter.manga_id,
                user_id=current_user.id,
                report_type=report_type,
                details=details,
            )
            db.add(report)
        db.commit()
        db.refresh(report)

        from ...services.notification_service import notify_async

        notify_async(
            type="chapter.reported",
            title=f"Chapter report: {report_type}",
            body=(
                f"{chapter.manga.title if chapter.manga else 'A series'} — "
                f"chapter {report_to_dict(report, db)['chapter_number']}: "
                f"{details or report_type}"
            ),
            target_type="chapter",
            target_id=chapter_id,
            # report_type drives the badge (broken / wrong / missing image or
            # text) on the Notifications page.
            data={"report_id": report.id, "manga_id": chapter.manga_id, "report_type": report_type},
            dedup_key=f"chapter_report:{chapter_id}",
        )
        return {"success": True, "report": report_to_dict(report, db)}

    return await run_in_db_threadpool(_work)


@router.get("/chapters/{chapter_id}/reports")
def chapter_alerts(
    chapter_id: int,
    viewer: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Open reports for one chapter: staff only (admin / sub-admin).

    Readers get an empty answer -- broken-chapter reports are operational
    information, not something shown to the public."""

    if viewer is None or not is_secondary_or_higher(viewer):
        return {"active_alert": None, "count": 0}

    open_reports = (
        db.query(ChapterReport)
        .filter(ChapterReport.chapter_id == chapter_id, ChapterReport.status == "open")
        .order_by(ChapterReport.created_at.desc())
        .all()
    )
    active_alert = None
    if open_reports:
        latest = open_reports[0]
        active_alert = {
            "report_type": latest.report_type,
            "count": len(open_reports),
            "message": (
                f"{latest.report_type} reported — our team has been notified and "
                "is working on a fix."
            ),
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        }
    return {
        "active_alert": active_alert,
        "count": len(open_reports),
        "reports": [report_to_dict(r, db) for r in open_reports],
    }


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


def announcement_to_dict(item: Announcement) -> Dict[str, Any]:
    return {
        "id": item.id,
        "type": item.type,
        "title": item.title,
        "text": item.message,
        "message": item.message,
        "enabled": bool(item.enabled),
        "is_popup": bool(item.is_popup),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@router.get("/announcements")
def list_announcements(db: Session = Depends(get_db)) -> Dict[str, Any]:
    items = (
        db.query(Announcement)
        .filter(Announcement.enabled.is_(True))
        .order_by(Announcement.created_at.desc(), Announcement.id.desc())
        .limit(20)
        .all()
    )
    popup = next((a for a in items if a.is_popup), None)
    return {
        "announcements": [announcement_to_dict(a) for a in items],
        "popup": (
            {
                "id": popup.id,
                "title": popup.title,
                "message": popup.message,
                "type": popup.type,
            }
            if popup
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Bookmark backup import
# ---------------------------------------------------------------------------


class BookmarkImportPayload(BaseModel):
    bookmarks: List[Dict[str, Any]] = Field(default_factory=list, max_length=5000)


@router.post("/bookmarks/import")
async def import_bookmarks(
    request: Request,
    payload: BookmarkImportPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"bookmark_import:{current_user.id}", limit=10, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        wanted: set[tuple[int, Optional[int]]] = set()
        for entry in payload.bookmarks:
            manga_id = entry.get("manga_id", entry.get("mangaId"))
            chapter_id = entry.get("chapter_id", entry.get("chapterId"))
            try:
                manga_id = int(manga_id)
                chapter_id = int(chapter_id) if chapter_id not in (None, "") else None
            except (TypeError, ValueError):
                continue
            wanted.add((manga_id, chapter_id))

        if not wanted:
            return {"success": True, "imported": 0, "skipped": 0}

        manga_ids = {m for m, _ in wanted}
        existing_manga = {
            row[0] for row in db.query(Manga.id).filter(Manga.id.in_(manga_ids))
        }
        chapter_ids = {c for _, c in wanted if c is not None}
        valid_chapters = {
            (row.id, row.manga_id)
            for row in db.query(Chapter.id, Chapter.manga_id).filter(Chapter.id.in_(chapter_ids or {0}))
        }
        already = {
            (row.manga_id, row.chapter_id)
            for row in db.query(Bookmark.manga_id, Bookmark.chapter_id).filter(
                Bookmark.user_id == current_user.id
            )
        }

        imported = 0
        for manga_id, chapter_id in wanted:
            if manga_id not in existing_manga:
                continue
            if chapter_id is not None and (chapter_id, manga_id) not in valid_chapters:
                continue
            if (manga_id, chapter_id) in already:
                continue
            db.add(Bookmark(user_id=current_user.id, manga_id=manga_id, chapter_id=chapter_id))
            imported += 1
        db.commit()
        return {"success": True, "imported": imported, "skipped": len(wanted) - imported}

    return await run_in_db_threadpool(_work)


# ---------------------------------------------------------------------------
# Signed image proxy
# ---------------------------------------------------------------------------


@router.get("/manga/covers/{filename}")
def serve_cover(filename: str) -> Response:
    from ...services import cover_service

    target = cover_service.path_for(filename)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return FileResponse(
        target,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/manga/pages/{manga_id}/{chapter_id}/{filename}")
def serve_page_image(manga_id: int, chapter_id: int, filename: str) -> Response:
    """A stored chapter page (WebP, or the source's own JPEG/PNG/WebP when it
    needed no change). Names are content-addressed,
    so browsers and CDNs may cache them forever."""

    from ...services import page_image_service

    target = page_image_service.path_for(manga_id, chapter_id, filename)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return FileResponse(
        target,
        # WebP when re-encoded; a source JPEG/PNG kept as-is keeps its type.
        media_type=page_image_service.media_type_for(target),
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/images/proxy")
def proxy_image(
    t: str | None = Query(None, max_length=8192),
    u: str | None = Query(None, max_length=4096),
    r: str | None = Query(None, max_length=2048),
    s: str | None = Query(None, max_length=64),
) -> Response:
    if t:
        decoded = image_proxy.decode_token(t)
    elif u and r is not None and s:
        decoded = image_proxy.decode_request(u, r, s)
    else:
        decoded = None
    if decoded is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_signature")
    url, referer = decoded

    from ...scrapers.http_client import USER_AGENTS
    from ...services.pinned_fetch import ResponseTooLarge, get_pinned_following_redirects
    from ...services.url_guard import validate_scrape_url_resolved
    from ...services import page_image_service

    try:
        upstream = get_pinned_following_redirects(
            url,
            lambda candidate: validate_scrape_url_resolved(candidate, db_session=None),
            timeout=20,
            headers={
                "User-Agent": USER_AGENTS[0],
                **({"Referer": referer} if referer else {}),
                "Accept": page_image_service.ORIGINAL_FIRST_ACCEPT,
            },
            max_bytes=image_proxy.MAX_PROXY_IMAGE_BYTES,
        )
    except ResponseTooLarge:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="image_too_large")
    except requests.exceptions.InvalidURL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_image_url")
    except requests.exceptions.RequestException as exc:
        logger.warning("image_proxy_fetch_failed", error=str(exc)[:200])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="image_fetch_failed")

    content_type = (upstream.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if upstream.status_code != 200 or not content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="image_fetch_failed")
    if content_type == "image/svg+xml":
        # SVG can carry script; never serve it from our origin.
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="unsupported_image")

    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=604800, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        },
    )


__all__ = ["router", "report_to_dict", "announcement_to_dict", "REPORT_TYPES"]
