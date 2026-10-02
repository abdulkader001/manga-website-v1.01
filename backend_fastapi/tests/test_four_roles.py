"""Four roles: owner, Admin, sub-admin, user (owner's rules, 2026-10-02).

The owner is never changed or touched by anyone and holds everything. An Admin
(at most two) holds almost everything by default, changes only sub-admins and
users, and has its own toggles changed only by the owner. The owner caps what a
sub-admin may ever hold and shares the sub-admin seats between the Admins. Each
Admin keeps a succession line of up to two sub-admins; an idle Admin is
replaced from it (owner's switch), or the owner hands the seat over at once.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.permissions import SUB_ADMIN_POOL
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import AdminActivityDay, AdminAuditLog, AdminSuccessor, PermissionOverride, User, UserRole
from backend_fastapi.app.services import admin_roles, admin_succession, permissions_service
from backend_fastapi.app.services import admin_second_factor as tfa
from backend_fastapi.app.services.system_settings_service import get_or_create_system_settings


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean_slate():
    """Admin seats and the ceiling are site-wide: start every test empty."""

    def reset():
        with SessionLocal() as session:
            session.query(AdminSuccessor).delete()
            session.query(User).filter(User.role == UserRole.CO_ADMIN).update(
                {"role": UserRole.USER, "is_secondary_admin": False}
            )
            row = get_or_create_system_settings(session)
            row.sub_admin_blocked_permissions = None
            row.succession_enabled = False
            row.succession_enabled_at = None
            session.commit()

    reset()
    yield
    reset()


def _user(role: UserRole, *, main=False, authenticator=False, active=True) -> int:
    with SessionLocal() as session:
        user = User(
            # A fresh, large id: SQLite reuses ids of users other tests
            # deleted, and the (append-only) audit log keeps their rows.
            id=random.randint(10**8, 2 * 10**9),
            email=f"r4-{uuid.uuid4().hex}@example.com",
            is_active=active,
            name=f"{role.value}-{uuid.uuid4().hex[:4]}",
            role=role,
            is_main_admin=main,
            is_secondary_admin=role in (UserRole.SECONDARY, UserRole.CO_ADMIN),
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        if authenticator:
            tfa.start_enrolment(session, user)
            user.totp_enabled = True
            session.commit()
        return user.id


def owner(**kw) -> int:
    return _user(UserRole.ADMIN, main=True, authenticator=True, **kw)


def admin(**kw) -> int:
    kw.setdefault("authenticator", True)
    return _user(UserRole.CO_ADMIN, **kw)


def sub(**kw) -> int:
    kw.setdefault("authenticator", True)
    return _user(UserRole.SECONDARY, **kw)


def code(uid: int) -> str:
    """A valid, unused authenticator code for ``uid`` right now."""

    with SessionLocal() as session:
        user = session.get(User, uid)
        user.totp_last_step = None
        session.commit()
        return tfa._code_for_step(tfa._stored_secret(user), tfa._current_step())


def _h(uid: int, *, step_up: bool = True) -> dict:
    headers = {"Authorization": f"Bearer {create_access_token(str(uid))}"}
    if step_up:
        with SessionLocal() as session:
            token = tfa.create_step_up_token(session.get(User, uid))
        headers["Cookie"] = f"{tfa.STEP_UP_COOKIE}={token}"
    return headers


def _set(client, actor: int, target: int, items: dict, *, with_code=False):
    body = {"overrides": [{"permission": k, "state": v} for k, v in items.items()]}
    if with_code:
        body["code"] = code(actor)
    return client.put(f"/api/v1/admin/users/{target}/permissions", json=body, headers=_h(actor))


def _reason(response) -> str:
    return response.json()["error"]["details"]["reason"]


def _has(uid: int, key: str) -> bool:
    with SessionLocal() as session:
        return permissions_service.has_permission(session, session.get(User, uid), key)


def _make_admin(client, boss: int, target: int):
    return client.post("/api/v1/admin/roles/admins", json={"user_id": target, "code": code(boss)}, headers=_h(boss))


# --------------------------------------------------------------------------
# What an Admin holds
# --------------------------------------------------------------------------


def test_an_admin_holds_almost_everything_but_not_settings_cache_or_purge():
    a = admin()
    for key in ("edit_series", "manage_backups", "manage_secret_vault", "manage_roles", "reveal_user_email"):
        assert _has(a, key), key
    for key in ("manage_admin_settings", "manage_cache", "purge_site_data"):
        assert not _has(a, key), key
    # Site-owner powers are paused until the Admin has an authenticator.
    no_phone = admin(authenticator=False)
    assert _has(no_phone, "edit_series") and not _has(no_phone, "manage_backups")


def test_the_owner_switches_an_admins_powers_off_and_on(fastapi_client):
    boss, a = owner(), admin()
    assert fastapi_client.get("/api/v1/admin/backups", headers=_h(a)).status_code == 200

    off = _set(fastapi_client, boss, a, {"manage_backups": "revoked", "edit_series": "revoked"})
    assert off.status_code == 200, off.text
    assert fastapi_client.get("/api/v1/admin/backups", headers=_h(a)).status_code == 403
    assert not _has(a, "edit_series")

    # Taking away needs no code; switching a site-owner power back on does.
    assert _reason(_set(fastapi_client, boss, a, {"manage_backups": "granted"})) == "code_required"
    assert _set(fastapi_client, boss, a, {"manage_backups": "granted"}, with_code=True).status_code == 200
    assert fastapi_client.get("/api/v1/admin/backups", headers=_h(a)).status_code == 200

    # Admin Settings and "delete all manga" start off; the owner can switch them on.
    assert not _has(a, "manage_admin_settings")
    assert _set(fastapi_client, boss, a, {"manage_admin_settings": "granted"}, with_code=True).status_code == 200
    assert _has(a, "manage_admin_settings")


def test_nobody_but_the_owner_changes_an_admin_or_touches_the_owner(fastapi_client):
    boss, a, other, s = owner(), admin(), admin(), sub()
    assert _reason(_set(fastapi_client, a, other, {"edit_series": "revoked"})) == "admin_protected"
    assert _reason(_set(fastapi_client, a, a, {"edit_series": "revoked"})) == "self_change"
    assert _reason(_set(fastapi_client, a, boss, {"edit_series": "revoked"})) == "permanent_admin_immutable"
    assert _reason(_set(fastapi_client, s, a, {"edit_series": "revoked"})) == "missing_power"  # a sub-admin has no Role Management
    reset = fastapi_client.post(f"/api/v1/admin/users/{other}/permissions/reset", headers=_h(a))
    assert _reason(reset) == "admin_protected"
    preset = fastapi_client.post(
        f"/api/v1/admin/users/{other}/permissions/apply-preset", json={"preset": "titular"}, headers=_h(a)
    )
    assert _reason(preset) == "admin_protected"
    # An Admin can't read another Admin's toggles either.
    assert fastapi_client.get(f"/api/v1/admin/users/{other}/permissions", headers=_h(a)).status_code == 403
    assert fastapi_client.get(f"/api/v1/admin/users/{s}/permissions", headers=_h(a)).status_code == 200
    with SessionLocal() as session:
        assert session.query(PermissionOverride).filter_by(user_id=other).count() == 0


def test_a_sub_admin_can_never_manage_roles_or_hold_a_site_owner_power(fastapi_client):
    boss, a, s, other = owner(), admin(), sub(), sub()
    assert fastapi_client.get(f"/api/v1/admin/users/{other}/permissions", headers=_h(s)).status_code == 403
    # Not by the owner, not by an Admin, not as a stored row.
    refused = _set(fastapi_client, boss, s, {"manage_backups": "granted"}, with_code=True)
    assert refused.status_code == 403 and _reason(refused) == "admin_only"
    assert _reason(_set(fastapi_client, a, s, {"manage_backups": "granted"}, with_code=True)) == "owner_only"
    with SessionLocal() as session:
        session.add(PermissionOverride(user_id=s, permission="manage_backups", state="granted"))
        session.commit()
    assert not _has(s, "manage_backups")
    assert fastapi_client.get("/api/v1/admin/backups", headers=_h(s)).status_code == 403


# --------------------------------------------------------------------------
# What an Admin gives, and the owner's ceiling
# --------------------------------------------------------------------------


def test_an_admin_gives_only_what_it_holds_and_the_owner_allows(fastapi_client):
    boss, a, s = owner(), admin(), sub()
    assert _set(fastapi_client, a, s, {"handle_reports": "granted"}).status_code == 200

    assert _reason(_set(fastapi_client, a, s, {"manage_backups": "granted"}, with_code=True)) == "owner_only"

    # The owner takes view_full_audit from this Admin: they can't hand it on.
    assert _set(fastapi_client, boss, a, {"view_full_audit": "revoked"}).status_code == 200
    assert _reason(_set(fastapi_client, a, s, {"view_full_audit": "granted"})) == "not_yours_to_give"

    # The ceiling: nobody gives a sub-admin what the owner blocks.
    blocked = fastapi_client.put(
        "/api/v1/admin/roles/sub-admin-limits",
        json={"blocked": ["approve_website", "manage_backups"], "code": code(boss)},
        headers=_h(boss),
    )
    assert blocked.status_code == 200 and blocked.json()["blocked"] == ["approve_website"]  # owner powers are always out
    refused = _set(fastapi_client, a, s, {"approve_website": "granted"})
    assert refused.status_code == 403 and _reason(refused) == "owner_ceiling"
    assert not _has(s, "approve_website")

    # A sub-admin who already held a blocked power loses it, and gets it back when the owner lifts the ceiling.
    with SessionLocal() as session:
        session.add(PermissionOverride(user_id=s, permission="rollback_series", state="granted"))
        session.commit()
    assert _has(s, "rollback_series")
    fastapi_client.put(
        "/api/v1/admin/roles/sub-admin-limits",
        json={"blocked": ["rollback_series"], "code": code(boss)},
        headers=_h(boss),
    )
    assert not _has(s, "rollback_series")
    states = {p["key"]: p["state"] for p in fastapi_client.get(f"/api/v1/admin/users/{s}/permissions", headers=_h(boss)).json()["permissions"]}
    assert states["rollback_series"] == "blocked"
    fastapi_client.put("/api/v1/admin/roles/sub-admin-limits", json={"blocked": [], "code": code(boss)}, headers=_h(boss))
    assert _has(s, "rollback_series")


def test_the_ceiling_is_the_owners_alone_and_needs_the_owners_code(fastapi_client):
    boss, a = owner(), admin()
    assert fastapi_client.get("/api/v1/admin/roles/sub-admin-limits", headers=_h(a)).status_code == 403
    assert fastapi_client.put("/api/v1/admin/roles/sub-admin-limits", json={"blocked": [], "code": "000000"}, headers=_h(a)).status_code == 403
    assert _reason(
        fastapi_client.put("/api/v1/admin/roles/sub-admin-limits", json={"blocked": ["edit_series"]}, headers=_h(boss))
    ) == "code_required"
    unknown = fastapi_client.put(
        "/api/v1/admin/roles/sub-admin-limits", json={"blocked": ["nope"], "code": code(boss)}, headers=_h(boss)
    )
    assert unknown.status_code == 422


def test_roles_are_made_by_the_owner_and_applied_by_admins_within_the_ceiling(fastapi_client):
    boss, a, s = owner(), admin(), sub()
    key = f"role{uuid.uuid4().hex[:6]}"
    body = {"key": key, "label": "Comment mod", "grant": ["remove_comments", "approve_website"], "revoke": ["edit_series"]}
    assert _reason(fastapi_client.post("/api/v1/admin/permissions/presets", json=body, headers=_h(a))) == "owner_only"
    assert fastapi_client.post("/api/v1/admin/permissions/presets", json=body, headers=_h(boss)).status_code == 200

    fastapi_client.put(
        "/api/v1/admin/roles/sub-admin-limits", json={"blocked": ["approve_website"], "code": code(boss)}, headers=_h(boss)
    )
    applied = fastapi_client.post(f"/api/v1/admin/users/{s}/permissions/apply-preset", json={"preset": key}, headers=_h(a))
    assert applied.status_code == 200, applied.text
    assert _has(s, "remove_comments") and not _has(s, "edit_series") and not _has(s, "approve_website")


# --------------------------------------------------------------------------
# Making Admins
# --------------------------------------------------------------------------


def test_only_the_owner_makes_two_admins_with_their_code(fastapi_client):
    boss, s1, s2, s3, no_phone, a = owner(), sub(), sub(), sub(), sub(authenticator=False), admin()
    with SessionLocal() as session:  # `a` was the one seat in use; free it for this test
        session.query(User).filter_by(id=a).update({"role": UserRole.USER})
        session.commit()

    assert _reason(fastapi_client.post("/api/v1/admin/roles/admins", json={"user_id": s1}, headers=_h(boss))) == "code_required"
    assert _reason(_make_admin(fastapi_client, boss, no_phone)) == "authenticator_required"
    assert _make_admin(fastapi_client, boss, s1).status_code == 200
    assert _make_admin(fastapi_client, boss, s2).status_code == 200
    third = _make_admin(fastapi_client, boss, s3)
    assert third.status_code == 403 and _reason(third) == "admin_limit"

    # An Admin can't make another Admin, nor can a sub-admin.
    assert fastapi_client.post("/api/v1/admin/roles/admins", json={"user_id": s3, "code": code(s1)}, headers=_h(s1)).status_code == 403
    me = fastapi_client.get("/api/v1/admin/permissions/me", headers=_h(s1)).json()
    assert me["role"] == "admin" and me["is_admin"] is True and me["is_main_admin"] is False
    # A plain user can't be made an Admin directly: sub-admin first.
    reader = _user(UserRole.USER, authenticator=True)
    with SessionLocal() as session:
        session.query(User).filter_by(id=s2).update({"role": UserRole.USER})
        session.commit()
    assert _reason(_make_admin(fastapi_client, boss, reader)) == "not_a_sub_admin"


def test_the_owner_removes_an_admin_to_user_or_sub_admin(fastapi_client):
    boss, a1, a2 = owner(), admin(), admin()
    with SessionLocal() as session:
        session.add(PermissionOverride(user_id=a1, permission="edit_series", state="revoked"))
        session.commit()
    assert fastapi_client.post(f"/api/v1/admin/roles/admins/{a1}/demote", json={"to": "sub_admin"}, headers=_h(a2)).status_code == 403
    assert fastapi_client.post(f"/api/v1/admin/roles/admins/{a1}/demote", json={"to": "sub_admin"}, headers=_h(boss)).status_code == 200
    assert fastapi_client.post(f"/api/v1/admin/demote/{a2}", headers=_h(boss)).status_code == 200
    with SessionLocal() as session:
        first, second = session.get(User, a1), session.get(User, a2)
        assert first.role == UserRole.SECONDARY and second.role == UserRole.USER
        assert session.query(PermissionOverride).filter_by(user_id=a1).count() == 0  # the Admin's restrictions go with the seat
    with SessionLocal() as session:
        assert admin_roles.admins(session) == []


def test_an_admin_cannot_demote_an_admin_or_the_owner_but_can_demote_a_sub_admin(fastapi_client):
    boss, a, other, s = owner(), admin(), admin(), sub()
    assert fastapi_client.post(f"/api/v1/admin/demote/{other}", headers=_h(a)).status_code == 403
    assert fastapi_client.post(f"/api/v1/admin/demote/{boss}", headers=_h(a)).status_code == 403
    assert fastapi_client.post(f"/api/v1/admin/demote/{a}", headers=_h(a)).status_code == 403
    assert fastapi_client.post(f"/api/v1/admin/demote/{s}", headers=_h(a)).status_code == 200
    # Nor does anything an Admin sends turn someone into an Admin.
    reader = _user(UserRole.USER)
    for role in ("admin", "permanent_admin", "co_admin"):
        assert fastapi_client.post(f"/api/v1/admin/promote/{reader}", json={"role": role}, headers=_h(a)).status_code == 400
    assert fastapi_client.post("/api/v1/admin/demote-main", json={"user_id": boss}, headers=_h(a)).status_code == 403


# --------------------------------------------------------------------------
# The sub-admin pool
# --------------------------------------------------------------------------


def test_the_pool_is_shared_equally_unless_the_owner_sets_it():
    admin(), admin()
    with SessionLocal() as session:
        shares = admin_roles.quotas(session)
        assert sorted(shares.values()) == [SUB_ADMIN_POOL // 2] * 2


def test_an_admin_appoints_only_while_it_has_seats(fastapi_client):
    boss, a, other = owner(), admin(), admin()
    assert fastapi_client.put(f"/api/v1/admin/roles/admins/{a}/quota", json={"quota": 2}, headers=_h(a)).status_code == 403
    assert fastapi_client.put(f"/api/v1/admin/roles/admins/{a}/quota", json={"quota": 2}, headers=_h(boss)).status_code == 200

    readers = [_user(UserRole.USER) for _ in range(3)]
    promote = lambda uid, who: fastapi_client.post(f"/api/v1/admin/promote/{uid}", json={"role": "secondary_admin"}, headers=_h(who))  # noqa: E731
    assert promote(readers[0], a).status_code == 200
    assert promote(readers[1], a).status_code == 200
    full = promote(readers[2], a)
    assert full.status_code == 403 and _reason(full) == "no_seats_left"

    # The owner's own appointments cost nobody a seat.
    assert promote(readers[2], boss).status_code == 200
    row = fastapi_client.get("/api/v1/admin/roles/admins", headers=_h(boss)).json()["admins"]
    mine = next(r for r in row if r["user_id"] == a)
    assert mine["quota"] == 2 and mine["used"] == 2 and mine["left"] == 0

    # Removing one gives the seat back; the owner can add seats.
    assert fastapi_client.post(f"/api/v1/admin/demote/{readers[0]}", headers=_h(a)).status_code == 200
    assert promote(readers[0], a).status_code == 200
    assert fastapi_client.put(f"/api/v1/admin/roles/admins/{a}/quota", json={"quota": 3}, headers=_h(boss)).status_code == 200
    # The other Admin's share is untouched by this one's spending.
    with SessionLocal() as session:
        assert admin_roles.seats_left(session, session.get(User, other)) == SUB_ADMIN_POOL - 3


def test_no_share_can_push_the_pool_over_fifty(fastapi_client):
    boss, a, b = owner(), admin(), admin()
    assert fastapi_client.put(f"/api/v1/admin/roles/admins/{a}/quota", json={"quota": 40}, headers=_h(boss)).status_code == 200
    over = fastapi_client.put(f"/api/v1/admin/roles/admins/{b}/quota", json={"quota": 20}, headers=_h(boss))
    assert over.status_code == 403 and _reason(over) == "pool_exceeded"
    assert fastapi_client.put(f"/api/v1/admin/roles/admins/{b}/quota", json={"quota": 10}, headers=_h(boss)).status_code == 200
    assert fastapi_client.put(f"/api/v1/admin/roles/admins/{b}/quota", json={"quota": 51}, headers=_h(boss)).status_code == 422


# --------------------------------------------------------------------------
# E-mail and sign-outs follow the chain of command
# --------------------------------------------------------------------------


def test_who_sees_whose_email(fastapi_client):
    boss, a, other, s, reader = owner(), admin(), admin(), sub(), _user(UserRole.USER)

    def reveal(viewer, target):
        return fastapi_client.get(f"/api/v1/admin/users/{target}/email", headers=_h(viewer)).status_code

    assert reveal(a, reader) == 200 and reveal(a, s) == 200
    assert reveal(a, other) == 403 and reveal(a, boss) == 403
    assert reveal(boss, a) == 200 and reveal(boss, reader) == 200
    assert reveal(s, reader) == 403  # a sub-admin never holds the power


def test_sign_outs_follow_the_chain_of_command(fastapi_client):
    boss, a, other, s = owner(), admin(), admin(), sub()
    post = lambda who, target: fastapi_client.post(f"/api/v1/admin/users/{target}/revoke-sessions", headers=_h(who)).status_code  # noqa: E731
    assert post(a, s) == 200
    assert post(a, other) == 403 and post(a, boss) == 403
    assert post(s, a) == 403
    assert post(boss, a) == 200


# --------------------------------------------------------------------------
# Succession lines
# --------------------------------------------------------------------------


def test_an_admin_keeps_a_line_of_two_sub_admins(fastapi_client):
    boss, a, other, s1, s2, s3 = owner(), admin(), admin(), sub(), sub(), sub()
    put = lambda who, target, ids: fastapi_client.put(f"/api/v1/admin/roles/admins/{target}/successors", json={"successor_ids": ids}, headers=_h(who))  # noqa: E731

    ok = put(a, a, [s1, s2])
    assert ok.status_code == 200
    line = next(r for r in ok.json()["admins"] if r["user_id"] == a)["line"]
    assert [p["user_id"] for p in line] == [s1, s2]
    assert put(a, a, [s1, s2, s3]).status_code == 422
    assert put(a, a, [s1, s1]).status_code == 422
    assert _reason(put(a, a, [other])) == "not_a_sub_admin"  # only sub-admins
    assert _reason(put(a, a, [a])) == "not_a_sub_admin"
    assert _reason(put(a, other, [s3])) == "not_your_line"
    assert put(a, a, [s2]).status_code == 200  # reorder / replace
    # Admins see only their own row; the owner sees all and can set any line.
    assert [r["user_id"] for r in fastapi_client.get("/api/v1/admin/roles/admins", headers=_h(a)).json()["admins"]] == [a]
    assert len(fastapi_client.get("/api/v1/admin/roles/admins", headers=_h(boss)).json()["admins"]) == 2
    assert put(boss, other, [s3]).status_code == 200
    # Sub-admins have no line, and a sub-admin can't set one.
    assert put(s1, a, [s3]).status_code == 403


def _idle_admin_with_line(*, enabled_days_ago: int = 120):
    """An Admin gone quiet for 90 days with a restriction, seats, an appointee and a line."""

    today = date.today()
    a = admin()
    first, second = sub(), sub(authenticator=False)  # the first in line is eligible; the second isn't
    appointee = sub()
    with SessionLocal() as session:
        row = session.get(User, a)
        row.admin_since = datetime.utcnow() - timedelta(days=300)
        row.sub_admin_quota = 7
        session.add(PermissionOverride(user_id=a, permission="view_full_audit", state="revoked"))
        session.query(User).filter_by(id=appointee).update({"appointed_by": a})
        session.add(AdminActivityDay(user_id=a, day=today - timedelta(days=90)))
        admin_roles.set_line(session, row, [first, second])
        session.commit()
    with SessionLocal() as session:
        admin_succession.set_config(session, enabled=True, inactive_days=60)
        get_or_create_system_settings(session).succession_enabled_at = datetime.utcnow() - timedelta(days=enabled_days_ago)
        session.commit()
    return a, first, second, appointee


def test_an_idle_admin_is_replaced_by_the_first_eligible_successor_who_inherits_the_seat():
    today = date.today()
    a, first, second, appointee = _idle_admin_with_line()
    bystander = admin()  # an active Admin is left alone
    with SessionLocal() as session:
        session.add(AdminActivityDay(user_id=bystander, day=today))
        session.commit()

        events = admin_succession.run(session, today)
        assert [(e["demoted"], e["promoted"]) for e in events] == [(a, first)]
        assert session.get(User, a).role == UserRole.USER
        new = session.get(User, first)
        assert new.role == UserRole.CO_ADMIN and new.sub_admin_quota == 7
        # The owner's restriction on the seat, and the people the old Admin appointed, move with it.
        assert {(o.permission, o.state) for o in session.query(PermissionOverride).filter_by(user_id=first)} == {("view_full_audit", "revoked")}
        assert session.get(User, appointee).appointed_by == first
        assert session.query(AdminSuccessor).filter_by(admin_id=a).count() == 0
        assert session.query(AdminAuditLog).filter_by(action="roles.succession").count() >= 1
        assert session.get(User, bystander).role == UserRole.CO_ADMIN
        # Running again changes nothing.
        assert admin_succession.run(session, today) == []


def test_a_successor_who_cannot_serve_is_skipped_and_an_empty_line_leaves_the_seat_open():
    today = date.today()
    a, first, second, _appointee = _idle_admin_with_line()
    with SessionLocal() as session:
        session.query(User).filter_by(id=first).update({"is_active": False})
        session.commit()
        # The first is suspended and the second has no authenticator: nobody can take it.
        events = admin_succession.run(session, today)
        assert events == [{"demoted": a, "reason": "idle", "idle_days": events[0]["idle_days"]}]
        assert session.get(User, a).role == UserRole.USER
        assert admin_roles.admins(session) == []


def test_switching_succession_on_never_demotes_at_once_and_off_means_off():
    today = date.today()
    a, first, _second, _ = _idle_admin_with_line(enabled_days_ago=0)  # just switched on: the idle clock starts now
    with SessionLocal() as session:
        assert admin_succession.run(session, today) == []
        assert session.get(User, a).role == UserRole.CO_ADMIN
        admin_succession.set_config(session, enabled=False, inactive_days=60)
        get_or_create_system_settings(session).succession_enabled_at = datetime.utcnow() - timedelta(days=200)
        session.commit()
        assert admin_succession.run(session, today) == []


def test_succession_settings_need_the_owners_code_and_admins_cannot_touch_them(fastapi_client):
    boss, a = owner(), admin()
    url = "/api/v1/admin/roles/succession"
    assert _reason(fastapi_client.put(url, json={"enabled": True, "inactive_days": 60}, headers=_h(boss))) == "code_required"
    assert fastapi_client.put(url, json={"enabled": True, "inactive_days": 3, "code": code(boss)}, headers=_h(boss)).status_code == 422
    ok = fastapi_client.put(url, json={"enabled": True, "inactive_days": 60, "code": code(boss)}, headers=_h(boss))
    assert ok.status_code == 200 and ok.json()["enabled"] is True and ok.json()["rules"]["max_admins"] == 2
    assert fastapi_client.get(url, headers=_h(a)).status_code == 403
    assert fastapi_client.put(url, json={"enabled": False, "inactive_days": 60, "code": code(a)}, headers=_h(a)).status_code == 403


def test_the_owner_hands_a_seat_over_at_once(fastapi_client):
    boss, a, other = owner(), admin(), admin()
    first, second, not_in_line = sub(), sub(), sub()
    with SessionLocal() as session:
        admin_roles.set_line(session, session.get(User, a), [first, second])
        session.add(PermissionOverride(user_id=a, permission="manage_backups", state="revoked"))
        session.commit()
    url = f"/api/v1/admin/roles/admins/{a}/hand-over"
    assert _reason(fastapi_client.post(url, json={}, headers=_h(boss))) == "code_required"
    assert fastapi_client.post(url, json={"code": code(other)}, headers=_h(other)).status_code == 403

    # No successor named: the first in the line. Restrictions come with the seat.
    done = fastapi_client.post(url, json={"code": code(boss)}, headers=_h(boss))
    assert done.status_code == 200, done.text
    with SessionLocal() as session:
        assert session.get(User, a).role == UserRole.USER
        assert session.get(User, first).role == UserRole.CO_ADMIN
        assert {(o.permission, o.state) for o in session.query(PermissionOverride).filter_by(user_id=first)} == {("manage_backups", "revoked")}

    # The owner can also name anyone eligible, even outside the line ("give a new person the role").
    again = fastapi_client.post(
        f"/api/v1/admin/roles/admins/{other}/hand-over", json={"successor_id": not_in_line, "code": code(boss)}, headers=_h(boss)
    )
    assert again.status_code == 200
    with SessionLocal() as session:
        assert session.get(User, not_in_line).role == UserRole.CO_ADMIN and session.get(User, other).role == UserRole.USER

    # An empty line and nobody named: nothing happens.
    third = admin()
    refused = fastapi_client.post(f"/api/v1/admin/roles/admins/{third}/hand-over", json={"code": code(boss)}, headers=_h(boss))
    assert refused.status_code == 403 and _reason(refused) == "no_eligible_successor"


def test_admin_pages_record_daily_activity(fastapi_client):
    s = sub()
    for _ in range(2):
        assert fastapi_client.get("/api/v1/admin/permissions/me", headers=_h(s)).status_code == 200
    with SessionLocal() as session:
        assert session.query(AdminActivityDay).filter_by(user_id=s).count() == 1
        reader = _user(UserRole.USER)
        admin_succession.record_activity(session, session.get(User, reader))
        assert session.query(AdminActivityDay).filter_by(user_id=reader).count() == 0
