"""Regression tests for F-66 — session refresh must work from a browser.

Background
----------
``POST /auth/refresh`` declared ``request: RefreshRequest`` and read the token
only from the JSON body, never from cookies. But the browser's only copy of the
refresh token lives in ``refresh_token_cookie``, which is set ``httponly=True``
and is therefore unreadable from JavaScript, and the client correctly sends no
body (``api.js``: ``refresh: () => api.post("/auth/refresh", {})``).

The three pieces were mutually incompatible: the endpoint required a value the
client was architecturally prevented from ever obtaining, so every call returned
422. Session refresh was impossible from a browser, which meant the
admin-configurable 1-30 day session length had no effect — users were silently
logged out at the 60-minute access-token expiry. The failure was invisible
because ``/auth/refresh`` is listed in ``SESSION_CHECK_PATHS``, so the 422 was
swallowed rather than surfaced.

Cookies are sent via a raw ``Cookie`` header because the repo's local httpx test
stub has no cookie jar; Starlette still parses ``request.cookies`` from it. This
mirrors ``test_csrf_and_cookie_auth.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services.auth_service import issue_tokens_for_user
from _support.db_reset import clear_users


def _make_user_with_tokens() -> tuple[int, str, str]:
    session = SessionLocal()
    try:
        clear_users(session)
        user = User(
            email="refresh@example.com",
            is_active=True,
            name="Refresh User",
            username="refreshuser",
            provider="magic_link",
            role=UserRole.USER,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        pair = issue_tokens_for_user(user, session)
        session.commit()
        return user.id, pair.access_token, pair.refresh_token
    finally:
        session.close()


def _set_cookie_values(response) -> list[str]:
    raw = response.headers
    items = raw.items() if hasattr(raw, "items") else raw
    return [v for (k, v) in items if k.lower() == "set-cookie"]


def test_refresh_accepts_the_httponly_cookie_with_no_body(fastapi_app):
    """The real browser call: no body, refresh token only in the cookie.

    Pre-fix this returned 422 ("Field required", loc ["body"]) on every call.
    """

    _, _, refresh_token = _make_user_with_tokens()

    with TestClient(fastapi_app) as client:
        response = client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token_cookie={refresh_token}"},
        )

    assert response.status_code == 200, (
        "POST /auth/refresh with only the httpOnly refresh cookie returned "
        f"{response.status_code}: {response.text}. The browser cannot read that "
        "cookie to put it in a body, so this is the only call it can make."
    )

    body = response.json()
    assert body.get("access_token"), "no access_token in refresh response"
    assert body.get("refresh_token"), "no refresh_token in refresh response"


def test_refresh_accepts_the_clients_literal_empty_object_body(fastapi_app):
    """The exact call the shipped client makes: ``post("/auth/refresh", {})``.

    This is distinct from sending *no* body. An empty JSON object is present
    but does not satisfy a required ``refresh_token``, so Pydantic rejects it
    with 422 before any cookie fallback can run. Making the body optional is
    not enough on its own — the field inside it has to be optional too.

    Caught by the live browser run: the endpoint answered 200 to a bodyless
    curl while still answering 422 to the real client.
    """

    _, _, refresh_token = _make_user_with_tokens()

    with TestClient(fastapi_app) as client:
        response = client.post(
            "/api/v1/auth/refresh",
            json={},
            headers={"Cookie": f"refresh_token_cookie={refresh_token}"},
        )

    assert response.status_code == 200, (
        "POST /auth/refresh with the client's literal {} body returned "
        f"{response.status_code}: {response.text}"
    )
    assert response.json().get("access_token")


def test_refresh_sets_new_auth_cookies(fastapi_app):
    """Refreshing must hand the browser the new tokens.

    Returning a token pair in the body alone is useless to a cookie-based
    client — without new Set-Cookie headers the browser keeps sending the old,
    expired access token and nothing is actually refreshed.
    """

    _, _, refresh_token = _make_user_with_tokens()

    with TestClient(fastapi_app) as client:
        response = client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token_cookie={refresh_token}"},
        )

    assert response.status_code == 200
    cookies = _set_cookie_values(response)
    joined = " | ".join(cookies)

    assert any(c.startswith("access_token_cookie=") for c in cookies), (
        f"refresh did not set a new access_token_cookie; got: {joined}"
    )
    assert any(c.startswith("refresh_token_cookie=") for c in cookies), (
        f"refresh did not set a new refresh_token_cookie; got: {joined}"
    )


def test_refresh_without_any_token_is_401_not_422(fastapi_app):
    """A missing token is an auth failure, not a schema violation.

    422 also caused the client to mis-handle the response: a validation error
    is not something a session-check path can act on.
    """

    with TestClient(fastapi_app) as client:
        response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 401, (
        f"expected 401 for a refresh with no token, got {response.status_code}: "
        f"{response.text}"
    )


def test_refresh_still_accepts_an_explicit_body(fastapi_app):
    """Back-compat: non-browser clients may still post the token explicitly."""

    _, _, refresh_token = _make_user_with_tokens()

    with TestClient(fastapi_app) as client:
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

    assert response.status_code == 200, (
        f"body-supplied refresh regressed: {response.status_code} {response.text}"
    )
    assert response.json().get("access_token")


def test_refresh_rejects_an_access_token_in_the_cookie(fastapi_app):
    """Only a genuine refresh token may refresh — token type is still checked."""

    _, access_token, _ = _make_user_with_tokens()

    with TestClient(fastapi_app) as client:
        response = client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token_cookie={access_token}"},
        )

    assert response.status_code == 401, (
        "an access token was accepted as a refresh token: "
        f"{response.status_code} {response.text}"
    )
