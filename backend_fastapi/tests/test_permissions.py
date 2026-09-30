"""Granular per-person permission system (SRS 1F.6–1F.10)."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import ApprovedSourceDomain, User, UserRole
from backend_fastapi.app.services.permissions_service import has_permission


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"u-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="U",
        role=role,
        is_main_admin=main,
        is_secondary_admin=secondary,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _headers(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def test_catalogue_excludes_never_grantable(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    resp = fastapi_client.get(
        "/api/admin/permissions/catalogue", headers=_headers(admin_id)
    )
    assert resp.status_code == 200
    keys = {p["key"] for p in resp.json()["permissions"]}
    assert "approve_website" in keys
    # Never-grantable capabilities are absent entirely (SRS 1F.8).
    for forbidden in (
        "view_user_credentials",
        "modify_permanent_admin",
        "alter_rank",
        "edit_audit_log",
    ):
        assert forbidden not in keys


def test_secondary_default_cannot_approve_website(fastapi_client):
    session = SessionLocal()
    try:
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    resp = fastapi_client.post(
        "/api/admin/approved-domains",
        headers=_headers(sec_id),
        json={"url": "https://blocked.example"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_permanent_admin_can_delegate_website_approval(fastapi_client):
    """Granting approve_website to a secondary admin lets them approve (Req 8)."""
    session = SessionLocal()
    try:
        session.query(ApprovedSourceDomain).filter_by(
            domain="delegated.example"
        ).delete()
        session.commit()
        admin_id = _user(session, UserRole.ADMIN, main=True)
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    # PA grants the permission per-person.
    grant = fastapi_client.put(
        f"/api/admin/users/{sec_id}/permissions",
        headers=_headers(admin_id),
        json={"overrides": [{"permission": "approve_website", "state": "granted"}]},
    )
    assert grant.status_code == 200

    # The secondary admin can now approve — effect is immediate (next request).
    approved = fastapi_client.post(
        "/api/admin/approved-domains",
        headers=_headers(sec_id),
        json={"url": "https://delegated.example"},
    )
    assert approved.status_code == 201


def test_never_grantable_is_refused(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
        target_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    resp = fastapi_client.put(
        f"/api/admin/users/{target_id}/permissions",
        headers=_headers(admin_id),
        json={
            "overrides": [{"permission": "view_user_credentials", "state": "granted"}]
        },
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_only_permanent_admin_can_change_overrides(fastapi_client):
    session = SessionLocal()
    try:
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
        other_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    # A secondary admin cannot edit anyone's overrides.
    resp = fastapi_client.put(
        f"/api/admin/users/{other_id}/permissions",
        headers=_headers(sec_id),
        json={"overrides": [{"permission": "approve_website", "state": "granted"}]},
    )
    assert resp.status_code == 403


def test_revoke_takes_effect_and_reset_restores(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    # Secondary holds configure_ocr by default.
    session = SessionLocal()
    try:
        sec = session.get(User, sec_id)
        assert has_permission(session, sec, "configure_ocr") is True
    finally:
        session.close()

    # PA revokes it.
    fastapi_client.put(
        f"/api/admin/users/{sec_id}/permissions",
        headers=_headers(admin_id),
        json={"overrides": [{"permission": "configure_ocr", "state": "revoked"}]},
    )
    session = SessionLocal()
    try:
        sec = session.get(User, sec_id)
        assert has_permission(session, sec, "configure_ocr") is False
    finally:
        session.close()

    # Reset restores the role default.
    reset = fastapi_client.post(
        f"/api/admin/users/{sec_id}/permissions/reset", headers=_headers(admin_id)
    )
    assert reset.status_code == 200
    session = SessionLocal()
    try:
        sec = session.get(User, sec_id)
        assert has_permission(session, sec, "configure_ocr") is True
    finally:
        session.close()


def test_cannot_override_permanent_admin(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _user(session, UserRole.ADMIN, main=True)
        pa_id = _user(session, UserRole.PERMANENT, main=True)
        session.get(User, pa_id).permanent = True
        session.commit()
    finally:
        session.close()

    resp = fastapi_client.put(
        f"/api/admin/users/{pa_id}/permissions",
        headers=_headers(admin_id),
        json={"overrides": [{"permission": "approve_website", "state": "revoked"}]},
    )
    assert resp.status_code == 403


def test_flag_only_admin_gets_matching_catalogue_permissions():
    """F-4: has_permission used to consult only user.role, ignoring the
    admin boolean flags the role-tier gates (is_secondary_or_higher, used by
    require_admin_user) already honour. A row with role=USER but
    is_secondary_admin=True was simultaneously authorised by the role-tier
    gate and refused by the permission catalogue for the same page.
    """
    from backend_fastapi.app.dependencies.auth import is_secondary_or_higher

    session = SessionLocal()
    try:
        flag_only_secondary = User(
            email=f"flagsec-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="FlagSecondary",
            role=UserRole.USER,
            is_secondary_admin=True,
            provider="magic_link",
        )
        session.add(flag_only_secondary)
        session.commit()
        session.refresh(flag_only_secondary)

        assert is_secondary_or_higher(flag_only_secondary) is True
        # "submit_manga_url" has a True secondary default in the catalogue.
        assert has_permission(session, flag_only_secondary, "submit_manga_url") is True
    finally:
        session.close()


def test_permanent_flag_without_role_is_treated_as_main_admin_everywhere():
    """F-5: admin_service._is_main omitted the `permanent` flag that
    dependencies.auth.is_main_admin checks, so a `permanent=True, role=USER`
    account passed require_main_admin_user on every route but was treated as
    a Secondary Administrator inside promote_to_moderator/demote_moderator
    -- capped by the moderator limit and refused demoting moderators they
    didn't personally assign, an unexplainable lockout for the one tier that
    is supposed to have no limits. Both call sites now resolve through the
    same effective_role used everywhere else.
    """
    from backend_fastapi.app.dependencies.auth import is_main_admin
    from backend_fastapi.app.services.admin_service import (
        DEFAULT_MODERATOR_LIMIT,
        count_moderators_for,
        promote_to_moderator,
    )

    session = SessionLocal()
    try:
        permanent_flag_only = User(
            email=f"permflag-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="PermanentFlagOnly",
            role=UserRole.USER,
            permanent=True,
            provider="magic_link",
        )
        session.add(permanent_flag_only)
        session.commit()
        session.refresh(permanent_flag_only)

        assert is_main_admin(permanent_flag_only) is True

        # Promote past DEFAULT_MODERATOR_LIMIT + 1 moderators -- a Secondary
        # Administrator would hit MODERATOR_LIMIT_REACHED well before this;
        # a genuine main admin must not.
        for i in range(DEFAULT_MODERATOR_LIMIT + 1):
            target = User(
                email=f"modtarget-{uuid.uuid4().hex}@example.com",
                is_active=True,
                name=f"Mod{i}",
                role=UserRole.USER,
                provider="magic_link",
            )
            session.add(target)
            session.commit()
            session.refresh(target)
            promote_to_moderator(session, target, permanent_flag_only)

        assert (
            count_moderators_for(session, permanent_flag_only.id) == 0
        ), "a main admin's promotions must be unassigned, not counted against their own cap"
    finally:
        session.close()
