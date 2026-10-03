import redis
import os
import contextlib
import time
from typing import Optional


def get_redis_client() -> Optional[redis.Redis]:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/1")
    if not redis_url:
        return None
    return redis.from_url(redis_url)


@contextlib.contextmanager
def acquire_lock(lock_key: str, timeout: int = 300, wait_for: float = 0.0):
    """
    Acquire a distributed Redis lock.
    """
    client = get_redis_client()
    if not client:
        # Fallback if no redis
        yield True
        return

    lock_value = os.urandom(16).hex()
    acquired = False
    start_time = time.time()

    try:
        while True:
            acquired = client.set(lock_key, lock_value, nx=True, ex=timeout)
            if acquired:
                break
            if time.time() - start_time >= wait_for:
                break
            time.sleep(0.5)

        if acquired:
            yield True
        else:
            yield False
    finally:
        if acquired:
            # Check if we still hold the lock, then delete
            val = client.get(lock_key)
            if val and val.decode() == lock_value:
                client.delete(lock_key)


def check_rate_limit(domain: str, limit: int, window: int) -> bool:
    """
    Distributed rate limiting per domain.
    """
    client = get_redis_client()
    if not client:
        return True

    key = f"scraper:ratelimit:{domain}"
    current = client.get(key)
    if current and int(current) >= limit:
        return False

    pipe = client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window, nx=True)
    pipe.execute()
    return True


DEFAULT_REQUESTS_PER_MINUTE = 30
_local_windows: dict = {}


def requests_per_minute(config: Optional[dict] = None) -> int:
    """How many page requests a minute one website gets.

    The vault setting ``SCRAPER_REQUESTS_PER_MINUTE`` (default 30, up from a
    fixed 10) is the ceiling. A parser may set ``requests_per_minute`` to go
    slower on a strict site; it can't go above the ceiling. The per-site
    AutoThrottle (``throttle.py``) still slows down a site that answers
    slowly or pushes back, whatever this says.
    """

    try:
        ceiling = max(1, min(600, int(os.getenv("SCRAPER_REQUESTS_PER_MINUTE", DEFAULT_REQUESTS_PER_MINUTE))))
    except (TypeError, ValueError):
        ceiling = DEFAULT_REQUESTS_PER_MINUTE
    value = (config or {}).get("requests_per_minute")
    if value is None:
        return ceiling
    try:
        return max(1, min(ceiling, int(value)))
    except (TypeError, ValueError):
        return ceiling


def take_request_slot(domain: str, limit: int, window: int = 60) -> float:
    """Claim one request for ``domain`` in the current window.

    Returns 0 when the request may go now, else the seconds until the window
    resets (sleep that long, then claim again). Atomic in Redis (INCR first,
    so two workers can't both take the last slot); one window per process
    when Redis is not configured.
    """

    try:
        client = get_redis_client()
    except Exception:
        client = None
    if client is not None:
        key = f"scraper:slots:{domain}"
        try:
            count = client.incr(key)
            if count == 1:
                client.expire(key, window)
            if count <= limit:
                return 0.0
            ttl = client.ttl(key)
            if ttl is None or ttl < 0:
                client.expire(key, window)
                ttl = window
            return float(max(1, ttl))
        except Exception:
            pass  # Redis down: fall back to the process-local window
    now = time.time()
    start, count = _local_windows.get(domain, (now, 0))
    if now - start >= window:
        start, count = now, 0
    if count < limit:
        _local_windows[domain] = (start, count + 1)
        return 0.0
    return max(0.5, window - (now - start))
