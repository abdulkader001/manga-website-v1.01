"""Verified-email state (SRS 1D.2.4).

Verification's only purpose on this platform is confirming a genuine, reachable
email (for promotions). It is set once the user proves control.
"""

from __future__ import annotations

import uuid

from backend_fastapi.app.core.db import SessionLocal


def _request_token(client, email: str) -> str:
    resp = client.post("/api/auth/request-magic-link", json={"email": email})
    assert resp.status_code == 200
    return resp.json()["debug_token"]


def test_new_account_starts_unverified_then_verifies_on_click(fastapi_client):
    email = f"user-{uuid.uuid4().hex}@gmail.com"

    # Requesting a link creates the account but does not verify it yet.
    token = _request_token(fastapi_client, email)
    session = SessionLocal()
    try:
        from backend_fastapi.app.services.auth_service import get_user_by_email

        user = get_user_by_email(session, email)
        assert user is not None
        assert user.email_verified is False
    finally:
        session.close()

    # Clicking the link proves control of the mailbox -> verified.
    consume = fastapi_client.get(f"/api/auth/magic-link/{token}")
    assert consume.status_code == 200

    session = SessionLocal()
    try:
        from backend_fastapi.app.services.auth_service import get_user_by_email

        user = get_user_by_email(session, email)
        assert user.email_verified is True
        assert user.email_verified_at is not None
    finally:
        session.close()


def test_oauth_sets_verified_from_claim():
    from backend_fastapi.app.services.oauth_service import ensure_google_user

    session = SessionLocal()
    try:
        profile = {
            "email": f"g-{uuid.uuid4().hex}@gmail.com",
            "sub": uuid.uuid4().hex,
            "email_verified": True,
            "name": "G User",
        }
        user = ensure_google_user(session, profile)
        assert user.email_verified is True
    finally:
        session.close()


def test_oauth_rejects_disposable_email():
    from backend_fastapi.app.services.oauth_service import (
        OAuthUserError,
        ensure_google_user,
    )

    session = SessionLocal()
    try:
        profile = {
            "email": f"g-{uuid.uuid4().hex}@mailinator.com",
            "sub": uuid.uuid4().hex,
            "email_verified": True,
        }
        try:
            ensure_google_user(session, profile)
            assert False, "disposable OAuth email should be rejected"
        except OAuthUserError:
            pass
    finally:
        session.close()
