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


async def _slow_app(scope, receive, send):
    await asyncio.sleep(0.05)
    await Response(status_code=200)(scope, receive, send)


async def _call(mw):
    """Drive the ASGI middleware once; returns (status, headers)."""

    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/api/whatever", "headers": []}
    await mw(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return start["status"], headers


def _run(coro):
    return asyncio.run(coro)


def test_over_capacity_requests_are_rejected_with_503_and_retry_after(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    mw = BackpressureMiddleware(app=_slow_app, max_concurrency=2)

    async def scenario():
        return await asyncio.gather(*[_call(mw) for _ in range(5)])

    results = _run(scenario())
    accepted = [r for r in results if r[0] == 200]
    rejected = [r for r in results if r[0] == 503]

    # Capacity is 2, so exactly 2 of the 5 concurrent requests get through --
    # the rest are shed, not silently dropped or left waiting.
    assert len(accepted) == 2
    assert len(rejected) == 3
    for _status, headers in rejected:
        assert headers["retry-after"] == "5"


def test_capacity_is_released_after_requests_complete(monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    mw = BackpressureMiddleware(app=_slow_app, max_concurrency=1)

    async def scenario():
        first = await _call(mw)
        # The semaphore slot must be released once the first request
        # finishes, so a subsequent request isn't permanently shed.
        second = await _call(mw)
        return first, second

    first, second = _run(scenario())
    assert first[0] == 200
    assert second[0] == 200
