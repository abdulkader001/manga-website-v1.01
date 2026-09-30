import anyio
import math

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
