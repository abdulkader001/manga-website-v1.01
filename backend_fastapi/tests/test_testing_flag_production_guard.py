"""Guard against F-13: TESTING/equivalent flags must never grant a bypass in
production.

The magic-link flow used to return the live login token (``debug_token``) and
drop its rate limit whenever ``TESTING=1`` was set, with no check against the
actual deployment environment — a full unauthenticated account-takeover path
for any email if that flag ever reached production. Five sibling sites (rate
limiter, circuit breaker, daily limiter, backpressure, Celery eager mode) had
the same env-var-only pattern.

These tests pin the invariant: when the deployment environment is production,
no test flag grants any bypass, and the process refuses to start in that
combination.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Unit level: the central gate honours the deployment environment, not the raw
# flag. All five request-time sites resolve through test_mode_active().
# ---------------------------------------------------------------------------
def test_test_mode_active_is_false_in_production(monkeypatch) -> None:
    from backend_fastapi.app.core import test_mode

    monkeypatch.setenv("TESTING", "1")

    monkeypatch.setenv("APP_ENV", "production")
    assert test_mode.test_mode_active() is False
    assert test_mode.celery_eager_active() is False

    # Non-production with the flag set keeps the test conveniences available.
    monkeypatch.setenv("APP_ENV", "test")
    assert test_mode.test_mode_active() is True


def test_startup_assertion_rejects_production_plus_test_flag(monkeypatch) -> None:
    from backend_fastapi.app.core import test_mode

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TESTING", "1")
    with pytest.raises(RuntimeError, match="test-mode flags"):
        test_mode.assert_test_flags_safe()

    # CELERY_TASK_ALWAYS_EAGER is treated as an equivalent flag.
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    with pytest.raises(RuntimeError, match="CELERY_TASK_ALWAYS_EAGER"):
        test_mode.assert_test_flags_safe()


def test_settings_refuses_to_construct_in_production_with_test_flag(
    monkeypatch,
) -> None:
    """(c) The app refuses to start under TESTING=1 + APP_ENV=production."""

    from backend_fastapi.app.core.settings import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TESTING", "1")
    with pytest.raises(Exception) as exc:
        Settings()
    assert "test-mode flags" in str(exc.value)


# ---------------------------------------------------------------------------
# Integration level: the live magic-link endpoint under a production
# environment must not leak the token and must still enforce the rate limit.
# The helpers read APP_ENV live, so forcing it here flips behaviour without
# rebooting the app (the startup assertion is exercised separately above).
# ---------------------------------------------------------------------------
@pytest.fixture()
def production_env(monkeypatch):
    # TESTING=1 stays set (as the suite runs it) to prove it is *not* enough.
    monkeypatch.setenv("APP_ENV", "production")
    yield


def test_magic_link_never_leaks_debug_token_in_production(
    fastapi_client, production_env
) -> None:
    """(a) No debug_token in the response body when APP_ENV=production."""

    resp = fastapi_client.post(
        "/auth/request-magic-link",
        json={"email": "takeover-target@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json().get("debug_token") is None


def test_magic_link_rate_limit_still_applies_in_production(
    fastapi_client, production_env
) -> None:
    """(b) The 3-per-hour magic-link rate limit is enforced in production."""

    email = "rate-limited-in-prod@example.com"
    statuses = [
        fastapi_client.post(
            "/auth/request-magic-link", json={"email": email}
        ).status_code
        for _ in range(4)
    ]
    # First 3 allowed, 4th rejected — the limiter is no longer bypassed.
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_all_request_sites_route_through_test_mode_active() -> None:
    """The five request-time bypass sites must call test_mode_active(), not a
    bare os.getenv("TESTING") check."""

    from backend_fastapi.app.utils import (
        circuit_breaker,
        daily_limiter,
        endpoint_limiter,
    )
    from backend_fastapi.app.bootstrap import backpressure
    from backend_fastapi.app.api.routers import auth

    import inspect

    for module in (
        circuit_breaker,
        daily_limiter,
        endpoint_limiter,
        backpressure,
        auth,
    ):
        src = inspect.getsource(module)
        assert (
            "test_mode_active" in src
        ), f"{module.__name__} should gate test behaviour on test_mode_active()"
        assert (
            'os.getenv("TESTING")' not in src
        ), f"{module.__name__} still has a bare os.getenv('TESTING') bypass"
