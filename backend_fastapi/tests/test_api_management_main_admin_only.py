"""API Management, Admin Settings and Role Management are site-owner powers.

A sub-admin only reaches them when the owner gave the power (with the owner's
authenticator code) and the sub-admin has an authenticator; stored rows, presets
and everyday toggles never open them (tests/test_deputies.py covers granting).
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.permissions import BUILTIN_PRESETS, OWNER_POWERS, catalogue
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import PermissionOverride, User, UserRole
from backend_fastapi.app.services import permissions_service

API_MANAGEMENT = ["view_providers", "manage_providers"]


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


def test_api_management_keys_are_site_owner_powers():
    assert set(API_MANAGEMENT) <= OWNER_POWERS
    entries = {e["key"]: e for e in catalogue()}
    for key in API_MANAGEMENT:
        assert entries[key]["owner_power"] is True
    assert not set(BUILTIN_PRESETS["operations_admin"]["grant"]) & OWNER_POWERS


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


def test_role_management_needs_an_owner_grant(fastapi_client):
    assert set(ROLE_MANAGEMENT) <= OWNER_POWERS
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


def test_admin_settings_destructive_actions_need_site_owner_powers(fastapi_client):
    """Admin Settings can purge caches and delete every series: a sub-admin
    holding every everyday toggle still can't trigger any of it."""

    from backend_fastapi.app.core.permissions import ALL_PERMISSIONS
    from backend_fastapi.app.models import Manga

    grantable = [k for k in ALL_PERMISSIONS if k not in OWNER_POWERS]
    sub = _user(UserRole.SECONDARY, secondary=True, grants=grantable)
    tag = uuid.uuid4().hex[:8]
    with SessionLocal() as session:
        manga = Manga(title=f"Keep {tag}", slug=f"keep-{tag}", source_url=f"https://example.com/{tag}")
        session.add(manga)
        session.commit()
        manga_id = manga.id

    calls = [
        ("post", "/api/v1/admin/settings/clear-cache"),
        ("post", "/api/v1/admin/maintenance/delete-all-manga"),
        ("post", "/api/v1/admin/maintenance/purge-all-images"),
        ("post", "/api/v1/admin/maintenance/mirror-all-images"),
        ("post", "/api/v1/admin/cache/clear"),
        ("post", "/api/v1/admin/cache/refresh"),
        ("patch", "/api/v1/admin/cache/priority"),
        ("post", "/api/v1/admin/settings"),
    ]
    for method, path in calls:
        response = getattr(fastapi_client, method)(path, headers=_h(sub), json={})
        assert response.status_code == 403, (method, path, response.status_code)
    with SessionLocal() as session:
        assert session.get(Manga, manga_id) is not None
