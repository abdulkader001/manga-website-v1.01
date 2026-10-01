"""Permission presets + Modified-only list (SRS 1F.9.1, 1F.9.3)."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services.permissions_service import has_permission


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"p-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="P",
        role=role,
        is_main_admin=main,
        is_secondary_admin=secondary,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def test_presets_include_builtin_titular(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    resp = fastapi_client.get("/api/admin/permissions/presets", headers=_h(admin_id))
    assert resp.status_code == 200
    keys = {p["key"] for p in resp.json()["presets"]}
    assert {"community_moderator", "content_moderator", "titular"} <= keys


def test_apply_titular_strips_all_permissions(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
        mod_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    # A sub-admin holds some defaults.
    session = SessionLocal()
    try:
        mod = session.get(User, mod_id)
        assert has_permission(session, mod, "remove_comments") is True
    finally:
        session.close()

    resp = fastapi_client.post(
        f"/api/admin/users/{mod_id}/permissions/apply-preset",
        headers=_h(admin_id),
        json={"preset": "titular"},
    )
    assert resp.status_code == 200

    session = SessionLocal()
    try:
        mod = session.get(User, mod_id)
        assert has_permission(session, mod, "remove_comments") is False
        assert has_permission(session, mod, "submit_manga_url") is False
    finally:
        session.close()


def test_apply_community_moderator_shapes_permissions(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    fastapi_client.post(
        f"/api/admin/users/{sec_id}/permissions/apply-preset",
        headers=_h(admin_id),
        json={"preset": "community_moderator"},
    )
    session = SessionLocal()
    try:
        sec = session.get(User, sec_id)
        assert has_permission(session, sec, "block_user") is True
        assert has_permission(session, sec, "submit_manga_url") is False
    finally:
        session.close()


def test_create_and_apply_custom_preset(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
        mod_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    key = f"custom_{uuid.uuid4().hex[:6]}"
    created = fastapi_client.post(
        "/api/admin/permissions/presets",
        headers=_h(admin_id),
        json={
            "key": key,
            "label": "Custom",
            "grant": ["approve_website"],
            "revoke": ["remove_comments", "view_user_credentials"],  # last ignored
        },
    )
    assert created.status_code == 200
    # never-grantable key is silently dropped.
    assert "view_user_credentials" not in created.json()["definition"]["revoke"]

    applied = fastapi_client.post(
        f"/api/admin/users/{mod_id}/permissions/apply-preset",
        headers=_h(admin_id),
        json={"preset": key},
    )
    assert applied.status_code == 200
    session = SessionLocal()
    try:
        mod = session.get(User, mod_id)
        assert has_permission(session, mod, "approve_website") is True
    finally:
        session.close()


def test_modified_only_filter(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
        clean_id = _user(session, UserRole.SECONDARY, secondary=True)
        modified_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    # Give one of them an override.
    fastapi_client.put(
        f"/api/admin/users/{modified_id}/permissions",
        headers=_h(admin_id),
        json={"overrides": [{"permission": "approve_website", "state": "granted"}]},
    )

    all_people = fastapi_client.get(
        "/api/admin/permissions/managed", headers=_h(admin_id)
    ).json()["people"]
    ids_all = {p["user_id"] for p in all_people}
    assert clean_id in ids_all and modified_id in ids_all

    only_mod = fastapi_client.get(
        "/api/admin/permissions/managed?modified_only=true", headers=_h(admin_id)
    ).json()["people"]
    ids_mod = {p["user_id"] for p in only_mod}
    assert modified_id in ids_mod
    assert clean_id not in ids_mod


def test_preset_endpoints_require_permanent_admin(fastapi_client):
    session = SessionLocal()
    try:
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
        mod_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    # A secondary admin cannot apply presets.
    resp = fastapi_client.post(
        f"/api/admin/users/{mod_id}/permissions/apply-preset",
        headers=_h(sec_id),
        json={"preset": "titular"},
    )
    assert resp.status_code == 403
