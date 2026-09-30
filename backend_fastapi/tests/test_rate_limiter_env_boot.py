"""G32: empty (not absent) numeric env vars must not crash the limiter at boot.

.env.example documents RATE_LIMIT_STRIKE_DECAY_SECONDS, RATE_LIMIT_MAX_BLOCK_SECONDS,
and RATE_LIMIT_REDIS_TIMEOUT_SECONDS with blank values so operators see the
knobs exist. ``os.getenv(name, default)`` only substitutes the default when
the key is absent -- an explicit empty string is returned as-is, so
``int("")``/``float("")`` used to raise before the app could start.
"""

from __future__ import annotations

import pytest

from backend_fastapi.app.utils.rate_limiter import (
    DEFAULT_MAX_BLOCK_SECONDS,
    DEFAULT_REDIS_TIMEOUT_SECONDS,
    RateLimitMiddleware,
)


@pytest.mark.parametrize(
    "env_var",
    [
        "RATE_LIMIT_STRIKE_DECAY_SECONDS",
        "RATE_LIMIT_MAX_BLOCK_SECONDS",
        "RATE_LIMIT_REDIS_TIMEOUT_SECONDS",
    ],
)
def test_empty_env_var_does_not_crash_construction(monkeypatch, env_var):
    monkeypatch.setenv(env_var, "")
    mw = RateLimitMiddleware(app=None, limit=10, window_seconds=60)
    assert mw is not None


def test_empty_strike_decay_falls_back_to_window_default(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STRIKE_DECAY_SECONDS", "")
    mw = RateLimitMiddleware(app=None, limit=10, window_seconds=60)
    assert mw.strike_decay_seconds == 60 * 10


def test_empty_max_block_seconds_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_MAX_BLOCK_SECONDS", "")
    mw = RateLimitMiddleware(app=None, limit=10, window_seconds=60)
    assert mw.max_block_seconds == DEFAULT_MAX_BLOCK_SECONDS


def test_empty_redis_timeout_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REDIS_TIMEOUT_SECONDS", "")
    mw = RateLimitMiddleware(app=None, limit=10, window_seconds=60)
    assert mw.redis_timeout == max(0.01, DEFAULT_REDIS_TIMEOUT_SECONDS)
