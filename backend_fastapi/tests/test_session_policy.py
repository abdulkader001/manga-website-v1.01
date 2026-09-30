"""Admin-configurable session expiry policy (SRS 1D.5.1).

Session lifetime is controlled by the admin, integer days, range 1–30.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token, decode_token
from backend_fastapi.app.models import SystemSettings, User, UserRole
from backend_fastapi.app.services.auth_service import (
    SESSION_EXPIRY_DEFAULT_DAYS,
    get_session_expiry_days,
    issue_tokens_for_user,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _reset_settings(session):
    session.query(SystemSettings).delete()
    session.commit()


def _main_admin(session):
    admin = User(
        email=f"admin-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Admin",
        role=UserRole.ADMIN,
        is_main_admin=True,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)
    return admin


def test_default_when_unset():
    session = SessionLocal()
    try:
        _reset_settings(session)
        assert get_session_expiry_days(session) == SESSION_EXPIRY_DEFAULT_DAYS
    finally:
        session.close()


def test_value_is_clamped_to_1_30():
    session = SessionLocal()
    try:
        _reset_settings(session)
        session.add(SystemSettings(id=1, session_expiry_days=99))
        session.commit()
        assert get_session_expiry_days(session) == 30
        session.query(SystemSettings).delete()
        session.add(SystemSettings(id=1, session_expiry_days=0))
        session.commit()
        # 0 is falsy -> default; a stored 0 never yields a 0-day session.
        assert get_session_expiry_days(session) == SESSION_EXPIRY_DEFAULT_DAYS
    finally:
        session.close()


def test_refresh_token_reflects_configured_expiry():
    """A 2-day policy yields a refresh token expiring ~2 days out."""
    import datetime as dt

    session = SessionLocal()
    try:
        _reset_settings(session)
        session.add(SystemSettings(id=1, session_expiry_days=2))
        session.commit()
        user = _main_admin(session)
        pair = issue_tokens_for_user(user, session)
    finally:
        session.close()

    payload = decode_token(pair.refresh_token)
    exp = dt.datetime.fromtimestamp(payload["exp"], tz=dt.timezone.utc)
    now = dt.datetime.now(tz=dt.timezone.utc)
    delta_days = (exp - now).total_seconds() / 86400
    assert 1.5 < delta_days < 2.5


def test_admin_endpoint_get_and_set(fastapi_client):
    session = SessionLocal()
    try:
        _reset_settings(session)
        admin_id = _main_admin(session).id
    finally:
        session.close()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    got = fastapi_client.get("/api/admin/config/session", headers=headers)
    assert got.status_code == 200
    assert got.json()["session_expiry_max_days"] == 30

    put = fastapi_client.put(
        "/api/admin/config/session", headers=headers, json={"session_expiry_days": 13}
    )
    assert put.status_code == 200
    assert put.json()["session_expiry_days"] == 13


def test_admin_endpoint_rejects_out_of_range(fastapi_client):
    session = SessionLocal()
    try:
        _reset_settings(session)
        admin_id = _main_admin(session).id
    finally:
        session.close()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    resp = fastapi_client.put(
        "/api/admin/config/session", headers=headers, json={"session_expiry_days": 45}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_FAILED"
