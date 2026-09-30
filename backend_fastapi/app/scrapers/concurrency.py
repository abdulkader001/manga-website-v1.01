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
