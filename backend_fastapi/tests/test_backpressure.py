"""Backpressure under load (SRS 4D.3): exhaust the concurrency cap and
confirm requests are rejected clearly (503 + Retry-After), not dropped
silently or queued indefinitely.

BackpressureMiddleware short-circuits entirely under TESTING=1 (so the rest
of the suite isn't rate-limited by it), so this test drives the middleware
directly rather than through the app/TestClient, with TESTING unset for the
duration of the scenario.
"""

from __future__ import annotations

import asyncio

from starlette.responses import Response

from backend_fastapi.app.bootstrap.backpressure import BackpressureMiddleware


class _FakeURL:
    path = "/api/whatever"


class _FakeRequest:
    url = _FakeURL()


async def _slow_call_next(request):
    await asyncio.sleep(0.05)
    return Response(status_code=200)


def _run(coro):
    return asyncio.run(coro)


def test_over_capacity_requests_are_rejected_with_503_and_retry_after(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    mw = BackpressureMiddleware(app=None, max_concurrency=2)

    async def scenario():
        return await asyncio.gather(
            *[mw.dispatch(_FakeRequest(), _slow_call_next) for _ in range(5)]
        )

    results = _run(scenario())
    accepted = [r for r in results if r.status_code == 200]
    rejected = [r for r in results if r.status_code == 503]

    # Capacity is 2, so exactly 2 of the 5 concurrent requests get through --
    # the rest are shed, not silently dropped or left waiting.
    assert len(accepted) == 2
    assert len(rejected) == 3
    for response in rejected:
        assert response.headers["Retry-After"] == "5"
        assert response.status_code == 503


def test_capacity_is_released_after_requests_complete(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    mw = BackpressureMiddleware(app=None, max_concurrency=1)

    async def scenario():
        first = await mw.dispatch(_FakeRequest(), _slow_call_next)
        # The semaphore slot must be released once the first request
        # finishes, so a subsequent request isn't permanently shed.
        second = await mw.dispatch(_FakeRequest(), _slow_call_next)
        return first, second

    first, second = _run(scenario())
    assert first.status_code == 200
    assert second.status_code == 200
