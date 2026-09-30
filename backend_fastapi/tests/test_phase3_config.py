"""Regression tests for Phase 3 config/reliability fixes (items 16, 18, 20)."""

from __future__ import annotations

import pytest

from backend_fastapi.app.core import settings as settings_module
from backend_fastapi.app.core.settings import Settings
from backend_fastapi.app.utils.rate_limiter import (
    DEFAULT_REDIS_TIMEOUT_SECONDS,
    RateLimitMiddleware,
)


def _settings(**overrides):
    base = dict(secret_key="x" * 12, jwt_secret_key="y" * 12)
    base.update(overrides)
    return Settings(**base)


# ---- Item 20: fail loud when the email key is missing (no plaintext PII) ----


def test_missing_email_key_fails_when_plaintext_disabled(monkeypatch):
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: False)
    with pytest.raises(ValueError):
        _settings(email_encryption_key=None)


def test_missing_email_key_allowed_in_plaintext_dev(monkeypatch):
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: True)
    # Should not raise.
    assert _settings(email_encryption_key=None) is not None


# ---- Item 18: alembic check defaults on in staging/production ----


def test_alembic_check_defaults_true_in_production(monkeypatch):
    monkeypatch.delenv("ALEMBIC_CHECK_ON_STARTUP", raising=False)
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: True)
    s = _settings(app_env="production", email_encryption_key=None)
    assert s.alembic_check_on_startup is True


def test_alembic_check_stays_false_in_dev(monkeypatch):
    monkeypatch.delenv("ALEMBIC_CHECK_ON_STARTUP", raising=False)
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: True)
    s = _settings(app_env="local", email_encryption_key=None)
    assert s.alembic_check_on_startup is False


# ---- Item 16: rate limiter uses a realistic timeout and exposes degradation ----


def test_rate_limiter_default_timeout_is_realistic():
    mw = RateLimitMiddleware(app=None, limit=10, window_seconds=60)
    assert mw.redis_timeout == DEFAULT_REDIS_TIMEOUT_SECONDS
    assert mw.redis_timeout >= 0.15  # not the old 20ms fail-open value


def test_rate_limiter_timeout_is_configurable():
    mw = RateLimitMiddleware(app=None, limit=10, window_seconds=60, redis_timeout=0.5)
    assert mw.redis_timeout == 0.5


def test_rate_limiter_marks_and_clears_degraded_state():
    mw = RateLimitMiddleware(app=None, limit=10, window_seconds=60)

    class _State:
        pass

    class _App:
        state = _State()

    class _Req:
        app = _App()

    request = _Req()
    assert mw.degraded is False
    mw._mark_degraded(request)
    assert mw.degraded is True
    assert request.app.state.rate_limit_degraded is True
    mw._mark_healthy(request)
    assert mw.degraded is False
    assert request.app.state.rate_limit_degraded is False
