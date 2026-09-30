"""Regression tests for cookie auth (C1) and double-submit CSRF (C6).

These assert the previously-broken paths are now closed:
- ``get_current_user`` accepts the httponly ``access_token_cookie`` (C1), and
- the CSRF middleware validates the token *value*, not just its presence (C6):
  a cookie-authenticated state-changing request with a missing or mismatched
  ``X-CSRF-Token`` header is rejected (it used to pass with any header).

Cookies are sent via a raw ``Cookie`` header because the repo's local httpx
test stub has no cookie jar; Starlette still parses ``request.cookies`` from it.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole
from _support.db_reset import clear_users


def _make_user() -> int:
    session = SessionLocal()
    try:
        clear_users(session)
        user = User(
            email="cookie@example.com",
            is_active=True,
            name="Cookie User",
            username="cookieuser",
            provider="magic_link",
            role=UserRole.USER,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id
    finally:
        session.close()


def _cookie(**cookies: str) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _set_cookie_values(response) -> list[str]:
    raw = response.headers
    items = raw.items() if hasattr(raw, "items") else raw
    return [v for (k, v) in items if k.lower() == "set-cookie"]


def test_cookie_auth_authenticates_protected_get(fastapi_app):
    uid = _make_user()
    token = create_access_token(str(uid))
    with TestClient(fastapi_app) as client:
        resp = client.get(
            "/api/auth/me", headers={"Cookie": _cookie(access_token_cookie=token)}
        )
        assert resp.status_code == 200


def test_missing_credentials_still_rejected(fastapi_app):
    with TestClient(fastapi_app) as client:
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401


def test_csrf_rejects_missing_header(fastapi_app):
    uid = _make_user()
    token = create_access_token(str(uid))
    with TestClient(fastapi_app) as client:
        resp = client.post(
            "/api/auth/logout",
            headers={
                "Cookie": _cookie(
                    access_token_cookie=token, csrf_token="the-real-token"
                )
            },
        )
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["error"]["message"]


def test_csrf_rejects_mismatched_header(fastapi_app):
    """This is the exploit that used to succeed: any header value passed."""
    uid = _make_user()
    token = create_access_token(str(uid))
    with TestClient(fastapi_app) as client:
        resp = client.post(
            "/api/auth/logout",
            headers={
                "Cookie": _cookie(
                    access_token_cookie=token, csrf_token="the-real-token"
                ),
                "X-CSRF-Token": "attacker-guess",
            },
        )
        assert resp.status_code == 403
        assert "CSRF" in resp.json()["error"]["message"]


def test_csrf_allows_matching_header(fastapi_app):
    uid = _make_user()
    token = create_access_token(str(uid))
    with TestClient(fastapi_app) as client:
        resp = client.post(
            "/api/auth/logout",
            headers={
                "Cookie": _cookie(
                    access_token_cookie=token, csrf_token="the-real-token"
                ),
                "X-CSRF-Token": "the-real-token",
            },
        )
        assert resp.status_code == 200


def test_csrf_skipped_for_bearer_auth(fastapi_app):
    """Bearer-authenticated requests carry no CSRF risk and are exempt."""
    uid = _make_user()
    token = create_access_token(str(uid))
    with TestClient(fastapi_app) as client:
        resp = client.post(
            "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200


def test_safe_request_seeds_csrf_cookie(fastapi_app):
    with TestClient(fastapi_app) as client:
        resp = client.get("/api/system/state")
        assert resp.status_code == 200
        assert any("csrf_token=" in v for v in _set_cookie_values(resp))
