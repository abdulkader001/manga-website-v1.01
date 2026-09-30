from typing import Iterable, List, Optional
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, cast, Text
from sqlalchemy.dialects.postgresql import JSONB
from ..models import Manga
from ..core.api_errors import ApiError, ErrorCode

# User-facing messages mandated by the SRS (Part 1G). Kept as constants so the
# exact wording is asserted by tests and cannot drift.
MSG_DUPLICATE_MANGA_URL = "Invalid — this URL has already been added for mangas"
# SRS 1B.4.2 canonical message for WEBSITE_NOT_APPROVED. Opens with the exact
# 1G.2.2 string "Unidentified or unmatched URL".
MSG_UNAPPROVED_URL = (
    "Unidentified or unmatched URL. This website has not been approved. "
    "Only the Permanent Administrator can add a source website."
)


def _approved_entry_for_host(db_session, hostname: str):
    """Return the ``ApprovedSourceDomain`` matching ``hostname``, or ``None``.

    A website is approved only when the Permanent Administrator has saved its
    homepage URL (SRS 1G.6.0). Matching accepts the exact host or any subdomain
    of an approved apex domain (``colamanga.com`` approves ``www.colamanga.com``).
    A working parser is never sufficient on its own — "a parser is not
    permission" (SRS 1G.3).
    """

    from ..models import ApprovedSourceDomain

    hostname = (hostname or "").strip().lower()
    if not hostname:
        return None

    for entry in db_session.query(ApprovedSourceDomain).all():
        domain = (entry.domain or "").strip().lower()
        if not domain:
            continue
        if hostname == domain or hostname.endswith("." + domain):
            return entry
    return None


def _host_is_approved(db_session, hostname: str) -> bool:
    """True when the host's website exists AND accepts submissions (1G.6.3).

    Only ``active`` and ``degraded`` websites accept manga URLs; ``pending``,
    ``testing``, and ``disabled`` reject them the same as an unknown domain.
    """

    entry = _approved_entry_for_host(db_session, hostname)
    if entry is None:
        return False
    return (entry.status or "active") in ("active", "degraded")


def normalize_multi(values: Optional[Iterable[str]]) -> List[str]:
    if not values:
        return []

    seen: set[str] = set()
    normalized: list[str] = []
    for raw in values:
        if not raw:
            continue
        parts = [part.strip() for part in str(raw).split(",")]
        for part in parts:
            if not part:
                continue
            if part not in seen:
                seen.add(part)
                normalized.append(part)
    return normalized


def _genre_like_pattern(value: str) -> str:
    return f'%"{value}"%'


def apply_genre_filters(
    query,
    include_genres: List[str],
    exclude_genres: List[str],
    dialect_name: str = "sqlite",
):
    """Filter a manga query by included/excluded genres.

    H3: on PostgreSQL this uses the JSONB existence operator (``genres::jsonb ?
    'genre'`` via ``has_key``) so the query can use the ``ix_manga_genres_gin``
    GIN index instead of forcing a full sequential scan. The previous
    ``cast(genres, TEXT) LIKE`` approach could never use an index. Genres are
    matched in lowercase form (they are stored/queried lowercase throughout the
    app); if legacy rows contain mixed-case genres a one-off normalization
    backfill is recommended. Non-Postgres backends (e.g. SQLite in tests) fall
    back to the case-insensitive text-match, which has no index either way.
    """

    if not include_genres and not exclude_genres:
        return query

    include = [g.lower() for g in include_genres if g]
    exclude = [g.lower() for g in exclude_genres if g]

    if not include and not exclude:
        return query

    if dialect_name == "postgresql":
        genres_jsonb = cast(Manga.genres, JSONB)
        if include:
            query = query.filter(Manga.genres.isnot(None))
            for genre in include:
                query = query.filter(genres_jsonb.has_key(genre))  # noqa: W601
        if exclude:
            for genre in exclude:
                query = query.filter(
                    or_(
                        Manga.genres.is_(None), ~genres_jsonb.has_key(genre)
                    )  # noqa: W601, E501
                )
        return query

    genre_text = func.lower(cast(Manga.genres, Text))

    if include:
        query = query.filter(Manga.genres.isnot(None))
        for genre in include:
            pattern = _genre_like_pattern(genre)
            query = query.filter(genre_text.like(pattern))

    if exclude:
        for genre in exclude:
            pattern = _genre_like_pattern(genre)
            query = query.filter(or_(Manga.genres.is_(None), ~genre_text.like(pattern)))

    return query


_PERIOD_SORTS = {"views_today": 1, "views_week": 7, "views_month": 30}


def _apply_sort(db: Session, query, sort: str):
    """Order the catalogue. Unknown values fall back to ``latest``."""

    from datetime import datetime, timedelta

    from ..models import Chapter, MangaDailyView, MangaRating

    if sort in _PERIOD_SORTS:
        since = datetime.utcnow().date() - timedelta(days=_PERIOD_SORTS[sort] - 1)
        period = (
            db.query(
                MangaDailyView.manga_id.label("manga_id"),
                func.sum(MangaDailyView.views).label("period_views"),
            )
            .filter(MangaDailyView.day >= since)
            .group_by(MangaDailyView.manga_id)
            .subquery()
        )
        return query.outerjoin(period, period.c.manga_id == Manga.id).order_by(
            func.coalesce(period.c.period_views, 0).desc(), Manga.views.desc(), Manga.id
        )
    if sort in {"popular", "views"}:
        return query.order_by(Manga.views.desc(), Manga.popularity.desc().nullslast(), Manga.id)
    if sort == "rating":
        ratings = (
            db.query(
                MangaRating.manga_id.label("manga_id"),
                func.avg(MangaRating.score).label("avg_score"),
            )
            .group_by(MangaRating.manga_id)
            .subquery()
        )
        return query.outerjoin(ratings, ratings.c.manga_id == Manga.id).order_by(
            func.coalesce(ratings.c.avg_score, 0).desc(), Manga.id
        )
    if sort in {"az", "title"}:
        return query.order_by(func.lower(Manga.title).asc(), Manga.id)
    if sort == "chapters":
        counts = (
            db.query(
                Chapter.manga_id.label("manga_id"),
                func.count(Chapter.id).label("chapter_count"),
            )
            .group_by(Chapter.manga_id)
            .subquery()
        )
        return query.outerjoin(counts, counts.c.manga_id == Manga.id).order_by(
            func.coalesce(counts.c.chapter_count, 0).desc(), Manga.id
        )
    if sort == "new":
        return query.order_by(Manga.created_at.desc(), Manga.id.desc())
    if sort == "random":
        return query.order_by(func.random())
    return query.order_by(Manga.updated_at.desc().nullslast(), Manga.id.desc())


def get_manga_list(
    db: Session,
    q: Optional[str],
    type_: Optional[str],
    status_filter: Optional[str],
    include_genres: List[str],
    exclude_genres: List[str],
    sort: str,
    page: int,
    per_page: int,
):
    query = db.query(Manga)

    if q:
        term = q.strip()
        query = query.filter(
            or_(
                Manga.title.icontains(term, autoescape=True),
                Manga.original_title.icontains(term, autoescape=True),
                cast(Manga.alternative_titles, Text).icontains(term, autoescape=True),
                cast(Manga.authors, Text).icontains(term, autoescape=True),
            )
        )
    if type_:
        query = query.filter(Manga.type == type_)
    if status_filter:
        query = query.filter(Manga.status == status_filter)

    dialect_name = db.get_bind().dialect.name
    query = apply_genre_filters(
        query, include_genres, exclude_genres, dialect_name=dialect_name
    )

    count_query = query.order_by(None).with_entities(func.count(Manga.id))
    total = int(count_query.scalar() or 0)

    query = _apply_sort(db, query, sort)

    offset = (page - 1) * per_page
    items = query.offset(offset).limit(per_page).all()

    return items, total, query


def _url_dedupe_variants(url: str) -> list[str]:
    """Every stored spelling the canonical URL could have (SRS 1G.4.1).

    Older rows may hold http/https, ``www.``, or trailing-slash variants of the
    same page; matching against the expanded set keeps duplicate detection
    exact (indexed equality) without a full-table scan.
    """

    from .url_guard import canonicalize_source_url

    canonical = canonicalize_source_url(url)
    parsed = urlparse(canonical)
    host = parsed.netloc
    rest = parsed.path + (f"?{parsed.query}" if parsed.query else "")

    variants: list[str] = [url.strip()]
    for scheme in ("https", "http"):
        for prefix in ("", "www."):
            base = f"{scheme}://{prefix}{host}{rest}"
            variants.append(base)
            if not parsed.query:
                variants.append(base + "/")
    # Preserve order, drop duplicates.
    return list(dict.fromkeys(variants))


def schedule_series_scrape(
    db_session, url: str, *, added_by: int = None, options: Optional[dict] = None
) -> dict:
    from ..models import Manga, ScrapingJob
    from .universal_scraper import scrape_series_by_url

    # Approval gate (SRS 1G.6.0 / 1G.3): the website hosting this URL must have
    # been approved by the Permanent Administrator before anything is scraped
    # from it, regardless of whether a working parser exists. This check runs
    # BEFORE any scraper module is selected (1G.3.3).
    hostname = (urlparse(url).hostname or "").strip().lower()
    if not _host_is_approved(db_session, hostname):
        raise ApiError(
            ErrorCode.WEBSITE_NOT_APPROVED,
            MSG_UNAPPROVED_URL,
            field="manga_url",
            details={"url": url, "domain": hostname or None},
        )

    # Rights gate (SRS 1J): the website may be approved for indexing yet not
    # licensed for hosting (``may_host`` False). Raises an ApiError.
    from .content_rights import assert_may_host_url

    assert_may_host_url(db_session, url)

    # Duplicate gate (1G.4): normalized-URL match, rejected BEFORE any work is
    # queued. The response carries the existing series so the submitter can
    # navigate to it (1G.4.3).
    variants = _url_dedupe_variants(url)
    existing = db_session.query(Manga).filter(Manga.source_url.in_(variants)).first()
    if existing is not None:
        raise ApiError(
            ErrorCode.DUPLICATE_MANGA_URL,
            MSG_DUPLICATE_MANGA_URL,
            field="manga_url",
            details={
                "url": url,
                "existing_series_id": existing.id,
                "manga_id": existing.id,
            },
        )

    existing_job = (
        db_session.query(ScrapingJob)
        .filter(ScrapingJob.source_url.in_(variants))
        .order_by(ScrapingJob.created_at.desc())
        .first()
    )
    if existing_job is not None and existing_job.status in {
        "queued",
        "in_progress",
        "processing",
    }:
        raise ApiError(
            ErrorCode.DUPLICATE_MANGA_URL,
            MSG_DUPLICATE_MANGA_URL,
            field="manga_url",
            details={
                "url": url,
                "job_id": existing_job.id,
                "existing_series_id": existing_job.manga_id,
            },
        )

    # Use existing helper to queue
    return scrape_series_by_url(
        url, db_session=db_session, added_by=added_by, options=options
    )


def ingestion_progress(db_session, manga: "Manga") -> dict:
    """Chapter-by-chapter ingestion progress for a series (SRS 1G.2.3)."""

    from ..models import Chapter

    counts = dict(
        db_session.query(Chapter.ingestion_status, func.count(Chapter.id))
        .filter(Chapter.manga_id == manga.id)
        .group_by(Chapter.ingestion_status)
        .all()
    )
    total = sum(counts.values())
    complete = counts.get("complete", 0)
    return {
        "series_id": manga.id,
        "ingestion_status": manga.ingestion_status or "complete",
        "last_error": manga.last_error,
        "chapters_total": total,
        "chapters_complete": complete,
        "chapters_failed": counts.get("failed", 0),
        "chapters_pending": total - complete - counts.get("failed", 0),
        "progress": f"{complete} of {total}",
        # 1G.12A.8: per-series scheduled-check visibility.
        "last_checked": manga.last_scraped.isoformat() if manga.last_scraped else None,
        "next_check_at": (
            manga.next_check_at.isoformat() if manga.next_check_at else None
        ),
        "check_interval_hours": manga.check_interval_hours,
    }
