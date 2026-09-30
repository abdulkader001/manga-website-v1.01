from __future__ import annotations

import json
import time

from ..core.celery_app import celery_app
from ..core.db import SessionLocal
from ..services.manga_service import get_manga_list, normalize_multi
from ..models import Manga, Chapter
from sqlalchemy import cast, Text, func


@celery_app.task(
    name="backend_fastapi.app.tasks.manga_tasks.refresh_manga_list_cache",
    time_limit=120,
    soft_time_limit=100,
)
def refresh_manga_list_cache(
    cache_key: str,
    ttl: int,
    q: str | None,
    type_: str | None,
    status_filter: str | None,
    genre: str | None,
    include: list[str] | None,
    exclude: list[str] | None,
    sort: str,
    page: int,
    per_page: int,
    secret_phrase_used: bool,
):
    from redis import Redis
    from ..core.settings import get_settings

    settings = get_settings()
    redis_url = settings.redis_url or settings.celery_broker_url
    if not redis_url:
        return
    redis_client = Redis.from_url(redis_url)

    db = SessionLocal()
    try:
        include_genres = normalize_multi(include)
        exclude_genres = normalize_multi(exclude)
        if genre and genre not in include_genres:
            include_genres.insert(0, genre)

        items, total, query = get_manga_list(
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

        genres_column = cast(Manga.genres, Text).label("genres_text")
        raw_genres = (
            db.query(genres_column).filter(Manga.genres.isnot(None)).distinct().all()
        )
        genre_set = set()
        for row in raw_genres:
            genres_text = getattr(row, "genres_text", None)
            if not genres_text:
                continue
            try:
                parsed = json.loads(genres_text)
                if isinstance(parsed, list):
                    for entry in parsed:
                        if isinstance(entry, str):
                            genre_set.add(entry)
            except Exception:
                pass

        data = {
            "items": [m.to_dict() for m in items],
            "total": total,
            "page": page,
            "per_page": per_page,
            "genres": sorted(genre_set),
            "cache_hit": False,
            "secret_phrase_used": secret_phrase_used,
        }

        payload = {"data": data, "_expires_at": time.time() + ttl}
        redis_client.setex(cache_key, 86400, json.dumps(payload))
    finally:
        db.close()
        redis_client.delete(f"{cache_key}:lock")


@celery_app.task(
    name="backend_fastapi.app.tasks.manga_tasks.refresh_manga_detail_cache",
    time_limit=60,
    soft_time_limit=45,
)
def refresh_manga_detail_cache(cache_key: str, ttl: int, manga_id: int):
    from redis import Redis
    from ..core.settings import get_settings

    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url or settings.celery_broker_url)

    db = SessionLocal()
    try:
        manga = db.query(Manga).filter(Manga.id == manga_id).first()
        if manga is None:
            return
        chapters_count = (
            db.query(func.count(Chapter.id))
            .filter(Chapter.manga_id == manga_id)
            .scalar()
            or 0
        )
        data = manga.to_dict()
        data["chapters_count"] = int(chapters_count)

        payload = {"data": data, "_expires_at": time.time() + ttl}
        redis_client.setex(cache_key, 86400, json.dumps(payload))
    finally:
        db.close()
        redis_client.delete(f"{cache_key}:lock")


@celery_app.task(
    name="backend_fastapi.app.tasks.manga_tasks.refresh_manga_chapters_cache",
    time_limit=60,
    soft_time_limit=45,
)
def refresh_manga_chapters_cache(cache_key: str, ttl: int, manga_id: int, order: str):
    from redis import Redis
    from ..core.settings import get_settings
    from datetime import datetime

    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url or settings.celery_broker_url)

    db = SessionLocal()
    try:
        manga = db.query(Manga).filter(Manga.id == manga_id).first()
        if manga is None:
            return

        query = db.query(Chapter).filter(Chapter.manga_id == manga.id)
        if order.lower() == "asc":
            query = query.order_by(Chapter.chapter_number.asc())
        else:
            query = query.order_by(Chapter.chapter_number.desc())
        chapters = query.all()

        data = []
        for chapter in chapters:
            created_at = getattr(chapter, "created_at", None)
            if isinstance(created_at, datetime):
                created_at_value = created_at.isoformat()
            else:
                created_at_value = created_at
            data.append(
                {
                    "id": chapter.id,
                    "number": str(chapter.chapter_number),
                    "title": chapter.chapter_title,
                    "url": chapter.chapter_url,
                    "created_at": created_at_value,
                }
            )

        payload = {"data": data, "_expires_at": time.time() + ttl}
        redis_client.setex(cache_key, 86400, json.dumps(payload))
    finally:
        db.close()
        redis_client.delete(f"{cache_key}:lock")
