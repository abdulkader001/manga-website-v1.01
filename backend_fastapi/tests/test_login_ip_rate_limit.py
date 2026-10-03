"""Roadmap item 6: per-IP cap on the Google and Microsoft login entry points."""

from __future__ import annotations

import os

import pytest


@pytest.fixture()
def limiter_active(monkeypatch):
    # The limiter is skipped while TESTING is on; production turns it back on.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_PLAINTEXT_SECRETS", "0")
    from backend_fastapi.app.utils.endpoint_limiter import async_endpoint_limiter

    def clear():
        async_endpoint_limiter._buckets.clear()
        # With REDIS_URL set (CI) the counts live in Redis, and each test
        # must start with a full budget.
        url = os.getenv("REDIS_URL")
        if url:
            import redis

            client = redis.Redis.from_url(url)
            for key in client.scan_iter("endpointlimit:login_source:*"):
                client.delete(key)

    clear()
    yield
    clear()


def test_google_login_is_limited_per_ip(fastapi_client, limiter_active) -> None:
    statuses = [
        fastapi_client.get("/auth/google", follow_redirects=False).status_code
        for _ in range(31)
    ]
    assert 429 not in statuses[:30]
    assert statuses[30] == 429


def test_google_callback_shares_the_same_budget(fastapi_client, limiter_active) -> None:
    for _ in range(30):
        fastapi_client.get("/auth/google/callback", follow_redirects=False)
    assert (
        fastapi_client.get("/auth/google/callback", follow_redirects=False).status_code
        == 429
    )


def test_microsoft_login_and_callback_share_the_same_budget(fastapi_client, limiter_active) -> None:
    # plan.md P2-3: Microsoft sign-in had no per-address limit at all.
    statuses = [
        fastapi_client.get("/auth/microsoft", follow_redirects=False).status_code
        for _ in range(30)
    ]
    assert 429 not in statuses
    assert (
        fastapi_client.get("/auth/microsoft/callback", follow_redirects=False).status_code
        == 429
    )
