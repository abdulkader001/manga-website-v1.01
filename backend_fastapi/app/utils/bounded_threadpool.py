import math
import os

import anyio

_heavy_limiter = anyio.CapacityLimiter(
    math.ceil(anyio.CapacityLimiter(40).total_tokens / 2)
    if hasattr(anyio.CapacityLimiter(40), "total_tokens")
    else 10
)

_db_limiter = anyio.CapacityLimiter(85)


async def run_in_heavy_threadpool(func, *args, **kwargs):
    import anyio.to_thread
    import functools

    if kwargs:
        func = functools.partial(func, **kwargs)
    return await anyio.to_thread.run_sync(func, *args, limiter=_heavy_limiter)


async def run_in_db_threadpool(func, *args, **kwargs):
    import anyio.to_thread
    import functools

    if kwargs:
        func = functools.partial(func, **kwargs)
    return await anyio.to_thread.run_sync(func, *args, limiter=_db_limiter)


# Page OCR + translation (seconds of CPU and network per page). Kept small so a
# burst of readers can't start more OCR jobs than the CPU can run; the rest
# wait their turn instead of stalling the event loop (F-93).
_page_limiter = anyio.CapacityLimiter(max(1, int(os.getenv("PAGE_PROCESSING_CONCURRENCY", "2") or 2)))


async def run_in_page_pool(func, *args, **kwargs):
    import anyio.to_thread
    import functools

    if kwargs:
        func = functools.partial(func, **kwargs)
    return await anyio.to_thread.run_sync(func, *args, limiter=_page_limiter)
