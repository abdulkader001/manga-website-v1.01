"""Roadmap item 6: per-IP cap on the Google login entry points."""

from __future__ import annotations

import pytest


@pytest.fixture()
def limiter_active(monkeypatch):
    # The limiter is skipped while TESTING is on; production turns it back on.
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_PLAINTEXT_SECRETS", "0")
    from backend_fastapi.app.utils.endpoint_limiter import async_endpoint_limiter

    async_endpoint_limiter._buckets.clear()
    yield
    async_endpoint_limiter._buckets.clear()


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
