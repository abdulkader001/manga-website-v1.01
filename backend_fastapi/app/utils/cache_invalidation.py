"""Explicit cache invalidation helpers (item 34).

The manga list/detail/chapter caches use short TTLs (bounded staleness), but a
write (new scrape, admin edit) should also be able to invalidate them
immediately rather than waiting for the TTL to lapse. These helpers delete the
relevant Redis keys by prefix using non-blocking SCAN so a large keyspace is not
stalled.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger("backend_fastapi.cache_invalidation")

MANGA_LIST_PREFIX = "manga_list:"
MANGA_DETAIL_PREFIX = "manga:"
MANGA_CHAPTERS_PREFIX = "manga_chapters:"


def _delete_by_prefix(redis_client, prefix: str) -> int:
    """Delete every key starting with ``prefix``. Returns the count removed."""

    if redis_client is None:
        return 0
    removed = 0
    try:
        for key in redis_client.scan_iter(match=f"{prefix}*", count=500):
            redis_client.delete(key)
            removed += 1
    except Exception:  # best-effort; cache invalidation must never break a write
        logger.warning("cache_invalidation_failed", prefix=prefix)
    return removed


def invalidate_manga_list_cache(redis_client) -> int:
    """Invalidate all cached manga list/browse pages (call after list-affecting writes)."""

    return _delete_by_prefix(redis_client, MANGA_LIST_PREFIX)


def invalidate_manga_detail_cache(redis_client, manga_id: int | None = None) -> int:
    """Invalidate a manga's detail + chapter caches (or all when ``manga_id`` is None)."""

    if manga_id is None:
        return _delete_by_prefix(redis_client, MANGA_DETAIL_PREFIX) + _delete_by_prefix(
            redis_client, MANGA_CHAPTERS_PREFIX
        )
    removed = 0
    if redis_client is not None:
        try:
            for prefix in (MANGA_DETAIL_PREFIX, MANGA_CHAPTERS_PREFIX):
                for key in redis_client.scan_iter(
                    match=f"{prefix}{manga_id}*", count=200
                ):
                    redis_client.delete(key)
                    removed += 1
        except Exception:
            logger.warning("cache_invalidation_failed", manga_id=manga_id)
    return removed


def invalidate_all_manga_caches(redis_client) -> int:
    """Invalidate every manga-related cache entry (list + detail + chapters)."""

    return invalidate_manga_list_cache(redis_client) + invalidate_manga_detail_cache(
        redis_client
    )
