"""Progressive rate-limit backoff (SRS 4G.1).

Repeated violations from one source must escalate to a longer block each
time, not just repeat the same short one. Exercises the in-memory fallback
path directly (no Redis needed) since it implements the same escalation
Redis does, just with process-local state.
"""

from __future__ import annotations

import asyncio

from backend_fastapi.app.utils.rate_limiter import RateLimitMiddleware


def _run(coro):
    return asyncio.run(coro)


def _middleware(limit: int = 2, window_seconds: int = 10) -> RateLimitMiddleware:
    return RateLimitMiddleware(
        app=None,
        limit=limit,
        window_seconds=window_seconds,
        max_block_seconds=3600,
    )


def test_first_violation_blocks_for_the_window():
    mw = _middleware(limit=2, window_seconds=10)

    async def scenario():
        for _ in range(2):
            allowed, _ = await mw._consume_memory("1.2.3.4")
            assert allowed
        return await mw._consume_memory("1.2.3.4")

    allowed, retry_after = _run(scenario())
    assert not allowed
    assert 1 <= retry_after <= 10


def test_repeated_violations_escalate_beyond_the_base_window():
    mw = _middleware(limit=1, window_seconds=5)
    identifier = "5.6.7.8"

    async def violate_once():
        # First request in a fresh window is allowed; force a second
        # (over-limit) request in the same window to register a violation.
        await mw._consume_memory(identifier)
        return await mw._consume_memory(identifier)

    async def scenario():
        results = []
        for _ in range(3):
            # Reset the window bucket so each call is a *new* violation
            # rather than being short-circuited by the standing block.
            mw._buckets.pop(identifier, None)
            mw._blocked_until.pop(identifier, None)
            results.append(await violate_once())
        return results

    (_, first_retry), (_, second_retry), (_, third_retry) = _run(scenario())
    # Each successive violation escalates strictly further than the last.
    assert first_retry < second_retry < third_retry
    # And every escalated block is longer than the plain base-window block.
    assert first_retry >= mw.window


def test_escalated_block_is_capped_at_max_block_seconds():
    mw = _middleware(limit=1, window_seconds=1)
    mw.max_block_seconds = 20
    identifier = "9.9.9.9"

    async def scenario():
        result = None
        for _ in range(8):
            mw._buckets.pop(identifier, None)
            mw._blocked_until.pop(identifier, None)
            await mw._consume_memory(identifier)
            result = await mw._consume_memory(identifier)
        return result

    _, retry_after = _run(scenario())
    assert retry_after == 20


def test_while_blocked_further_requests_are_rejected_without_a_new_strike():
    mw = _middleware(limit=1, window_seconds=5)
    identifier = "10.0.0.1"

    async def scenario():
        await mw._consume_memory(identifier)
        first_block = await mw._consume_memory(identifier)
        # Still within the escalated block window -- must stay rejected,
        # and the strike count must not have moved.
        strikes_before = mw._strikes[identifier][1]
        second_block = await mw._consume_memory(identifier)
        strikes_after = mw._strikes[identifier][1]
        return first_block, second_block, strikes_before, strikes_after

    first_block, second_block, strikes_before, strikes_after = _run(scenario())
    assert not first_block[0]
    assert not second_block[0]
    assert strikes_before == strikes_after
