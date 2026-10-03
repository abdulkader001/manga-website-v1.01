"""Account lifecycle, data export, and the account-linkage rules (SRS 1E)."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    Bookmark,
    Manga,
    ReadHistory,
    User,
    UserAPIKey,
    UserRole,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _make_user(session) -> int:
    user = User(
        email=f"u-{uuid.uuid4().hex}@gmail.com",
        is_active=True,
        name="U",
        role=UserRole.USER,
        provider="magic_link",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


def _seed_manga(session) -> int:
    m = Manga(title=f"M-{uuid.uuid4().hex}", source_url=f"https://x/{uuid.uuid4().hex}")
    session.add(m)
    session.commit()
    session.refresh(m)
    return m.id


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def test_export_excludes_credentials(fastapi_client):
    session = SessionLocal()
    try:
        uid = _make_user(session)
        session.add(UserAPIKey(user_id=uid, provider="translation", api_key="secret"))
        session.commit()
    finally:
        session.close()

    resp = fastapi_client.get("/api/user/me/export", headers=_headers(uid))
    assert resp.status_code == 200
    body = resp.json()
    # Presence is disclosed; the secret value is not, anywhere in the payload.
    assert "translation" in body["configured_providers"]
    assert "secret" not in str(body)


def test_delete_account_removes_credentials_and_deactivates(fastapi_client):
    session = SessionLocal()
    try:
        uid = _make_user(session)
        manga_id = _seed_manga(session)
        session.add(UserAPIKey(user_id=uid, provider="ocr", api_key="k"))
        session.add(ReadHistory(user_id=uid, manga_id=manga_id))
        session.add(Bookmark(user_id=uid, manga_id=manga_id))
        session.commit()
    finally:
        session.close()

    headers = _headers(uid)
    resp = fastapi_client.delete("/api/user/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["message"] == "account_deleted"

    session = SessionLocal()
    try:
        assert session.query(UserAPIKey).filter_by(user_id=uid).count() == 0
        assert session.query(ReadHistory).filter_by(user_id=uid).count() == 0
        assert session.query(Bookmark).filter_by(user_id=uid).count() == 0
        user = session.get(User, uid)
        assert user is not None  # row retained (user_id not reused)
        assert user.is_active is False
    finally:
        session.close()

    # Sessions effectively revoked: the token no longer authenticates.
    after = fastapi_client.get("/api/user/me/export", headers=headers)
    assert after.status_code == 401


def test_rank_and_role_not_user_editable(fastapi_client):
    """SRS 1E.5.3: users cannot set role/rank/reputation via settings."""
    session = SessionLocal()
    try:
        uid = _make_user(session)
    finally:
        session.close()

    resp = fastapi_client.put(
        "/api/user/settings",
        headers=_headers(uid),
        json={
            "role": "admin",
            "is_main_admin": True,
            "realm": "Immortal",
            "reputation": 999999,
            "username": f"name{uuid.uuid4().hex[:6]}",
        },
    )
    assert resp.status_code in (200, 201)

    session = SessionLocal()
    try:
        user = session.get(User, uid)
        assert user.role == UserRole.USER
        assert user.is_main_admin is False
    finally:
        session.close()


def test_account_data_restored_on_a_fresh_device(fastapi_client):
    """SRS 1E.1A: data is account-keyed, not device-keyed.

    A second, independent token (a 'new device' with empty browser state) sees
    the same server-side data.
    """
    session = SessionLocal()
    try:
        uid = _make_user(session)
        manga_id = _seed_manga(session)
        session.add(Bookmark(user_id=uid, manga_id=manga_id))
        session.commit()
    finally:
        session.close()

    fresh_device_headers = {"Authorization": f"Bearer {create_access_token(str(uid))}"}
    resp = fastapi_client.get("/api/bookmarks/", headers=fresh_device_headers)
    assert resp.status_code == 200
    payload = resp.json()
    items = payload["items"] if isinstance(payload, dict) else payload
    assert any(b.get("manga_id") == manga_id for b in items)
