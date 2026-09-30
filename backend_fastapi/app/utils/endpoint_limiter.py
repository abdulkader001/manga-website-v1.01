from __future__ import annotations

import time
import asyncio
from typing import Optional

from fastapi import Request, HTTPException
from redis.asyncio import Redis


class AsyncEndpointLimiter:
    """An asynchronous rate limiter utility to apply limits per identifier dynamically."""

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()
        self._buckets: dict[str, tuple[float, int]] = {}

    @staticmethod
    def _redis(request: Request) -> Optional[Redis]:
        client = getattr(request.app.state, "redis", None)
        return client if isinstance(client, Redis) else None

    async def check_limit(
        self, request: Request, identifier: str, limit: int, window_seconds: int
    ) -> None:
        from ..core.test_mode import test_mode_active

        if test_mode_active():
            return

        redis_client = self._redis(request)
        if redis_client is not None:
            allowed, retry_after = await self._consume_redis(
                redis_client, identifier, limit, window_seconds
            )
            if allowed is not None:
                if not allowed:
                    raise HTTPException(
                        status_code=429,
                        detail="Too many requests",
                        headers={"Retry-After": str(max(1, int(retry_after)))},
                    )
                return

        # Fallback
        allowed, retry_after = await self._consume_memory(
            identifier, limit, window_seconds
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": str(max(1, int(retry_after)))},
            )

    async def _consume_redis(
        self, client: Redis, identifier: str, limit: int, window_seconds: int
    ) -> tuple[Optional[bool], int]:
        key = f"endpointlimit:{identifier}:{window_seconds}"
        try:
            # Add small timeout for redis calls to avoid blocking
            async with asyncio.timeout(0.02):
                async with client.pipeline() as pipe:
                    pipe.incr(key)
                    pipe.expire(key, window_seconds, nx=True)
                    count, _ = await pipe.execute()
                ttl = await client.ttl(key)
                remaining_window = (
                    window_seconds if ttl is None or ttl < 0 else int(ttl)
                )
        except Exception:
            return None, window_seconds

        current = int(count)
        if current > limit:
            return False, remaining_window
        return True, max(limit - current, 0)

    async def _consume_memory(
        self, identifier: str, limit: int, window_seconds: int
    ) -> tuple[bool, int]:
        now = time.monotonic()
        lock = self._locks.get(identifier)
        if lock is None:
            async with self._locks_lock:
                if identifier not in self._locks:
                    self._locks[identifier] = asyncio.Lock()
                lock = self._locks[identifier]

        async with lock:
            expires_at, count = self._buckets.get(identifier, (now + window_seconds, 0))
            if expires_at <= now:
                expires_at = now + window_seconds
                count = 0
            count += 1
            self._buckets[identifier] = (expires_at, count)

        if count > limit:
            retry_after = max(1, int(expires_at - now))
            return False, retry_after

        return True, max(limit - count, 0)


async_endpoint_limiter = AsyncEndpointLimiter()
# Fallback for old imports
sync_endpoint_limiter = async_endpoint_limiter
