"""Reader-facing catalogue payloads (list, detail, chapter list).

Built in one place so the request path and the Celery cache-refresh tasks
(``tasks.manga_tasks``) always produce the same shape. Aggregates that need
other tables (ratings, chapter counts, period views) are computed in batches,
never per row.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import Text, cast, func, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Chapter,
    ChapterLike,
    Manga,
    MangaDailyView,
    MangaRating,
    ReadHistory,
    User,
)
from ..models.manga import chapter_number_value
from .manga_service import get_manga_list, normalize_multi

VIEW_DEDUPE_WINDOW = timedelta(minutes=30)


def _genres(db: Session) -> List[str]:
    genres_column = cast(Manga.genres, Text).label("genres_text")
    genre_set: set[str] = set()
    for row in db.query(genres_column).filter(Manga.genres.isnot(None)).distinct():
        text = getattr(row, "genres_text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, list):
            genre_set.update(entry for entry in parsed if isinstance(entry, str))
    return sorted(genre_set)


def enrich(db: Session, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add rating, chapter and period-view aggregates to serialized manga."""

    ids = [item["id"] for item in items if item.get("id") is not None]
    if not ids:
        return items

    ratings = {
        manga_id: (float(avg or 0), int(count or 0))
        for manga_id, avg, count in db.query(
            MangaRating.manga_id, func.avg(MangaRating.score), func.count(MangaRating.id)
        )
        .filter(MangaRating.manga_id.in_(ids))
        .group_by(MangaRating.manga_id)
    }

    chapter_stats = {}
    first_numbers = {}
    newest_added = {}
    for manga_id, count, latest, first, added in db.query(
        Chapter.manga_id,
        func.count(Chapter.id),
        func.max(Chapter.chapter_number),
        func.min(Chapter.chapter_number),
        func.max(Chapter.created_at),
    ).filter(Chapter.manga_id.in_(ids)).group_by(Chapter.manga_id):
        chapter_stats[manga_id] = (int(count or 0), latest)
        first_numbers[manga_id] = first
        newest_added[manga_id] = added

    # Ids of the first and newest chapter, so "Read now" / "latest chapter"
    # links open a real chapter. Only those two rows per series are fetched.
    edge_ids: Dict[tuple, int] = {}
    pairs = {(m, n) for m, (_, n) in chapter_stats.items() if n is not None}
    pairs |= {(m, n) for m, n in first_numbers.items() if n is not None}
    if pairs:
        for manga_id, number, chapter_id in (
            db.query(Chapter.manga_id, Chapter.chapter_number, Chapter.id)
            .filter(tuple_(Chapter.manga_id, Chapter.chapter_number).in_(list(pairs)))
            .order_by(Chapter.id)
        ):
            edge_ids.setdefault((manga_id, number), chapter_id)

    today = datetime.utcnow().date()
    period_views: Dict[int, Dict[str, int]] = {i: {"d": 0, "w": 0, "m": 0} for i in ids}
    for manga_id, day, views in db.query(
        MangaDailyView.manga_id, MangaDailyView.day, MangaDailyView.views
    ).filter(
        MangaDailyView.manga_id.in_(ids),
        MangaDailyView.day > today - timedelta(days=30),
    ):
        bucket = period_views[manga_id]
        age = (today - day).days
        bucket["m"] += views
        if age < 7:
            bucket["w"] += views
        if age == 0:
            bucket["d"] += views

    for item in items:
        manga_id = item["id"]
        avg, count = ratings.get(manga_id, (0.0, 0))
        item["rating"] = round(avg, 1)
        item["rating_count"] = count
        chapters_count, latest = chapter_stats.get(manga_id, (0, None))
        item["chapters_count"] = chapters_count
        latest_number = chapter_number_value(latest)
        item["latest_chapter_number"] = latest_number
        item["latest_chapter_id"] = edge_ids.get((manga_id, latest))
        item["first_chapter_id"] = edge_ids.get((manga_id, first_numbers.get(manga_id)))
        item["last_chapter_title"] = (
            f"Chapter {latest_number}" if latest_number is not None else None
        )
        # When the newest chapter arrived on this site (UTC, "Z"-suffixed so
        # every browser reads it the same way): drives "3h ago" on update cards.
        added = newest_added.get(manga_id)
        if isinstance(added, datetime):
            item["last_chapter_at"] = _utc_iso(added)
        views = period_views.get(manga_id, {"d": 0, "w": 0, "m": 0})
        item["daily_views"] = views["d"]
        item["weekly_views"] = views["w"]
        item["monthly_views"] = views["m"]
    return items


def build_list_payload(
    db: Session,
    *,
    q: Optional[str],
    type_: Optional[str],
    status_filter: Optional[str],
    genre: Optional[str],
    include: Optional[list[str]],
    exclude: Optional[list[str]],
    sort: str,
    page: int,
    per_page: int,
) -> Dict[str, Any]:
    include_genres = normalize_multi(include)
    exclude_genres = normalize_multi(exclude)
    if genre and genre not in include_genres:
        include_genres.insert(0, genre)

    items, total, _query = get_manga_list(
        db,
        q,
        type_,
        status_filter,
        include_genres,
        exclude_genres,
        sort,
        page,
        per_page,
    )
    return {
        "items": enrich(db, [m.to_dict() for m in items]),
        "total": total,
        "page": page,
        "per_page": per_page,
        "genres": _genres(db),
        "cache_hit": False,
    }


def build_detail_payload(db: Session, manga_id: int) -> Optional[Dict[str, Any]]:
    manga = db.get(Manga, manga_id)
    if manga is None:
        return None
    return enrich(db, [manga.to_dict()])[0]


def _utc_iso(value: Optional[datetime]) -> Optional[str]:
    """Stored times are naive UTC; mark them as such for the browser."""

    if value is None:
        return None
    if value.tzinfo is not None:
        return value.isoformat()
    return value.replace(microsecond=0).isoformat() + "Z"


def build_chapter_list_payload(
    db: Session, manga_id: int, order: str
) -> Optional[List[Dict[str, Any]]]:
    if db.get(Manga, manga_id) is None:
        return None

    query = db.query(Chapter).filter(Chapter.manga_id == manga_id)
    if order.lower() == "asc":
        query = query.order_by(Chapter.chapter_number.asc(), Chapter.id.asc())
    else:
        query = query.order_by(Chapter.chapter_number.desc(), Chapter.id.desc())
    chapters = query.all()

    likes = dict(
        db.query(ChapterLike.chapter_id, func.count(ChapterLike.id))
        .filter(ChapterLike.chapter_id.in_([c.id for c in chapters] or [0]))
        .group_by(ChapterLike.chapter_id)
        .all()
    )

    payload = []
    for chapter in chapters:
        released = chapter.created_at or chapter.scraped_at
        number = chapter_number_value(chapter.chapter_number)
        payload.append(
            {
                "id": chapter.id,
                "number": str(number) if number is not None else None,
                "chapter_number": number,
                "title": chapter.chapter_title or f"Chapter {number}",
                "url": chapter.chapter_url,
                "created_at": _utc_iso(released),
                "release_date": _utc_iso(released),
                "views": int(chapter.views or 0),
                "likes": int(likes.get(chapter.id, 0)),
                "page_count": len(chapter.pages or []),
                "ingestion_status": chapter.ingestion_status or "queued",
            }
        )
    return payload


ADMIN_ONLY_FIELDS = ("source_url", "mangaupdates_url", "scrape_layout")


def _hide_admin_fields(items: List[Dict[str, Any]], user: Optional[User]) -> None:
    """Drop the scraping sources unless the viewer is an admin."""

    from ..dependencies.auth import is_secondary_or_higher

    if user is not None and is_secondary_or_higher(user):
        return
    for item in items:
        for field in ADMIN_ONLY_FIELDS:
            item.pop(field, None)


def apply_viewer_fields(
    db: Session, items: Iterable[Dict[str, Any]], user: Optional[User]
) -> None:
    """Per-viewer fields that must never be cached across users."""

    items = list(items)
    _hide_admin_fields(items, user)
    for item in items:
        item["user_rating"] = None
    if user is None or not items:
        return
    ids = [item["id"] for item in items]
    for manga_id, score in db.query(MangaRating.manga_id, MangaRating.score).filter(
        MangaRating.user_id == user.id, MangaRating.manga_id.in_(ids)
    ):
        for item in items:
            if item["id"] == manga_id:
                item["user_rating"] = int(score)


def record_chapter_view(db: Session, chapter: Chapter, user: Optional[User]) -> None:
    """Count a read once per reader per chapter per 30 minutes.

    Must run BEFORE the caller refreshes the reader's history row, since the
    previous ``last_read_at`` is what identifies a repeat view.
    """

    if user is not None:
        recent = (
            db.query(ReadHistory.id)
            .filter(
                ReadHistory.user_id == user.id,
                ReadHistory.chapter_id == chapter.id,
                ReadHistory.last_read_at >= datetime.utcnow() - VIEW_DEDUPE_WINDOW,
            )
            .first()
        )
        if recent is not None:
            return

    today = datetime.utcnow().date()
    db.query(Chapter).filter(Chapter.id == chapter.id).update(
        {Chapter.views: Chapter.views + 1}, synchronize_session=False
    )
    db.query(Manga).filter(Manga.id == chapter.manga_id).update(
        {Manga.views: Manga.views + 1}, synchronize_session=False
    )
    if not _bump_daily_view(db, chapter.manga_id, today):
        try:
            with db.begin_nested():
                db.add(MangaDailyView(manga_id=chapter.manga_id, day=today, views=1))
        except IntegrityError:
            # Another reader created today's row first.
            _bump_daily_view(db, chapter.manga_id, today)


def _bump_daily_view(db: Session, manga_id: int, day: date) -> int:
    return (
        db.query(MangaDailyView)
        .filter(MangaDailyView.manga_id == manga_id, MangaDailyView.day == day)
        .update({MangaDailyView.views: MangaDailyView.views + 1}, synchronize_session=False)
    )
