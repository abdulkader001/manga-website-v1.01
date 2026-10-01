"""Public manga and chapter routes."""

from __future__ import annotations

from typing import List

import structlog

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from ...schemas.manga import (
    MangaListResponse,
    MangaDetailResponse,
    ChapterBase,
    ChapterDetailResponse,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...utils.swr_cache import cached_with_swr

from ...core.db import get_db, get_read_db, SessionLocal
from ...core.pagination import MAX_PAGE
from ...dependencies.auth import get_optional_user
from ...models import Chapter, ChapterLike, Manga, ReadHistory, User
from ...services import catalogue_service, image_proxy
from ...services.history_service import record_history as _record_history
from ...services.system_state import is_secret_phrase_used

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


logger = structlog.get_logger("backend_fastapi.manga")


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
    secret_phrase_used = is_secret_phrase_used(db)

    async def fetch_data():
        from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool

        def _sync_fetch():
            with SessionLocal() as local_db:
                return catalogue_service.build_list_payload(
                    local_db,
                    q=q,
                    type_=type_,
                    status_filter=status_filter,
                    genre=genre,
                    include=include,
                    exclude=exclude,
                    sort=sort,
                    page=page,
                    per_page=per_page,
                    secret_phrase_used=secret_phrase_used,
                )

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
            # F-63: read-only. Evaluated eagerly on the request's own
            # never-committed read session (see is_secret_phrase_used).
            "secret_phrase_used": secret_phrase_used,
        },
    )
    if not (payload.get("cache_hit") is False and redis_client):
        payload["cache_hit"] = True
    # The cached payload is shared between viewers: work on a copy.
    payload = {**payload, "items": [dict(i) for i in payload.get("items") or []]}
    catalogue_service.apply_viewer_fields(db, payload["items"], user)
    return payload


@router.get("/", response_model=MangaListResponse)
async def list_manga(
    request: Request,
    db: Session = Depends(get_read_db),
    q: str | None = None,
    search: str | None = Query(default=None, max_length=200),
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
        q=q or search,
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
    search: str | None = Query(default=None, max_length=200),
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
        q=q or search,
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
                payload = catalogue_service.build_detail_payload(db_session, manga_id)
                if payload is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
                    )
                return payload

        return await run_in_db_threadpool(_sync_fetch)

    payload = await cached_with_swr(
        redis_client,
        cache_key,
        60,
        fetch_data,
        celery_task_name="backend_fastapi.app.tasks.manga_tasks.refresh_manga_detail_cache",
        celery_task_kwargs={"cache_key": cache_key, "ttl": 60, "manga_id": manga_id},
    )
    payload = dict(payload)
    catalogue_service.apply_viewer_fields(db, [payload], user)
    return payload


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

    order = "desc" if order.lower() == "desc" else "asc"
    cache_key = f"manga_chapters:{manga_id}:{order}"
    redis_client = getattr(request.app.state, "redis", None)

    async def fetch_data():
        from backend_fastapi.app.utils.bounded_threadpool import run_in_db_threadpool

        def _sync_fetch():
            with SessionLocal() as local_db:
                payload = catalogue_service.build_chapter_list_payload(
                    local_db, manga_id, order
                )
                if payload is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found"
                    )
                return payload

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


@router.get("/{manga_id}/chapter-titles")
async def get_chapter_titles(
    request: Request,
    manga_id: int,
    lang: str = Query("en", min_length=2, max_length=8),
    user: User | None = Depends(get_optional_user),
) -> dict:
    """Readable, translated chapter titles: ``{"titles": {id: {title, original}}}``.

    Source titles like "522 원준 522화 2024-11-07" become "Chapter 522"; a real
    subtitle is translated once into ``lang`` (with the reader's own
    translator, else the site default) and cached per chapter.
    """

    await _enforce_series_hostable(manga_id, user)
    from ...services import chapter_title_service
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        with SessionLocal() as local_db:
            manga = local_db.get(Manga, manga_id)
            if manga is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manga not found")
            translate = _title_translator(request, local_db, user, lang)
            titles = chapter_title_service.display_titles(
                local_db, manga, lang, translate=translate
            )
            return {"lang": lang, "titles": {str(k): v for k, v in titles.items()}}

    return await run_in_db_threadpool(_work)


def _title_translator(request: Request, db: Session, user: User | None, lang: str):
    """A ``text -> translation`` callable, or None when nothing can translate."""

    from ...services.provider_resolver import integration_vault, user_provider_config
    from ...services.translation_service import TranslationService
    from .processing import _platform_default

    vault = integration_vault(request)
    candidates = []
    if user is not None:
        candidates.append(user_provider_config(db, user, "translation", vault=vault))
        candidates.append(user_provider_config(db, user, "ai", vault=vault))
    candidates.append(_platform_default(request, db, "translation"))
    candidates.append(_platform_default(request, db, "ai"))
    configs = [c for c in candidates if c and c.get("api_url")]
    if not configs:
        return None
    service = TranslationService(
        default_api_url=None, default_provider_config=configs[1] if len(configs) > 1 else None
    )

    def translate(text: str):
        return service.translate(text, "auto", lang, provider_config=configs[0])

    return translate


@router.get("/{manga_id}/chapters/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter_content(
    manga_id: int,
    chapter_id: int,
    db: Session = Depends(get_db),
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

        from ...dependencies.auth import is_secondary_or_higher
        from ...services.content_rights import (
            assert_series_hostable,
            resolve_series_rights,
        )

        manga = db.get(Manga, manga_id)
        # F-18: a taken-down/not-hostable series' pages must not remain
        # readable to ordinary viewers just because the chapter row itself
        # still exists -- admins bypass this, matching
        # get_manga_detail/get_chapter_list.
        if manga is not None and not (
            user is not None and is_secondary_or_higher(user)
        ):
            assert_series_hostable(db, manga)

        try:
            catalogue_service.record_chapter_view(db, chapter, user)
            if user is not None:
                _record_history(user, manga_id, chapter.id, db)
            db.commit()
        except IntegrityError:
            db.rollback()

        payload = chapter.to_dict()
        payload["pages"] = image_proxy.reader_page_urls(db, chapter)
        payload["may_translate"] = (
            resolve_series_rights(db, manga)["may_translate"]
            if manga is not None
            else True
        )
        payload["manga_title"] = manga.title if manga is not None else None

        neighbours = (
            db.query(Chapter.id, Chapter.chapter_number)
            .filter(Chapter.manga_id == manga_id)
            .order_by(Chapter.chapter_number.asc(), Chapter.id.asc())
            .all()
        )
        ids = [row.id for row in neighbours]
        position = ids.index(chapter.id) if chapter.id in ids else -1
        payload["prev_chapter_id"] = ids[position - 1] if position > 0 else None
        payload["next_chapter_id"] = (
            ids[position + 1] if 0 <= position < len(ids) - 1 else None
        )
        payload["liked"] = bool(
            user is not None
            and db.query(ChapterLike.id)
            .filter(ChapterLike.chapter_id == chapter.id, ChapterLike.user_id == user.id)
            .first()
        )
        payload["likes"] = (
            db.query(func.count(ChapterLike.id))
            .filter(ChapterLike.chapter_id == chapter.id)
            .scalar()
            or 0
        )
        return payload

    return await run_in_db_threadpool(_sync_get_content)


