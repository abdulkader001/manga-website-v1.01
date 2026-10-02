"""Main-admin "sign-in required" switch."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import SystemSettings, User, UserRole


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _switch_off_afterwards():
    yield
    session = SessionLocal()
    try:
        for row in session.query(SystemSettings).all():
            row.login_required = False
        session.commit()
    finally:
        session.close()


def _user(**extra):
    session = SessionLocal()
    try:
        user = User(
            email=f"u-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Someone",
            provider="magic_link",
            **extra,
        )
        session.add(user)
        session.commit()
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    finally:
        session.close()


def _main_admin():
    return _user(role=UserRole.ADMIN, is_main_admin=True, is_secondary_admin=True)


def _sub_admin():
    return _user(role=UserRole.SECONDARY, is_main_admin=False, is_secondary_admin=True)


def _forget_the_settings_row():
    session = SessionLocal()
    try:
        session.query(SystemSettings).delete()
        session.commit()
    finally:
        session.close()


def test_on_by_default_with_no_settings_row(fastapi_client, members_only_default):
    # A brand-new site has no settings row yet: guests are still turned away.
    _forget_the_settings_row()
    assert fastapi_client.get("/api/v1/config/site-access").json() == {"loginRequired": True}
    guest = fastapi_client.get("/api/v1/manga/")
    assert guest.status_code == 401
    assert guest.json()["error"]["code"] == "LOGIN_REQUIRED"
    assert fastapi_client.get("/api/v1/manga/", headers=_user()).status_code == 200


def test_a_new_settings_row_starts_with_it_on():
    # The database default (not the Python-side one, which the shared fixtures
    # switch off): a row inserted without the column comes out on.
    from sqlalchemy import text

    from backend_fastapi.app.models.settings import LOGIN_REQUIRED_DEFAULT

    assert LOGIN_REQUIRED_DEFAULT is True
    _forget_the_settings_row()
    session = SessionLocal()
    try:
        session.execute(text("INSERT INTO system_settings (id) VALUES (1)"))
        session.commit()
        assert session.query(SystemSettings).first().login_required is True
    finally:
        session.close()


def test_sign_in_and_admin_stay_reachable_by_default(fastapi_client, members_only_default):
    _forget_the_settings_row()
    assert fastapi_client.get("/api/v1/config/site-access").status_code == 200
    assert fastapi_client.get("/api/v1/auth/options").status_code == 200
    # The owner can still open Admin Settings and switch it off.
    resp = fastapi_client.put(
        "/api/v1/admin/config/access", headers=_main_admin(), json={"login_required": False}
    )
    assert resp.status_code == 200, resp.text
    assert fastapi_client.get("/api/v1/manga/").status_code == 200


def test_the_switch_reports_off_when_the_owner_turns_it_off(fastapi_client):
    assert fastapi_client.get("/api/v1/config/site-access").json() == {"loginRequired": False}
    assert fastapi_client.get("/api/v1/manga/").status_code == 200


def test_main_admin_switches_it_on_and_guests_are_turned_away(fastapi_client):
    admin = _main_admin()
    resp = fastapi_client.put(
        "/api/v1/admin/config/access", headers=admin, json={"login_required": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"login_required": True}
    assert fastapi_client.get("/api/v1/config/site-access").json() == {"loginRequired": True}

    guest = fastapi_client.get("/api/v1/manga/")
    assert guest.status_code == 401
    assert guest.json()["error"]["code"] == "LOGIN_REQUIRED"

    # A signed-in reader still reads.
    assert fastapi_client.get("/api/v1/manga/", headers=_user()).status_code == 200


def test_sign_in_routes_stay_open_while_it_is_on(fastapi_client):
    fastapi_client.put(
        "/api/v1/admin/config/access", headers=_main_admin(), json={"login_required": True}
    )
    # Requesting a magic link and reading the public config never hit the gate.
    resp = fastapi_client.post("/api/v1/auth/magic-link", json={"email": "x@example.com"})
    assert resp.status_code != 401 or resp.json()["error"]["code"] != "LOGIN_REQUIRED"
    assert fastapi_client.get("/api/v1/config/site-access").status_code == 200


def test_only_the_main_admin_can_toggle(fastapi_client):
    for headers in ({}, _user(), _sub_admin()):
        resp = fastapi_client.put(
            "/api/v1/admin/config/access", headers=headers, json={"login_required": True}
        )
        assert resp.status_code in (401, 403), resp.status_code
        assert fastapi_client.get("/api/v1/admin/config/access", headers=headers).status_code in (401, 403)
    assert fastapi_client.get("/api/v1/config/site-access").json() == {"loginRequired": False}
