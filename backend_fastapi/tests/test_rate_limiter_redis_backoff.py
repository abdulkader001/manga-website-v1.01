"""Progressive rate-limit backoff on the Redis-backed path (SRS 4G.1).

Complements test_rate_limiter_backoff.py (the in-memory fallback): this
exercises _consume_redis/_escalate_redis directly against a fake Redis client
to catch wiring bugs (wrong await/argument shape) the in-memory path can't.
"""

from __future__ import annotations

import asyncio
import time

from backend_fastapi.app.utils.rate_limiter import RateLimitMiddleware


def _run(coro):
    return asyncio.run(coro)


class FakeRedis:
    """Minimal async Redis stand-in covering what the rate limiter needs."""

    def __init__(self):
        self.store: dict[str, int] = {}
        self.expiry: dict[str, float] = {}

    def _expired(self, key: str) -> bool:
        deadline = self.expiry.get(key)
        return deadline is not None and deadline <= time.monotonic()

    async def ttl(self, key: str) -> int:
        if key not in self.store or self._expired(key):
            return -2
        deadline = self.expiry.get(key)
        if deadline is None:
            return -1
        return max(0, int(deadline - time.monotonic()))

    def pipeline(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incr(self, key):
        self._pending_key = key
        if self._expired(key):
            self.store.pop(key, None)
            self.expiry.pop(key, None)
        self.store[key] = self.store.get(key, 0) + 1

    def expire(self, key, seconds, nx=False):
        if nx and key in self.expiry:
            return
        self.expiry[key] = time.monotonic() + seconds

    async def execute(self):
        return [self.store[self._pending_key], True]

    async def set(self, key, value, ex=None):
        self.store[key] = value
        if ex is not None:
            self.expiry[key] = time.monotonic() + ex


def _middleware(limit: int = 1, window_seconds: int = 5) -> RateLimitMiddleware:
    return RateLimitMiddleware(
        app=None,
        limit=limit,
        window_seconds=window_seconds,
        max_block_seconds=3600,
    )


def test_redis_path_escalates_and_then_short_circuits_on_the_block_key():
    mw = _middleware(limit=1, window_seconds=5)
    client = FakeRedis()
    identifier = "1.1.1.1"

    async def scenario():
        # First request: allowed.
        allowed1, _ = await mw._consume_redis(client, identifier)
        # Second request in the same window: over limit -> first violation,
        # blocked for the base window.
        allowed2, retry2 = await mw._consume_redis(client, identifier)
        # Third call: the block key is now set, so this must short-circuit
        # straight to "blocked" without re-touching the counter.
        allowed3, retry3 = await mw._consume_redis(client, identifier)
        return allowed1, (allowed2, retry2), (allowed3, retry3)

    allowed1, (allowed2, retry2), (allowed3, retry3) = _run(scenario())
    assert allowed1 is True
    assert allowed2 is False
    # Allow for monotonic-clock/int-truncation jitter between setting the
    # TTL and reading it back.
    assert mw.window - 1 <= retry2 <= mw.window
    assert allowed3 is False
    assert mw.window - 1 <= retry3 <= mw.window
