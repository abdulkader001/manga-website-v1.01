"""Logout and refresh rotation must actually end a session (Tier 2.9).

Before this, both tokens were stateless JWTs with no server-side state: the
signature was the whole check, so a token stayed valid until it expired no
matter what the server did. ``POST /auth/logout`` deleted the browser's
cookies and nothing else — a refresh token captured off the wire or lifted
from a stolen browser profile kept working for the full configured session
length (1–30 days).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from backend_fastapi.app.models import RevokedToken, User, UserRole
from backend_fastapi.app.services import token_revocation


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def user_id() -> int:
    with SessionLocal() as session:
        user = User(
            email=f"revoke-{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_every_token_carries_a_unique_jti(user_id: int):
    first = decode_token(create_access_token(str(user_id)))
    second = decode_token(create_access_token(str(user_id)))

    assert first["jti"] and second["jti"]
    assert first["jti"] != second["jti"], "jti must be unique per token"


def test_logout_revokes_the_access_token(fastapi_client, user_id: int):
    token = create_access_token(str(user_id))
    assert fastapi_client.get("/api/auth/me", headers=_auth(token)).status_code == 200

    logout = fastapi_client.post("/api/auth/logout", headers=_auth(token))
    assert logout.status_code == 200

    after = fastapi_client.get("/api/auth/me", headers=_auth(token))
    assert after.status_code == 401, (
        "the token presented at logout must stop working; clearing the cookie "
        "does nothing for a client that kept a copy"
    )


def test_refresh_rotates_and_burns_the_presented_token(fastapi_client, user_id: int):
    refresh = create_refresh_token(str(user_id))

    first = fastapi_client.post(
        "/api/auth/refresh", json={"refresh_token": refresh}
    )
    assert first.status_code == 200, first.text
    rotated = first.json()["refresh_token"]
    assert rotated != refresh, "each refresh must issue a new refresh token"

    replay = fastapi_client.post(
        "/api/auth/refresh", json={"refresh_token": refresh}
    )
    assert replay.status_code == 401, "a consumed refresh token must not work twice"


def test_refresh_token_reuse_revokes_every_session(fastapi_client, user_id: int):
    """Replay means two parties hold the same token; neither keeps the session."""

    refresh = create_refresh_token(str(user_id))
    first = fastapi_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert first.status_code == 200
    rotated = first.json()["refresh_token"]

    # The attacker replays the original.
    replay = fastapi_client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert replay.status_code == 401

    # The legitimate client's freshly-rotated token is now dead too.
    after = fastapi_client.post("/api/auth/refresh", json={"refresh_token": rotated})
    assert after.status_code == 401, (
        "reuse detection must invalidate the whole account's sessions -- there "
        "is no way to tell the thief from the victim"
    )


def test_logout_all_revokes_other_outstanding_sessions(fastapi_client, user_id: int):
    phone = create_access_token(str(user_id))
    laptop = create_access_token(str(user_id))

    assert fastapi_client.get("/api/auth/me", headers=_auth(phone)).status_code == 200
    assert fastapi_client.get("/api/auth/me", headers=_auth(laptop)).status_code == 200

    out = fastapi_client.post("/api/auth/logout?all=true", headers=_auth(laptop))
    assert out.status_code == 200
    assert out.json()["message"] == "logged_out_everywhere"

    assert fastapi_client.get("/api/auth/me", headers=_auth(phone)).status_code == 401
    assert fastapi_client.get("/api/auth/me", headers=_auth(laptop)).status_code == 401


def test_a_token_minted_after_the_cutoff_still_works(fastapi_client, user_id: int):
    """Revocation ends existing sessions; it must not lock the account out."""

    fastapi_client.post(
        "/api/auth/logout?all=true", headers=_auth(create_access_token(str(user_id)))
    )

    fresh = create_access_token(str(user_id))
    assert fastapi_client.get("/api/auth/me", headers=_auth(fresh)).status_code == 200


def test_admin_can_revoke_another_users_sessions(fastapi_client, user_id: int):
    with SessionLocal() as session:
        admin = User(
            email=f"revoke-admin-{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_id = admin.id

    victim_token = create_access_token(str(user_id))
    assert (
        fastapi_client.get("/api/auth/me", headers=_auth(victim_token)).status_code
        == 200
    )

    resp = fastapi_client.post(
        f"/api/admin/users/{user_id}/revoke-sessions",
        headers=_auth(create_access_token(str(admin_id))),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sessions_revoked"] is True

    assert (
        fastapi_client.get("/api/auth/me", headers=_auth(victim_token)).status_code
        == 401
    )


def test_ordinary_user_cannot_revoke_sessions(fastapi_client, user_id: int):
    resp = fastapi_client.post(
        f"/api/admin/users/{user_id}/revoke-sessions",
        headers=_auth(create_access_token(str(user_id))),
    )
    assert resp.status_code == 403


def test_purge_drops_only_rows_whose_token_already_expired(user_id: int):
    with SessionLocal() as session:
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        stale_jti = uuid.uuid4().hex
        live_jti = uuid.uuid4().hex
        session.add_all(
            [
                RevokedToken(
                    jti=stale_jti,
                    user_id=user_id,
                    token_type="refresh",
                    expires_at=now - timedelta(days=1),
                ),
                RevokedToken(
                    jti=live_jti,
                    user_id=user_id,
                    token_type="refresh",
                    expires_at=now + timedelta(days=1),
                ),
            ]
        )
        session.commit()

        token_revocation.purge_expired(session)

        remaining = {
            row.jti
            for row in session.query(RevokedToken)
            .filter(RevokedToken.jti.in_([stale_jti, live_jti]))
            .all()
        }

    assert stale_jti not in remaining, "an expired token needs no denylist row"
    assert live_jti in remaining, "a still-valid token must stay revoked"
