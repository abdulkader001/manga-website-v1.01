"""Public manga and chapter routes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List

import structlog

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from ...schemas.manga import (
    MangaListResponse,
    MangaDetailResponse,
    ChapterBase,
    ChapterDetailResponse,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import Text, cast, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...utils.swr_cache import cached_with_swr

from ...core.db import get_db, get_read_db, SessionLocal
from ...core.pagination import MAX_PAGE
from ...models import Chapter, Manga, ReadHistory, User
from ...services.history_service import record_history as _record_history
from ...core.security import decode_token
from ...services.system_state import is_secret_phrase_used
from ...services.manga_service import (
    normalize_multi,
    get_manga_list,
)

router = APIRouter(prefix="/manga", tags=["manga"])


async def _enforce_series_hostable(manga_id: int, user: User | None) -> None:
    """F-18: refuse ordinary readers a taken-down/not-hostable series.

    ``resolve_series_rights`` computed the right answer but nothing on a
    read path consulted it -- a taken-down series stayed fully browsable.
    Runs as its own query outside the manga_detail/manga_chapters response
    cache (shared across every viewer), so an admin -- who bypasses this
    check -- can still see it while ordinary readers cannot. A series that
    doesn't exist at all is left to the caller's own 404 lookup.
    """

    from ...dependencies.auth import is_secondary_or_higher

    if user is not None and is_secondary_or_higher(user):
        return

    from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool
    from ...services.content_rights import assert_series_hostable

    def _check() -> None:
        with SessionLocal() as db_session:
            manga = db_session.get(Manga, manga_id)
            if manga is not None:
                assert_series_hostable(db_session, manga)

    await run_in_db_threadpool(_check)


_optional_bearer = HTTPBearer(auto_error=False)

logger = structlog.get_logger("backend_fastapi.manga")


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """Return the authenticated user if a valid bearer token is provided."""

    if credentials is None:
        return None

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None

    subject = payload.get("sub")
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        )

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject"
        ) from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )

    return user


async def _list_manga_impl(
    request: Request,
    q: str | None,
    type_: str | None,
    status_filter: str | None,
    genre: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
    sort: str,
    page: int,
    per_page: int,
    db: Session,
    user: User | None,
) -> dict[str, object]:
    """Browse manga with optional filters and pagination."""

    cache_key = f"manga_list:{q}:{type_}:{status_filter}:{genre}:{str(include)}:{str(exclude)}:{sort}:{page}:{per_page}"
    redis_client = getattr(request.app.state, "redis", None)

    async def fetch_data():
        from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool

        def _sync_fetch():
            with SessionLocal() as local_db:
                include_genres = normalize_multi(include)
                exclude_genres = normalize_multi(exclude)
                if genre and genre not in include_genres:
                    include_genres.insert(0, genre)

                items, total, query = get_manga_list(
                    local_db,
                    q,
                    type_,
                    status_filter,
                    include_genres,
                    exclude_genres,
                    sort,
                    page,
                    per_page,
                )

                genres_column = cast(Manga.genres, Text).label("genres_text")
                raw_genres = (
                    local_db.query(genres_column)
                    .filter(Manga.genres.isnot(None))
                    .distinct()
                    .all()
                )
                genre_set: set[str] = set()
                for row in raw_genres:
                    genres_text = getattr(row, "genres_text", None)
                    if not genres_text:
                        continue
                    try:
                        parsed = json.loads(genres_text)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(parsed, list):
                        for entry in parsed:
                            if isinstance(entry, str):
                                genre_set.add(entry)

                secret_phrase_used = is_secret_phrase_used(local_db)

                return {
                    "items": [m.to_dict() for m in items],
                    "total": total,
                    "page": page,
                    "per_page": per_page,
                    "genres": sorted(genre_set),
                    "cache_hit": False,
                    "secret_phrase_used": secret_phrase_used,
                }

        return await run_in_db_threadpool(_sync_fetch)

    payload = await cached_with_swr(
        redis_client,
        cache_key,
        60,
        fetch_data,
        celery_task_name="backend_fastapi.app.tasks.manga_tasks.refresh_manga_list_cache",
        celery_task_kwargs={
            "cache_key": cache_key,
            "ttl": 60,
            "q": q,
            "type_": type_,
            "status_filter": status_filter,
            "genre": genre,
            "include": include,
            "exclude": exclude,
            "sort": sort,
            "page": page,
            "per_page": per_page,
            # F-63: read-only. This argument is evaluated eagerly, before the
            # fetch callback runs, on the request's own never-committed read
            # session. Creating the row here left an uncommitted INSERT whose
            # unique-index lock the callback's separate session then blocked
            # on — a request deadlocking against itself.
            "secret_phrase_used": is_secret_phrase_used(db),
        },
    )
    if payload.get("cache_hit") is False and redis_client:
        pass
    else:
        payload["cache_hit"] = True

    return payload


@router.get("/", response_model=MangaListResponse)
async def list_manga(
    request: Request,
    db: Session = Depends(get_read_db),
    q: str | None = None,
    type_: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    genre: str | None = None,
    include: list[str] | None = Query(default=None),
    exclude: list[str] | None = Query(default=None),
    sort: str = "latest",
    page: int = Query(1, ge=1, le=MAX_PAGE),
    per_page: int = Query(60, ge=1, le=100),
    user: User | None = Depends(get_optional_user),
) -> MangaListResponse:
    """Browse manga with optional filters and pagination."""

    return await _list_manga_impl(
        request=request,
        q=q,
        type_=type_,
        status_filter=status_filter,
        genre=genre,
        include=include,
        exclude=exclude,
        sort=sort,
        page=page,
        per_page=per_page,
        db=db,
        user=user,
    )


@router.get("/browse", response_model=MangaListResponse, deprecated=True)
async def browse_manga(
    request: Request,
    response: Response,
    db: Session = Depends(get_read_db),
    q: str | None = None,
    type_: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    genre: str | None = None,
    include: list[str] | None = Query(default=None),
    exclude: list[str] | None = Query(default=None),
    sort: str = "latest",
    page: int = Query(1, ge=1, le=MAX_PAGE),
    per_page: int = Query(60, ge=1, le=100),
    user: User | None = Depends(get_optional_user),
) -> MangaListResponse:
    """Legacy browse endpoint that mirrors the primary listing route."""

    logger.info(
        "Deprecated endpoint hit",
        route="browse_manga",
        user_id=user.id if user else None,
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-07-01"

    return await _list_manga_impl(
        request=request,
        q=q,
        type_=type_,
        status_filter=status_filter,
        genre=genre,
        include=include,
        exclude=exclude,
        sort=sort,
        page=page,
        per_page=per_page,
        db=db,
        user=user,
    )


@router.get("/{manga_id}", response_model=MangaDetailResponse)
async def get_manga_detail(
    request: Request,
    manga_id: int,
    db: Session = Depends(get_read_db),
    user: User | None = Depends(get_optional_user),
) -> MangaDetailResponse:
    """Return detailed information for a single manga."""

    await _enforce_series_hostable(manga_id, user)

    cache_key = f"manga_detail:{manga_id}"
    redis_client = getattr(request.app.state, "redis", None)

    async def fetch_data():
        from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool

        def _sync_fetch():
            with SessionLocal() as db_session:
                manga = db_session.query(Manga).filter(Manga.id == manga_id).first()
                if manga is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
                    )

                chapters_count = (
                    db_session.query(func.count(Chapter.id))
                    .filter(Chapter.manga_id == manga_id)
                    .scalar()
                    or 0
                )

                payload = manga.to_dict()
                payload["chapters_count"] = int(chapters_count)
                return payload

        return await run_in_db_threadpool(_sync_fetch)

    return await cached_with_swr(
        redis_client,
        cache_key,
        60,
        fetch_data,
        celery_task_name="backend_fastapi.app.tasks.manga_tasks.refresh_manga_detail_cache",
        celery_task_kwargs={"cache_key": cache_key, "ttl": 60, "manga_id": manga_id},
    )


@router.get("/{manga_id}/chapters", response_model=List[ChapterBase])
async def get_chapter_list(
    request: Request,
    manga_id: int,
    order: str = Query("asc"),
    db: Session = Depends(get_read_db),
    user: User | None = Depends(get_optional_user),
) -> List[ChapterBase]:
    """Return the list of chapters for a manga."""

    await _enforce_series_hostable(manga_id, user)

    cache_key = f"manga_chapters:{manga_id}:{order}"
    redis_client = getattr(request.app.state, "redis", None)

    async def fetch_data():
        from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool

        def _sync_fetch():
            with SessionLocal() as local_db:
                manga = local_db.query(Manga).filter(Manga.id == manga_id).first()
                if manga is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
                    )

                query = local_db.query(Chapter).filter(Chapter.manga_id == manga.id)
                if order.lower() == "asc":
                    query = query.order_by(Chapter.chapter_number.asc())
                else:
                    query = query.order_by(Chapter.chapter_number.desc())

                chapters = query.all()

                cached_chapters = []
                for chapter in chapters:
                    created_at = getattr(chapter, "created_at", None)
                    if isinstance(created_at, datetime):
                        created_at_value: object | None = created_at.isoformat()
                    else:
                        created_at_value = created_at

                    cached_chapters.append(
                        {
                            "id": chapter.id,
                            "number": str(chapter.chapter_number),
                            "title": chapter.chapter_title,
                            "url": chapter.chapter_url,
                            "created_at": created_at_value,
                        }
                    )
                return cached_chapters

        return await run_in_db_threadpool(_sync_fetch)

    cached_chapters = await cached_with_swr(
        redis_client,
        cache_key,
        60,
        fetch_data,
        celery_task_name="backend_fastapi.app.tasks.manga_tasks.refresh_manga_chapters_cache",
        celery_task_kwargs={
            "cache_key": cache_key,
            "ttl": 60,
            "manga_id": manga_id,
            "order": order,
        },
    )

    read_chapters: set[int] = set()
    if user is not None:
        from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool

        def _fetch_history():
            rows = (
                db.query(ReadHistory.chapter_id)
                .filter(
                    ReadHistory.user_id == user.id, ReadHistory.manga_id == manga_id
                )
                .all()
            )
            return {row[0] for row in rows if row[0] is not None}

        read_chapters = await run_in_db_threadpool(_fetch_history)

    for chapter_payload in cached_chapters:
        chapter_payload["read"] = chapter_payload["id"] in read_chapters

    return cached_chapters


@router.get("/{manga_id}/chapters/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter_content(
    manga_id: int,
    chapter_id: int,
    db: Session = Depends(get_read_db),
    user: User | None = Depends(get_optional_user),
) -> ChapterDetailResponse:
    """Return the chapter content (pages) for a manga."""

    from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool

    def _sync_get_content():
        chapter = (
            db.query(Chapter)
            .filter(Chapter.id == chapter_id, Chapter.manga_id == manga_id)
            .first()
        )
        if chapter is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found"
            )

        if user is not None:
            try:
                _record_history(user, manga_id, chapter.id, db)
            except IntegrityError:
                db.rollback()

        payload = chapter.to_dict()
        pages = payload.get("pages") or []
        if isinstance(pages, list):
            payload["pages"] = pages
        else:
            payload["pages"] = [pages]

        # Effective translation right for the series (SRS 1J).
        from ...dependencies.auth import is_secondary_or_higher
        from ...services.content_rights import (
            assert_series_hostable,
            resolve_series_rights,
        )

        manga = db.get(Manga, manga_id)
        payload["may_translate"] = (
            resolve_series_rights(db, manga)["may_translate"]
            if manga is not None
            else True
        )

        # F-18: a taken-down/not-hostable series' pages must not remain
        # readable to ordinary viewers just because the chapter row itself
        # still exists -- admins bypass this, matching
        # get_manga_detail/get_chapter_list.
        if manga is not None and not (
            user is not None and is_secondary_or_higher(user)
        ):
            assert_series_hostable(db, manga)
        return payload

    return await run_in_db_threadpool(_sync_get_content)
