"""Global platform-default usage ceiling (SRS 2E.3)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend_fastapi.app.core.api_errors import ApiError
from backend_fastapi.app.models import SystemSettings
from backend_fastapi.app.services import platform_ceiling_service as pcs


@pytest.fixture(autouse=True)
def _ensure_tables(fastapi_app):
    yield


class FakeRedis:
    def __init__(self):
        self.store: dict[str, int] = {}
        self._alerted: dict[str, str] = {}

    def pipeline(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incr(self, key):
        self._pending_key = key
        self.store[key] = self.store.get(key, 0) + 1

    def expire(self, key, seconds, nx=False):
        pass

    async def execute(self):
        return [self.store[self._pending_key], True]

    async def get(self, key):
        return self._alerted.get(key)

    async def set(self, key, value, ex=None):
        self._alerted[key] = value


class FakeApp:
    def __init__(self, redis):
        self.state = MagicMock()
        self.state.redis = redis


class FakeRequest:
    def __init__(self, redis):
        self.app = FakeApp(redis)


def _isinstance_patch(monkeypatch, redis_instance):
    # platform_ceiling_service checks isinstance(client, Redis); patch the
    # module-level Redis symbol so our fake passes that check.
    monkeypatch.setattr(pcs, "Redis", type(redis_instance))


def test_noop_when_no_ceiling_configured(db_session, monkeypatch) -> None:
    redis = FakeRedis()
    _isinstance_patch(monkeypatch, redis)
    request = FakeRequest(redis)

    asyncio.run(pcs.check_and_increment(request, db_session, "ocr"))
    assert redis.store == {}


def test_raises_once_ceiling_reached(db_session, monkeypatch) -> None:
    settings = db_session.query(SystemSettings).first()
    if settings is None:
        settings = SystemSettings(id=1)
        db_session.add(settings)
    settings.platform_default_daily_ceiling = 2
    db_session.commit()

    redis = FakeRedis()
    _isinstance_patch(monkeypatch, redis)
    request = FakeRequest(redis)

    asyncio.run(pcs.check_and_increment(request, db_session, "ocr"))  # 1/2, fine
    with pytest.raises(ApiError):
        asyncio.run(
            pcs.check_and_increment(request, db_session, "ocr")
        )  # 2/2 -> blocked

    settings.platform_default_daily_ceiling = None
    db_session.commit()


def test_fails_open_without_redis(db_session, monkeypatch) -> None:
    settings = db_session.query(SystemSettings).first()
    if settings is None:
        settings = SystemSettings(id=1)
        db_session.add(settings)
    settings.platform_default_daily_ceiling = 1
    db_session.commit()

    request = FakeRequest(None)
    asyncio.run(pcs.check_and_increment(request, db_session, "ocr"))  # no raise

    settings.platform_default_daily_ceiling = None
    db_session.commit()
