"""Quota-reached message matches the exact 1H.8.2 wording.

DailyUserLimiter is a no-op in TESTING mode (see the module), so this
exercises the class directly with a fake Redis client and TESTING patched
off, rather than round-tripping through the HTTP stack. Run via asyncio.run
since this repo has no pytest-asyncio dependency.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from backend_fastapi.app.core.api_errors import ApiError, ErrorCode
from backend_fastapi.app.utils.daily_limiter import DailyUserLimiter


class _FakePipeline:
    def __init__(self, count: int):
        self._count = count

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incr(self, key):
        pass

    def expire(self, key, ttl, nx=True):
        pass

    async def execute(self):
        return (self._count, True)


class _FakeRedis:
    def __init__(self, count: int):
        self._count = count

    def pipeline(self):
        return _FakePipeline(self._count)


def test_quota_message_matches_1h_8_2_wording():
    limiter = DailyUserLimiter()
    fake_request = mock.Mock()
    fake_request.app.state.redis = _FakeRedis(count=11)  # over a limit of 10

    with mock.patch(
        "backend_fastapi.app.core.test_mode.test_mode_active", return_value=False
    ), mock.patch.object(
        DailyUserLimiter, "_redis", return_value=fake_request.app.state.redis
    ):
        with pytest.raises(ApiError) as excinfo:
            asyncio.run(
                limiter.check_limit(fake_request, "translation", user_id=1, limit=10)
            )

    err = excinfo.value
    assert err.code == ErrorCode.QUOTA_EXCEEDED
    assert err.status == 429
    assert err.message.startswith(
        "You've reached your translation limit for this period. It resets in"
    )
    assert err.message.endswith("or you can raise it in Settings.")
    assert "retry_after_seconds" in err.details


def test_ocr_quota_message_uses_ocr_label():
    limiter = DailyUserLimiter()
    fake_request = mock.Mock()
    fake_request.app.state.redis = _FakeRedis(count=21)

    with mock.patch(
        "backend_fastapi.app.core.test_mode.test_mode_active", return_value=False
    ), mock.patch.object(
        DailyUserLimiter, "_redis", return_value=fake_request.app.state.redis
    ):
        with pytest.raises(ApiError) as excinfo:
            asyncio.run(limiter.check_limit(fake_request, "ocr", user_id=1, limit=20))

    assert "OCR limit" in excinfo.value.message
