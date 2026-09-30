from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from backend_fastapi.app.models import User
from backend_fastapi.app.utils.email_crypto import mask_email


def _user_email(user: User) -> str:
    email = user.email_plaintext
    assert email is not None, "User email should be available for authentication tests"
    return email


def _request_token(client, email: str) -> str:
    """Request a magic link and return the plaintext token.

    Tokens are stored hash-only (SRS 1D.1A.3), so the plaintext cannot be read
    back from the DB — under TESTING the request response returns it directly.
    """
    resp = client.post("/api/auth/request-magic-link", json={"email": email})
    assert resp.status_code == 200
    token = resp.json().get("debug_token")
    assert token, "debug_token should be present under TESTING"
    return token


def _get_headers(response, name: str) -> list[str]:
    headers = getattr(response, "headers", None)
    if headers is None:
        return []
    if hasattr(headers, "getlist"):
        values = headers.getlist(name)
        return list(values) if values else []
    if hasattr(headers, "get"):
        value = headers.get(name)
        return [value] if value is not None else []
    if isinstance(headers, list):
        name_lower = name.lower()
        return [value for key, value in headers if key.lower() == name_lower]
    return []


def _authenticate_with_magic_link(client, email: str) -> tuple[dict[str, str], Any]:
    token_value = _request_token(client, email)
    consume = client.get(f"/api/auth/magic-link/{token_value}")
    assert consume.status_code == 200
    return consume.json(), consume


def test_magic_link_login_and_refresh(fastapi_client, sample_data):
    user = sample_data["user"]

    email = _user_email(user)
    payload, _response = _authenticate_with_magic_link(fastapi_client, email)

    refresh = fastapi_client.post(
        "/api/auth/refresh", json={"refresh_token": payload["refresh_token"]}
    )
    assert refresh.status_code == 200
    refreshed = refresh.json()
    assert refreshed["access_token"].startswith("eyJ")


def test_me_endpoint_never_leaks_oauth_provider_tokens(
    fastapi_client, sample_data, db_session
):
    """F-SSS-02: GET /auth/me must not serialize decrypted OAuth tokens.

    User.access_token/refresh_token are properties that decrypt stored OAuth
    provider tokens; UserRead used to declare matching fields and was applied
    directly to the ORM instance (from_attributes=True), so every profile
    fetch serialized the plaintext secrets.
    """
    user = sample_data["user"]
    user.access_token = "leaked-provider-access-token"
    user.refresh_token = "leaked-provider-refresh-token"
    db_session.add(user)
    db_session.commit()

    email = _user_email(user)
    payload, _response = _authenticate_with_magic_link(fastapi_client, email)

    me = fastapi_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me.status_code == 200
    body = me.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    assert "leaked-provider-access-token" not in me.text
    assert "leaked-provider-refresh-token" not in me.text


def test_password_login_route_removed(fastapi_client, sample_data):
    """Blind Spot #15: the dead password-login route is removed entirely."""
    user = sample_data["user"]

    email = _user_email(user)
    response = fastapi_client.post(
        "/api/auth/login",
        json={"email": email, "password": "irrelevant"},
    )
    # The route no longer exists (was an always-400 dead endpoint).
    assert response.status_code in (404, 405)


def test_magic_link_flow(fastapi_client, sample_data):
    user = sample_data["user"]

    email = _user_email(user)
    payload, response = _authenticate_with_magic_link(fastapi_client, email)
    assert payload["message"] == "magic_link_authenticated"
    assert payload["user"]["email"] is None
    assert payload["user"].get("email_masked") in {None, mask_email(email)}
    assert payload["user"]["email_hash"] == user.email_hash
    cookie_headers = "\n".join(_get_headers(response, "set-cookie"))
    assert "access_token_cookie" in cookie_headers
    assert "refresh_token_cookie" in cookie_headers


def test_magic_link_verify_endpoint(fastapi_client, sample_data):
    user = sample_data["user"]

    email = _user_email(user)
    resp = fastapi_client.post("/api/auth/magic/request", json={"email": email})
    token_value = resp.json()["debug_token"]

    verify = fastapi_client.get("/api/auth/magic/verify", params={"token": token_value})
    assert verify.status_code == 200
    verify_payload = verify.json()
    assert verify_payload["user"]["email"] is None
    assert verify_payload["user"]["email_hash"] == user.email_hash


def test_logout_clears_cookies(fastapi_client):
    response = fastapi_client.post(
        "/api/auth/logout",
        cookies={"access_token_cookie": "abc", "refresh_token_cookie": "def"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "logged_out"
    logout_cookies = "\n".join(_get_headers(response, "set-cookie"))
    assert "access_token_cookie=" in logout_cookies


def test_magic_token_stored_as_hash_not_plaintext(fastapi_client, sample_data):
    """SRS 1D.1A.3: only a hash is persisted; a breach yields no usable link."""
    from backend_fastapi.app.core.db import SessionLocal
    from backend_fastapi.app.models import LoginToken
    from backend_fastapi.app.services.auth_service import hash_login_token

    email = _user_email(sample_data["user"])
    token = _request_token(fastapi_client, email)

    session = SessionLocal()
    try:
        record = session.query(LoginToken).order_by(LoginToken.id.desc()).first()
        assert record is not None
        # The stored value is the hash, never the plaintext token.
        assert record.token_hash != token
        assert record.token_hash == hash_login_token(token)
    finally:
        session.close()


def test_magic_link_is_single_use(fastapi_client, sample_data):
    """SRS 1D.1A.3: a link works once; a second click fails."""
    email = _user_email(sample_data["user"])
    token = _request_token(fastapi_client, email)

    first = fastapi_client.get(f"/api/auth/magic-link/{token}")
    assert first.status_code == 200
    second = fastapi_client.get(f"/api/auth/magic-link/{token}")
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "MAGIC_LINK_ALREADY_USED"


def test_magic_link_invalid_token_returns_error_code(fastapi_client):
    """#6: a token that was never issued maps to MAGIC_LINK_INVALID, not a
    bare unlabeled 400/401."""
    resp = fastapi_client.get("/api/auth/magic-link/not-a-real-token")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "MAGIC_LINK_INVALID"


def test_magic_link_expired_token_returns_error_code(fastapi_client, sample_data):
    """#6: an expired-but-otherwise-valid token maps to MAGIC_LINK_EXPIRED."""
    from datetime import datetime, timedelta

    from backend_fastapi.app.core.db import SessionLocal
    from backend_fastapi.app.models import LoginToken

    email = _user_email(sample_data["user"])
    token = _request_token(fastapi_client, email)

    session = SessionLocal()
    try:
        record = session.query(LoginToken).order_by(LoginToken.id.desc()).first()
        assert record is not None
        record.expires_at = datetime.utcnow() - timedelta(minutes=1)
        session.commit()
    finally:
        session.close()

    resp = fastapi_client.get(f"/api/auth/magic-link/{token}")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "MAGIC_LINK_EXPIRED"


def test_concurrent_magic_link_redemption_succeeds_exactly_once(
    fastapi_client, sample_data
):
    """#55/F-2: two simultaneous redemptions of one token must not both win.

    A corporate mail scanner (Safe Links, URL Defense) fetching the link at
    nearly the same instant as the user's own click is the realistic trigger
    -- not an attacker. Both requests racing the old read-then-write path
    used to return 200; the fix makes the second request's conditional
    UPDATE match zero rows.

    This test's SQLite engine uses StaticPool (one physical connection
    shared by every session, deliberately, so the rest of this suite can run
    without "database is locked" errors) -- real threads issuing statements
    on that one shared connection can occasionally make *both* requests'
    UPDATE see zero rows (an [401, 401] outcome neither this bug nor its fix
    produces; verified separately against real concurrent PostgreSQL
    connections, 30/30 trials landing exactly [200, 401]). That inconclusive
    outcome is retried below. [200, 200] -- the actual vulnerability this
    test guards against -- must never happen, on any attempt.
    """
    import threading

    def _race_once(token: str) -> list[int]:
        barrier = threading.Barrier(2)
        results: list[int] = []
        results_lock = threading.Lock()

        def _redeem() -> None:
            barrier.wait()
            response = fastapi_client.get(f"/api/auth/magic-link/{token}")
            with results_lock:
                results.append(response.status_code)

        threads = [threading.Thread(target=_redeem) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return sorted(results)

    email = _user_email(sample_data["user"])

    for _ in range(15):
        token = _request_token(fastapi_client, email)
        outcome = _race_once(token)
        assert outcome != [200, 200], "both redemptions won -- single-use not enforced"
        if outcome == [200, 401]:
            return

    pytest.fail(
        "never observed a decisive [200, 401] race outcome in 15 attempts "
        f"(last: {outcome}) -- StaticPool contention likely swallowed every "
        "attempt; rerun or investigate"
    )


def test_magic_link_cookies_carry_max_age_matching_session_policy(
    fastapi_client, sample_data, db_session
):
    """F-6: auth cookies must persist for the configured session lifetime,
    not vanish as session cookies at browser-close while the refresh token
    inside keeps living for the admin-configured number of days."""
    from backend_fastapi.app.models import SystemSettings

    db_session.query(SystemSettings).delete()
    db_session.add(SystemSettings(id=1, session_expiry_days=5))
    db_session.commit()

    email = _user_email(sample_data["user"])
    token = _request_token(fastapi_client, email)
    response = fastapi_client.get(f"/api/auth/magic-link/{token}")
    assert response.status_code == 200

    set_cookie_headers = _get_headers(response, "set-cookie")
    refresh_cookie = next(
        h for h in set_cookie_headers if h.startswith("refresh_token_cookie=")
    )
    access_cookie = next(
        h for h in set_cookie_headers if h.startswith("access_token_cookie=")
    )

    assert f"Max-Age={5 * 86400}" in refresh_cookie
    assert "Max-Age=" in access_cookie


def test_new_link_invalidates_previous_unused(fastapi_client, sample_data):
    """SRS 1D.1A.3: issuing a new link invalidates prior unused links."""
    email = _user_email(sample_data["user"])
    first_token = _request_token(fastapi_client, email)
    # Requesting again invalidates the first.
    second_token = _request_token(fastapi_client, email)
    assert first_token != second_token

    stale = fastapi_client.get(f"/api/auth/magic-link/{first_token}")
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "MAGIC_LINK_ALREADY_USED"
    fresh = fastapi_client.get(f"/api/auth/magic-link/{second_token}")
    assert fresh.status_code == 200


def test_auth_options_metadata(fastapi_client):
    response = fastapi_client.get("/api/auth/options")
    assert response.status_code == 200
    payload = response.json()
    assert "magic_link" in payload
    assert payload["magic_link"]["enabled"] is True


def test_magic_link_email_uses_absolute_frontend_url(fastapi_client, monkeypatch):
    """Finding A: the emailed link must be absolute, not a bare relative path.

    Under TESTING=1 (the suite default) the email-send step is skipped
    entirely in favor of returning ``debug_token`` directly, so this test
    turns TESTING off just for this request to exercise the real
    ``send_magic_link_email.delay(...)`` call site and inspect what link it
    was actually given.
    """
    from backend_fastapi.app.core.settings import settings
    from backend_fastapi.app.tasks import email_tasks

    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")
    monkeypatch.setenv("TESTING", "0")

    captured: dict[str, str] = {}

    def fake_delay(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(email_tasks.send_magic_link_email, "delay", fake_delay)

    email = f"abs-link-{uuid4().hex}@example.com"
    resp = fastapi_client.post("/api/auth/request-magic-link", json={"email": email})
    assert resp.status_code == 200

    magic_link = captured.get("magic_link", "")
    assert magic_link.startswith("https://app.example.com/magic-link/")
    assert magic_link.count("/magic-link/") == 1


def test_google_callback_redirects_when_not_configured(fastapi_client, monkeypatch):
    """Finding B: an unconfigured-OAuth failure must land back on /login with
    a status the frontend's statusCopy map can render, not a raw 501 page."""
    from backend_fastapi.app.core.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", None)
    monkeypatch.setattr(settings, "google_oauth_client_secret", None)
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    resp = fastapi_client.get(
        "/api/auth/google/callback", params={"code": "x", "state": "y"}
    )
    assert resp.status_code == 302
    location = _get_headers(resp, "location")
    assert location == ["https://app.example.com/login?magic=provider_disabled"]


def test_google_callback_redirects_on_denied_consent(fastapi_client, monkeypatch):
    """Google omits `code` and sets `error=access_denied` when the user
    declines consent; this must map to the `oauth_denied` banner."""
    from backend_fastapi.app.core.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-secret")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    resp = fastapi_client.get(
        "/api/auth/google/callback",
        params={"error": "access_denied", "state": "y"},
    )
    assert resp.status_code == 302
    location = _get_headers(resp, "location")
    assert location == ["https://app.example.com/login?magic=oauth_denied"]


def test_google_callback_redirects_on_invalid_state(fastapi_client, monkeypatch):
    """A missing/mismatched state cookie is still rejected (the CSRF-state
    check itself is unchanged) but now redirects instead of raising."""
    from backend_fastapi.app.core.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-secret")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    resp = fastapi_client.get(
        "/api/auth/google/callback",
        params={"code": "x", "state": "mismatched-state"},
    )
    assert resp.status_code == 302
    location = _get_headers(resp, "location")
    assert location == ["https://app.example.com/login?magic=oauth_error"]


def test_google_callback_rejects_mismatched_state_cookie(fastapi_client, monkeypatch):
    """#3: state comparison now uses secrets.compare_digest (timing-safe).

    Confirms a present-but-different state cookie is still rejected -- only
    the comparison method changed, not the mismatch outcome. Unlike
    ``test_google_callback_redirects_on_invalid_state`` (no cookie at all,
    short-circuited by ``not expected_state``), this sends a real cookie so
    the ``compare_digest`` call itself is exercised.
    """
    from backend_fastapi.app.core.settings import settings

    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-secret")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    resp = fastapi_client.get(
        "/api/auth/google/callback",
        params={"code": "x", "state": "wrong-state-value"},
        headers={"Cookie": "google_oauth_state=correct-state-value"},
    )
    assert resp.status_code == 302
    location = _get_headers(resp, "location")
    assert location == ["https://app.example.com/login?magic=oauth_error"]


def test_google_callback_redirects_on_exchange_failure(fastapi_client, monkeypatch):
    from backend_fastapi.app.api.routers import auth as auth_router
    from backend_fastapi.app.core.settings import settings
    from backend_fastapi.app.services.oauth_service import OAuthExchangeError

    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-secret")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    def fake_exchange(code, redirect_uri, db):
        raise OAuthExchangeError("boom")

    monkeypatch.setattr(auth_router, "exchange_google_code_for_user", fake_exchange)

    resp = fastapi_client.get(
        "/api/auth/google/callback",
        params={"code": "x", "state": "matched-state"},
        headers={"Cookie": "google_oauth_state=matched-state"},
    )
    assert resp.status_code == 302
    location = _get_headers(resp, "location")
    assert location == ["https://app.example.com/login?magic=oauth_error"]
