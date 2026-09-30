"""Lightweight request rate limiting middleware with Redis fallback."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import structlog
from fastapi import Request
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..core.api_errors import ErrorCode, error_body
from .client_ip import resolve_client_ip

logger = structlog.get_logger("backend_fastapi.rate_limiter")

# M1: 20ms was far too tight — any minor Redis latency silently dropped
# distributed limiting down to weaker per-process limits. Default to 200ms and
# make it configurable.
DEFAULT_REDIS_TIMEOUT_SECONDS = 0.2

# 4G.1: repeated violations from one source escalate to a longer block each
# time, not just a repeated short one. Defaults are conservative (doubling,
# capped at an hour) so a single burst of legitimate retries never gets stuck
# behind a long block.
DEFAULT_MAX_BLOCK_SECONDS = 3600
STRIKE_BACKOFF_BASE = 2
MAX_STRIKE_EXPONENT = 10  # caps the doubling well before it would overflow

# F-73: liveness/readiness probes and the Prometheus scrape all arrive from a
# single source IP at a fixed interval, so they share one rate-limit bucket
# with every other request from that IP (the docker network gateway, the k8s
# node, the load balancer). Once that bucket trips, the probe itself starts
# receiving 429s, the container is marked unhealthy, and the orchestrator
# restarts a service that was never actually unhealthy — the limiter turns a
# traffic spike into an outage. These paths carry no state and leak nothing,
# so they are exempt.
EXEMPT_PATHS = frozenset({"/health", "/healthz", "/metrics"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply a coarse IP-based rate limit backed by Redis when available."""

    def __init__(  # type: ignore[override] # noqa: E501
        self,
        app,
        *,
        limit: int,
        window_seconds: int,
        redis_timeout: float | None = None,
        max_block_seconds: int | None = None,
        strike_decay_seconds: int | None = None,
    ) -> None:
        super().__init__(app)
        self.limit = max(1, int(limit))
        self.window = max(1, int(window_seconds))
        if redis_timeout is None:
            redis_timeout = float(
                os.getenv("RATE_LIMIT_REDIS_TIMEOUT_SECONDS")
                or str(DEFAULT_REDIS_TIMEOUT_SECONDS)
            )
        self.redis_timeout = max(0.01, float(redis_timeout))
        if max_block_seconds is None:
            max_block_seconds = int(
                os.getenv("RATE_LIMIT_MAX_BLOCK_SECONDS")
                or str(DEFAULT_MAX_BLOCK_SECONDS)
            )
        self.max_block_seconds = max(self.window, int(max_block_seconds))
        if strike_decay_seconds is None:
            strike_decay_seconds = int(
                os.getenv("RATE_LIMIT_STRIKE_DECAY_SECONDS")
                or str(self.window * 10)
            )
        # How long a source's strike count is remembered once it stops
        # violating the limit -- after this much quiet, escalation resets.
        self.strike_decay_seconds = max(self.window, int(strike_decay_seconds))
        # Exposed for health checks; True while we've fallen back to in-memory
        # limiting because Redis was unreachable/slow.
        self.degraded = False
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()
        self._buckets: dict[str, tuple[float, int]] = {}
        # In-memory progressive-backoff state (fallback path only; Redis
        # keeps the equivalent state server-side so it's shared across
        # processes).
        self._strikes: dict[str, tuple[float, int]] = {}  # id -> (decay_at, count)
        self._blocked_until: dict[str, float] = {}

    def _block_duration(self, strikes: int) -> int:
        # strikes=1 (the first violation) gets the plain base-window block;
        # each further violation doubles it from there.
        exponent = min(max(strikes - 1, 0), MAX_STRIKE_EXPONENT)
        return min(
            self.window * (STRIKE_BACKOFF_BASE**exponent), self.max_block_seconds
        )

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        identifier = self._identify_requester(request)
        allowed, retry_after = await self._consume(request, identifier)
        if not allowed:
            headers = {"Retry-After": str(max(1, int(retry_after)))}
            return JSONResponse(
                error_body(ErrorCode.RATE_LIMITED, "Too many requests"),
                status_code=429,
                headers=headers,
            )

        return await call_next(request)

    @staticmethod
    def _identify_requester(request: Request) -> str:
        # Delegates to the shared trusted-proxy-aware resolver (utils/client_ip)
        # instead of trusting the client-controlled first X-Forwarded-For hop --
        # that used to let any caller pick a fresh rate-limit bucket for free.
        return resolve_client_ip(request)

    async def _consume(self, request: Request, identifier: str) -> tuple[bool, int]:
        redis_client = self._redis(request)
        if redis_client is not None:
            allowed, retry_after = await self._consume_redis(redis_client, identifier)
            if allowed is not None:
                self._mark_healthy(request)
                return allowed, retry_after
            # Redis was configured but unreachable/slow: fall back to per-process
            # limiting, but make the degraded state loudly visible (M1).
            self._mark_degraded(request)

        return await self._consume_memory(identifier)

    def _mark_degraded(self, request: Request) -> None:
        if not self.degraded:
            self.degraded = True
            logger.warning(
                "rate_limiter_degraded",
                message="Redis unavailable/slow; falling back to weaker "
                "per-process rate limiting.",
                redis_timeout=self.redis_timeout,
            )
        try:
            request.app.state.rate_limit_degraded = True
        except Exception:  # pragma: no cover - defensive
            pass

    def _mark_healthy(self, request: Request) -> None:
        if self.degraded:
            self.degraded = False
            logger.info(
                "rate_limiter_recovered",
                message="Redis-backed rate limiting restored.",
            )
        try:
            request.app.state.rate_limit_degraded = False
        except Exception:  # pragma: no cover - defensive
            pass

    @staticmethod
    def _redis(request: Request) -> Optional[Redis]:
        client = getattr(request.app.state, "redis", None)
        return client if isinstance(client, Redis) else None

    async def _consume_redis(
        self, client: Redis, identifier: str
    ) -> tuple[Optional[bool], int]:
        block_key = f"ratelimit:block:{identifier}"
        try:
            async with asyncio.timeout(self.redis_timeout):
                block_ttl = await client.ttl(block_key)
        except Exception:
            return None, self.window
        if block_ttl and block_ttl > 0:
            return False, int(block_ttl)

        key = f"ratelimit:{identifier}:{self.window}"
        try:
            async with asyncio.timeout(self.redis_timeout):
                async with client.pipeline() as pipe:
                    pipe.incr(key)
                    pipe.expire(key, self.window, nx=True)
                    count, _ = await pipe.execute()
                ttl = await client.ttl(key)
            remaining_window = self.window if ttl is None or ttl < 0 else int(ttl)
        except Exception:
            return None, self.window

        current = int(count)
        if current <= self.limit:
            return True, max(self.limit - current, 0)

        retry_after = await self._escalate_redis(client, identifier, remaining_window)
        return False, retry_after

    async def _escalate_redis(
        self, client: Redis, identifier: str, fallback_retry_after: int
    ) -> int:
        strikes_key = f"ratelimit:strikes:{identifier}"
        block_key = f"ratelimit:block:{identifier}"
        try:
            async with asyncio.timeout(self.redis_timeout):
                strikes = await client.incr(strikes_key)
                await client.expire(strikes_key, self.strike_decay_seconds)
                block_seconds = self._block_duration(int(strikes))
                await client.set(block_key, int(strikes), ex=block_seconds)
        except Exception:
            return fallback_retry_after
        return block_seconds

    async def _consume_memory(self, identifier: str) -> tuple[bool, int]:
        now = time.monotonic()
        lock = self._locks.get(identifier)
        if lock is None:
            async with self._locks_lock:
                if identifier not in self._locks:
                    self._locks[identifier] = asyncio.Lock()
                lock = self._locks[identifier]

        async with lock:
            blocked_until = self._blocked_until.get(identifier)
            if blocked_until and blocked_until > now:
                return False, max(1, int(blocked_until - now))

            expires_at, count = self._buckets.get(identifier, (now + self.window, 0))
            if expires_at <= now:
                expires_at = now + self.window
                count = 0
            count += 1
            self._buckets[identifier] = (expires_at, count)

            if count <= self.limit:
                return True, max(self.limit - count, 0)

            decay_at, strikes = self._strikes.get(identifier, (0.0, 0))
            if decay_at <= now:
                strikes = 0
            strikes += 1
            self._strikes[identifier] = (now + self.strike_decay_seconds, strikes)
            block_seconds = self._block_duration(strikes)
            self._blocked_until[identifier] = now + block_seconds
            return False, block_seconds
