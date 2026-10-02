"""API Management and Admin Settings are main-admin only (owner's rule).

Sub-admins can't open them in the UI (tiles hidden, routes main-admin only),
can't read them through the API, and Role Management offers no toggle that
would grant them.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.permissions import BUILTIN_PRESETS, MAIN_ADMIN_ONLY, catalogue
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import PermissionOverride, User, UserRole
from backend_fastapi.app.services import permissions_service

API_MANAGEMENT = ["view_providers", "configure_ocr", "configure_translation", "configure_ai", "set_provider_priority"]


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(role: UserRole, *, main: bool = False, secondary: bool = False, grants=()) -> int:
    with SessionLocal() as session:
        user = User(
            email=f"apim-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="APIM",
            role=role,
            is_main_admin=main,
            is_secondary_admin=secondary,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        for key in grants:
            session.add(PermissionOverride(user_id=user.id, permission=key, state="granted"))
        session.commit()
        return user.id


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


MAIN_ONLY_CALLS = [
    ("get", "/api/v1/admin/settings"),
    ("get", "/api/v1/admin/validate-ocr-providers"),
    ("get", "/api/v1/config"),
    ("post", "/api/v1/admin/database/alembic-status"),
    ("get", "/api/v1/admin/system-providers"),
    ("get", "/api/v1/admin/providers"),
]


def test_api_management_keys_are_main_admin_only():
    assert set(API_MANAGEMENT) <= MAIN_ADMIN_ONLY
    entries = {e["key"]: e for e in catalogue()}
    for key in API_MANAGEMENT:
        assert entries[key]["main_admin_only"] is True
    assert not set(BUILTIN_PRESETS["operations_admin"]["grant"]) & MAIN_ADMIN_ONLY


def test_stored_api_management_grants_do_nothing():
    sub = _user(UserRole.SECONDARY, secondary=True, grants=API_MANAGEMENT)
    with SessionLocal() as session:
        user = session.get(User, sub)
        for key in API_MANAGEMENT:
            assert permissions_service.has_permission(session, user, key) is False


def test_sub_admin_cannot_see_admin_settings_or_api_management(fastapi_client):
    sub = _user(UserRole.SECONDARY, secondary=True, grants=API_MANAGEMENT)
    for method, path in MAIN_ONLY_CALLS:
        response = getattr(fastapi_client, method)(path, headers=_h(sub))
        assert response.status_code == 403, (method, path, response.status_code)


def test_main_admin_still_can(fastapi_client):
    main = _user(UserRole.ADMIN, main=True)
    for method, path in MAIN_ONLY_CALLS:
        if method != "get":
            continue
        response = fastapi_client.get(path, headers=_h(main))
        assert response.status_code == 200, (path, response.status_code)


def test_session_policy_read_follows_its_permission(fastapi_client):
    plain = _user(UserRole.SECONDARY, secondary=True)
    allowed = _user(UserRole.SECONDARY, secondary=True, grants=["set_session_policy"])
    assert fastapi_client.get("/api/v1/admin/config/session", headers=_h(plain)).status_code == 403
    assert fastapi_client.get("/api/v1/admin/config/session", headers=_h(allowed)).status_code == 200


ROLE_MANAGEMENT = ["promote_secondary", "demote_secondary"]


def test_role_management_is_main_admin_only(fastapi_client):
    assert set(ROLE_MANAGEMENT) <= MAIN_ADMIN_ONLY
    sub = _user(UserRole.SECONDARY, secondary=True, grants=ROLE_MANAGEMENT)
    target = _user(UserRole.USER)
    with SessionLocal() as session:
        user = session.get(User, sub)
        for key in ROLE_MANAGEMENT:
            assert permissions_service.has_permission(session, user, key) is False
    calls = [
        ("get", "/api/v1/admin/permissions/catalogue", None),
        ("get", "/api/v1/admin/permissions/presets", None),
        ("post", "/api/v1/admin/promote-secondary", {"email": "someone@example.com"}),
        ("post", f"/api/v1/admin/promote/{target}", {"role": "secondary_admin"}),
        ("post", f"/api/v1/admin/demote/{target}", {}),
    ]
    for method, path, body in calls:
        kwargs = {"headers": _h(sub)}
        if body is not None:
            kwargs["json"] = body
        response = getattr(fastapi_client, method)(path, **kwargs)
        assert response.status_code == 403, (method, path, response.status_code)
    # A sub-admin still sees their own permissions (drives their admin tiles).
    assert fastapi_client.get("/api/v1/admin/permissions/me", headers=_h(sub)).status_code == 200
