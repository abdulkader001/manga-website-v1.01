import json
import time
import asyncio
from typing import Any, Callable, Awaitable, Optional, Dict
from cachetools import TTLCache
import logging

logger = logging.getLogger("backend_fastapi.swr_cache")

_local_cache = TTLCache(maxsize=10000, ttl=10)
# Bounded like _local_cache: one entry per distinct cache_key (which embeds
# user-controlled query params), so an unbounded dict here is an unauthenticated
# memory-growth vector. Eviction only drops the *shared* reference — a
# coroutine already holding a Lock/Event keeps using its own reference, so
# eviction can never orphan a waiter (see get_local_lock/get_local_event).
_local_locks = TTLCache(maxsize=10000, ttl=30)
_local_locks_lock = asyncio.Lock()
_local_events = TTLCache(maxsize=10000, ttl=30)


async def get_local_lock(cache_key: str) -> asyncio.Lock:
    async with _local_locks_lock:
        if cache_key not in _local_locks:
            _local_locks[cache_key] = asyncio.Lock()
        return _local_locks[cache_key]


async def get_local_event(cache_key: str) -> asyncio.Event:
    async with _local_locks_lock:
        if cache_key not in _local_events:
            _local_events[cache_key] = asyncio.Event()
        return _local_events[cache_key]


async def _dispatch_celery_refresh(
    celery_task_name: str, celery_task_kwargs: Dict[str, Any], cache_key: str
) -> None:
    """Fire a Celery refresh task without blocking the event loop.

    ``celery_app.send_task`` is a synchronous call (kombu connection +
    bounded retries) that can stall for seconds under a broker outage;
    running it via ``asyncio.to_thread`` keeps that stall off the event
    loop so it can't freeze every other request this process is serving.
    """
    try:
        from backend_fastapi.app.core.celery_app import celery_app

        await asyncio.to_thread(
            celery_app.send_task,
            celery_task_name,
            kwargs=celery_task_kwargs,
            queue="default",
        )
    except Exception as e:
        logger.error(f"Celery dispatch failed for {cache_key}: {e}")


async def background_refresh(
    redis_client, cache_key: str, ttl: int, fetch_func: Callable[[], Awaitable[Any]]
):
    try:
        data = await fetch_func()
        payload = {"data": data, "_expires_at": time.time() + ttl}
        async with asyncio.timeout(0.02):
            await redis_client.setex(cache_key, 86400, json.dumps(payload))
        async with await get_local_lock(cache_key):
            _local_cache[cache_key] = (data, time.time() + min(ttl, 10))
    except Exception as e:
        logger.error(f"Background refresh failed for {cache_key}: {e}")


async def cached_with_swr(
    redis_client,
    cache_key: str,
    ttl: int,
    fetch_func: Callable[[], Awaitable[Any]],
    celery_task_name: Optional[str] = None,
    celery_task_kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    now = time.time()
    local_lock = await get_local_lock(cache_key)

    async with local_lock:
        if cache_key in _local_cache:
            data, expires_at = _local_cache[cache_key]
            if now < expires_at:
                return data

        if not redis_client:
            data = await fetch_func()
            _local_cache[cache_key] = (data, time.time() + min(ttl, 10))
            return data

    redis_available = True
    try:
        async with asyncio.timeout(0.02):
            cached = await redis_client.get(cache_key)
            if cached:
                payload = json.loads(cached)
                expires_at = payload.get("_expires_at", 0)
                data = payload.get("data")

                if now < expires_at:
                    async with local_lock:
                        _local_cache[cache_key] = (data, now + min(ttl, 10))
                    return data
                else:
                    # STALE HIT!
                    lock_key = f"{cache_key}:lock"
                    if await redis_client.set(lock_key, "1", nx=True, ex=30):
                        if celery_task_name and celery_task_kwargs is not None:
                            asyncio.create_task(
                                _dispatch_celery_refresh(
                                    celery_task_name, celery_task_kwargs, cache_key
                                )
                            )
                        else:
                            # Fallback: asyncio background task to refresh
                            asyncio.create_task(
                                background_refresh(
                                    redis_client, cache_key, ttl, fetch_func
                                )
                            )
                    return data
    except Exception:
        redis_available = False

    async with local_lock:
        # Check local cache again just in case another request fetched it while we were trying Redis
        if cache_key in _local_cache:
            data, expires_at = _local_cache[cache_key]
            if now < expires_at:
                return data

        if not redis_available:
            # Hard Miss & Redis Down - Fallback to fetch immediately inside the local lock.
            data = await fetch_func()
            _local_cache[cache_key] = (data, time.time() + min(ttl, 10))
            return data

    # Hard Miss - use dogpile lock to prevent thundering herd across workers
    lock_key = f"{cache_key}:lock"

    acquired = False
    try:
        async with asyncio.timeout(0.02):
            acquired = await redis_client.set(lock_key, "1", nx=True, ex=30)
    except Exception:
        redis_available = False

    if acquired:
        # We got the lock! Let's fetch and broadcast to anyone waiting locally
        try:
            data = await fetch_func()
            try:
                payload = {"data": data, "_expires_at": time.time() + ttl}
                async with asyncio.timeout(0.02):
                    await redis_client.setex(cache_key, 86400, json.dumps(payload))
            except Exception:
                pass

            async with local_lock:
                _local_cache[cache_key] = (data, time.time() + min(ttl, 10))

            # Wake up other waiters on this worker
            event = await get_local_event(cache_key)
            event.set()
            event.clear()
            return data
        finally:
            try:
                async with asyncio.timeout(0.02):
                    await redis_client.delete(lock_key)
            except Exception:
                pass
    elif redis_available:
        try:
            # Wait either for the local worker event or just a short fallback for cross-worker operations
            event = await get_local_event(cache_key)
            async with asyncio.timeout(0.1):
                await event.wait()
        except TimeoutError:
            pass

        try:
            async with asyncio.timeout(0.02):
                cached = await redis_client.get(cache_key)
                if cached:
                    payload = json.loads(cached)
                    return payload.get("data")
        except Exception:
            pass

    # Fallback if timeout reached or Redis failed, or we couldn't get it
    async with local_lock:
        if cache_key in _local_cache:
            data, expires_at = _local_cache[cache_key]
            if time.time() < expires_at:
                return data

        data = await fetch_func()
        _local_cache[cache_key] = (data, time.time() + min(ttl, 10))
    return data
