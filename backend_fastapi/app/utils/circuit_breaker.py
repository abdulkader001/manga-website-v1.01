import time
import structlog
import asyncio

from typing import Optional, Callable, Awaitable, Any
from fastapi import Request
from redis.asyncio import Redis

logger = structlog.get_logger("circuit_breaker")


class RedisCircuitBreaker:
    def __init__(self, failure_threshold=5, failure_window=60, recovery_timeout=300):
        self.failure_threshold = failure_threshold
        self.failure_window = failure_window
        self.recovery_timeout = recovery_timeout

    def _redis(self, request: Request) -> Optional[Redis]:
        client = getattr(request.app.state, "redis", None)
        return client if isinstance(client, Redis) else None

    async def is_allowed(
        self, request: Request, provider_type: str, provider_name: str
    ) -> bool:
        from ..core.test_mode import test_mode_active

        if test_mode_active():
            return True
        redis_client = self._redis(request)
        if not redis_client:
            return True  # Fallback if redis is unavailable

        cb_key = f"circuit:{provider_type}:{provider_name}"
        state_key = f"{cb_key}:state"

        try:
            async with asyncio.timeout(0.005):
                state = await redis_client.get(state_key)
                if state == b"OPEN":
                    # Check if recovery timeout has passed
                    last_failure = await redis_client.get(f"{cb_key}:last_failure")
                    if last_failure:
                        time_since_failure = time.time() - float(last_failure)
                        if time_since_failure > self.recovery_timeout:
                            await redis_client.set(state_key, "HALF-OPEN")
                            logger.info(
                                "Circuit breaker half-open",
                                extra={"provider": provider_name},
                            )
                            return True
                    return False
        except Exception:
            # If Redis times out or fails, fail open
            return True

        return True

    async def record_failure(
        self, request: Request, provider_type: str, provider_name: str
    ):
        redis_client = self._redis(request)
        if not redis_client:
            return

        cb_key = f"circuit:{provider_type}:{provider_name}"
        failures_key = f"{cb_key}:failures"
        state_key = f"{cb_key}:state"
        last_failure_key = f"{cb_key}:last_failure"

        try:
            async with asyncio.timeout(0.005):
                state = await redis_client.get(state_key)

                if state == b"HALF-OPEN":
                    # Immediate trip back to open if failure happens during half-open
                    await redis_client.set(state_key, "OPEN")
                    await redis_client.set(last_failure_key, str(time.time()))
                    logger.warning(
                        "Circuit breaker re-opened from half-open state",
                        extra={"provider": provider_name},
                    )
                    return

                async with redis_client.pipeline() as pipe:
                    pipe.incr(failures_key)
                    pipe.expire(failures_key, self.failure_window, nx=True)
                    count, _ = await pipe.execute()

                if count >= self.failure_threshold:
                    await redis_client.set(state_key, "OPEN")
                    await redis_client.set(last_failure_key, str(time.time()))
                    logger.warning(
                        "Circuit breaker opened due to failures",
                        extra={"provider": provider_name, "failures": count},
                    )
        except Exception:
            pass

    async def record_success(
        self, request: Request, provider_type: str, provider_name: str
    ):
        redis_client = self._redis(request)
        if not redis_client:
            return

        cb_key = f"circuit:{provider_type}:{provider_name}"
        failures_key = f"{cb_key}:failures"
        state_key = f"{cb_key}:state"

        try:
            async with asyncio.timeout(0.005):
                state = await redis_client.get(state_key)
                if state in (b"OPEN", b"HALF-OPEN"):
                    logger.info(
                        "Circuit breaker closed (recovered)",
                        extra={"provider": provider_name},
                    )

                await redis_client.delete(failures_key)
                await redis_client.set(state_key, "CLOSED")
        except Exception:
            pass

    async def execute(
        self,
        request: Request,
        provider_type: str,
        provider_name: str,
        func: Callable[[], Awaitable[Any]],
        timeout_seconds: float = 10.0,
        fallback: Optional[Callable[[], Awaitable[Any]]] = None,
    ) -> Any:
        """Run ``func`` behind the breaker with a timeout.

        Item 43: when a ``fallback`` coroutine is supplied it is used instead of
        raising — both when the circuit is open and when the call
        times out/fails — so a degraded (cached/last-known-good) response can be
        returned rather than failing the whole request.
        """

        if not await self.is_allowed(request, provider_type, provider_name):
            if fallback is not None:
                logger.warning("circuit_open_using_fallback", provider=provider_name)
                return await fallback()
            raise Exception("Circuit breaker is open")

        try:
            async with asyncio.timeout(timeout_seconds):
                result = await func()
                await self.record_success(request, provider_type, provider_name)
                return result
        except Exception:
            await self.record_failure(request, provider_type, provider_name)
            if fallback is not None:
                logger.warning(
                    "provider_call_failed_using_fallback", provider=provider_name
                )
                return await fallback()
            raise


cloud_circuit_breaker = RedisCircuitBreaker()
