from __future__ import annotations

import json
import time

from ..core.celery_app import celery_app
from ..core.db import SessionLocal
from ..services import catalogue_service


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
        data = catalogue_service.build_list_payload(
            db,
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
        data = catalogue_service.build_detail_payload(db, manga_id)
        if data is None:
            return

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

    settings = get_settings()
    redis_client = Redis.from_url(settings.redis_url or settings.celery_broker_url)

    db = SessionLocal()
    try:
        data = catalogue_service.build_chapter_list_payload(db, manga_id, order)
        if data is None:
            return

        payload = {"data": data, "_expires_at": time.time() + ttl}
        redis_client.setex(cache_key, 86400, json.dumps(payload))
    finally:
        db.close()
        redis_client.delete(f"{cache_key}:lock")
