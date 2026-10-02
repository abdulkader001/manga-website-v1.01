"""Deputies: the owner hands site-owner powers to at most two sub-admins.

Owner's rules (2026-10-02): only the owner gives or takes site-owner powers,
with their authenticator code; at most two sub-admins hold them; a holder
needs an authenticator and a fresh code to use them; sub-admins can't pass
them on, can't change themselves, and can't change a deputy. Automatic
succession (owner only) demotes a deputy idle for too long and hands their
powers to the most active eligible sub-admin.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import AdminActivityDay, AdminAuditLog, PermissionOverride, User, UserRole
from backend_fastapi.app.services import admin_second_factor as tfa
from backend_fastapi.app.services import admin_succession, permissions_service


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _no_other_deputies():
    """Deputy seats are site-wide: start each test with none taken."""

    with SessionLocal() as session:
        ids = permissions_service.deputy_ids(session)
        if ids:
            session.query(PermissionOverride).filter(PermissionOverride.user_id.in_(ids)).delete(synchronize_session=False)
            session.commit()
    yield


def _user(role: UserRole, *, main=False, authenticator=False) -> int:
    with SessionLocal() as session:
        user = User(
            # A fresh, large id: SQLite reuses ids of users other tests
            # deleted, and the (append-only) audit log keeps their rows.
            id=random.randint(10**8, 2 * 10**9),
            email=f"dep-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name=f"{role.value}-{uuid.uuid4().hex[:4]}",
            role=role,
            is_main_admin=main,
            is_secondary_admin=role == UserRole.SECONDARY,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        if authenticator:
            tfa.start_enrolment(session, user)
            user.totp_enabled = True
            session.commit()
        return user.id


def code(uid: int) -> str:
    """A valid, unused authenticator code for ``uid`` right now."""

    with SessionLocal() as session:
        user = session.get(User, uid)
        user.totp_last_step = None
        session.commit()
        return tfa._code_for_step(tfa._stored_secret(user), tfa._current_step())


def _h(uid: int, *, step_up: bool = True) -> dict:
    """Signed-in headers; with the admin step-up (a code entered recently)
    unless ``step_up=False``."""
    headers = {"Authorization": f"Bearer {create_access_token(str(uid))}"}
    if step_up:
        with SessionLocal() as session:
            token = tfa.create_step_up_token(session.get(User, uid))
        headers["Cookie"] = f"{tfa.STEP_UP_COOKIE}={token}"
    return headers


def _grant(client, actor: int, target: int, keys, *, with_code=True, state="granted"):
    body = {"overrides": [{"permission": k, "state": state} for k in keys]}
    if with_code:
        body["code"] = code(actor)
    return client.put(f"/api/v1/admin/users/{target}/permissions", json=body, headers=_h(actor))


def _reason(response) -> str:
    return response.json()["error"]["details"]["reason"]


# --------------------------------------------------------------------------
# Granting
# --------------------------------------------------------------------------


def test_owner_gives_a_power_with_their_code_and_the_deputy_uses_it(fastapi_client):
    owner = _user(UserRole.ADMIN, main=True, authenticator=True)
    sub = _user(UserRole.SECONDARY, authenticator=True)

    assert _reason(_grant(fastapi_client, owner, sub, ["manage_backups"], with_code=False)) == "code_required"
    wrong = fastapi_client.put(
        f"/api/v1/admin/users/{sub}/permissions",
        json={"overrides": [{"permission": "manage_backups", "state": "granted"}], "code": "000000"},
        headers=_h(owner),
    )
    assert _reason(wrong) == "code_required"
    assert fastapi_client.get("/api/v1/admin/backups", headers=_h(sub, step_up=True)).status_code == 403

    ok = _grant(fastapi_client, owner, sub, ["manage_backups"])
    assert ok.status_code == 200, ok.text
    # Using it needs a fresh code (step-up), not just a sign-in.
    no_step_up = fastapi_client.get("/api/v1/admin/backups", headers=_h(sub, step_up=False))
    assert no_step_up.status_code == 403 and no_step_up.json()["error"]["code"] == "REVERIFICATION_REQUIRED"
    assert fastapi_client.get("/api/v1/admin/backups", headers=_h(sub, step_up=True)).status_code == 200
    me = fastapi_client.get("/api/v1/admin/permissions/me", headers=_h(sub)).json()
    assert me["is_deputy"] is True and me["owner_powers"] == ["manage_backups"]

    # The owner takes it back (no code needed to take).
    assert _grant(fastapi_client, owner, sub, ["manage_backups"], with_code=False, state="inherited").status_code == 200
    assert fastapi_client.get("/api/v1/admin/backups", headers=_h(sub, step_up=True)).status_code == 403


def test_holder_needs_an_authenticator(fastapi_client):
    owner = _user(UserRole.ADMIN, main=True, authenticator=True)
    sub = _user(UserRole.SECONDARY)
    assert _reason(_grant(fastapi_client, owner, sub, ["manage_geolock"])) == "authenticator_required"


def test_only_two_deputies(fastapi_client):
    owner = _user(UserRole.ADMIN, main=True, authenticator=True)
    first, second, third = (_user(UserRole.SECONDARY, authenticator=True) for _ in range(3))
    assert _grant(fastapi_client, owner, first, ["manage_admin_settings"]).status_code == 200
    assert _grant(fastapi_client, owner, second, ["manage_roles", "manage_admin_settings"]).status_code == 200
    third_try = _grant(fastapi_client, owner, third, ["manage_cache"])
    assert third_try.status_code == 403 and _reason(third_try) == "deputy_limit"
    # A deputy can receive more powers; that doesn't take a new seat.
    assert _grant(fastapi_client, owner, first, ["manage_cache"]).status_code == 200


def test_a_deputy_cannot_pass_owner_powers_on_or_touch_deputies_or_themselves(fastapi_client):
    owner = _user(UserRole.ADMIN, main=True, authenticator=True)
    deputy = _user(UserRole.SECONDARY, authenticator=True)
    other_deputy = _user(UserRole.SECONDARY, authenticator=True)
    regular = _user(UserRole.SECONDARY, authenticator=True)
    assert _grant(fastapi_client, owner, deputy, ["manage_roles", "manage_admin_settings"]).status_code == 200
    assert _grant(fastapi_client, owner, other_deputy, ["manage_backups"]).status_code == 200

    def as_deputy(target, keys, state="granted"):
        body = {"overrides": [{"permission": k, "state": state} for k in keys], "code": code(deputy)}
        return fastapi_client.put(f"/api/v1/admin/users/{target}/permissions", json=body, headers=_h(deputy, step_up=True))

    assert _reason(as_deputy(regular, ["manage_admin_settings"])) == "owner_only"
    assert _reason(as_deputy(regular, ["manage_roles"])) == "owner_only"
    assert _reason(as_deputy(deputy, ["edit_series"], "revoked")) == "self_change"
    assert _reason(as_deputy(other_deputy, ["edit_series"], "revoked")) == "deputy_protected"
    # Everyday powers they hold themselves: allowed, on a regular sub-admin.
    assert as_deputy(regular, ["handle_reports"]).status_code == 200
    # Not one they don't hold.
    assert _reason(as_deputy(regular, ["view_full_audit"])) == "not_yours_to_give"
    # Presets and resets on deputies or themselves: refused too.
    preset = fastapi_client.post(
        f"/api/v1/admin/users/{other_deputy}/permissions/apply-preset",
        json={"preset": "titular"},
        headers=_h(deputy, step_up=True),
    )
    assert _reason(preset) == "deputy_protected"
    reset = fastapi_client.post(f"/api/v1/admin/users/{deputy}/permissions/reset", headers=_h(deputy, step_up=True))
    assert _reason(reset) == "self_change"
    # Nobody but the owner: the owner's own powers are fixed.
    assert _reason(as_deputy(owner, ["edit_series"], "revoked")) == "permanent_admin_immutable"
    # Automatic succession settings are the owner's alone.
    assert fastapi_client.get("/api/v1/admin/roles/succession", headers=_h(deputy, step_up=True)).status_code == 403


def test_demoting_a_deputy_is_the_owners_call_and_strips_their_powers(fastapi_client):
    owner = _user(UserRole.ADMIN, main=True, authenticator=True)
    deputy = _user(UserRole.SECONDARY, authenticator=True)
    other = _user(UserRole.SECONDARY, authenticator=True)
    assert _grant(fastapi_client, owner, deputy, ["demote_secondary", "promote_secondary"]).status_code == 200
    assert _grant(fastapi_client, owner, other, ["manage_geolock"]).status_code == 200

    refused = fastapi_client.post(f"/api/v1/admin/demote/{other}", headers=_h(deputy, step_up=True))
    assert refused.status_code == 403
    assert fastapi_client.post(f"/api/v1/admin/demote/{deputy}", headers=_h(deputy, step_up=True)).status_code == 403

    assert fastapi_client.post(f"/api/v1/admin/demote/{other}", headers=_h(owner)).status_code == 200
    promoted = fastapi_client.post(f"/api/v1/admin/promote/{other}", json={"role": "secondary_admin"}, headers=_h(owner))
    assert promoted.status_code == 200
    with SessionLocal() as session:
        assert not permissions_service.is_deputy(session, session.get(User, other))  # powers didn't come back


def test_presets_leave_owner_powers_alone(fastapi_client):
    owner = _user(UserRole.ADMIN, main=True, authenticator=True)
    deputy = _user(UserRole.SECONDARY, authenticator=True)
    assert _grant(fastapi_client, owner, deputy, ["manage_backups"]).status_code == 200
    applied = fastapi_client.post(
        f"/api/v1/admin/users/{deputy}/permissions/apply-preset", json={"preset": "titular"}, headers=_h(owner)
    )
    assert applied.status_code == 200
    with SessionLocal() as session:
        assert permissions_service.has_permission(session, session.get(User, deputy), "manage_backups")


def test_dropping_the_authenticator_pauses_the_powers():
    deputy = _user(UserRole.SECONDARY, authenticator=True)
    with SessionLocal() as session:
        user = session.get(User, deputy)
        permissions_service.set_override(session, user, "manage_geolock", "granted", None, by_owner=True)
        session.commit()
        assert permissions_service.has_permission(session, user, "manage_geolock")
        tfa.disable(session, user)
        assert not permissions_service.has_permission(session, user, "manage_geolock")


# --------------------------------------------------------------------------
# Automatic succession
# --------------------------------------------------------------------------


def _activity(uid: int, days_ago: list[int], today: date, *, work=True):
    with SessionLocal() as session:
        for d in days_ago:
            day = today - timedelta(days=d)
            session.merge(AdminActivityDay(user_id=uid, day=day))
            if work:
                session.add(AdminAuditLog(user_id=uid, action="test.work", timestamp=datetime.combine(day, datetime.min.time())))
        session.commit()


def _succession(enabled: bool, days: int = 60, enabled_at: datetime | None = None):
    with SessionLocal() as session:
        admin_succession.set_config(session, enabled=enabled, inactive_days=days)
        if enabled_at is not None:
            from backend_fastapi.app.services.system_settings_service import get_or_create_system_settings

            get_or_create_system_settings(session).succession_enabled_at = enabled_at
            session.commit()


@pytest.fixture()
def succession_off():
    yield
    _succession(False)


def test_idle_deputy_is_replaced_by_the_most_active_eligible_sub_admin(succession_off):
    today = date.today()
    deputy = _user(UserRole.SECONDARY, authenticator=True)
    busy = _user(UserRole.SECONDARY, authenticator=True)
    keen_newcomer = _user(UserRole.SECONDARY, authenticator=True)
    no_phone = _user(UserRole.SECONDARY)
    with SessionLocal() as session:
        for key in ("manage_backups", "manage_roles"):
            permissions_service.set_override(session, session.get(User, deputy), key, "granted", None, by_owner=True)
        session.query(PermissionOverride).filter_by(user_id=deputy).update(
            {"updated_at": datetime.utcnow() - timedelta(days=200), "created_at": datetime.utcnow() - timedelta(days=200)}
        )
        session.commit()
    _activity(deputy, [90], today)
    _activity(busy, list(range(0, 60)), today)  # admin for 60 days, active every day
    _activity(keen_newcomer, list(range(0, 10)), today)  # too new
    _activity(no_phone, list(range(0, 60)), today)  # no authenticator
    _succession(True, 60, enabled_at=datetime.utcnow() - timedelta(days=120))

    with SessionLocal() as session:
        ranked = admin_succession.candidates(session, today)
        assert ranked[0]["user_id"] == busy and not ranked[0]["blocked_by"]
        blocked = {c["user_id"]: c["blocked_by"] for c in ranked}
        assert any("admin for" in r for r in blocked[keen_newcomer])
        assert "no authenticator" in blocked[no_phone]

        events = admin_succession.run(session, today)
        assert events and events[0]["demoted"] == deputy and events[0]["promoted"] == busy
        assert session.get(User, deputy).role == UserRole.USER
        assert permissions_service.deputy_ids(session) == {busy}
        assert permissions_service.has_permission(session, session.get(User, busy), "manage_backups")
        assert session.query(AdminAuditLog).filter_by(action="roles.succession").count() >= 1
        # Running again changes nothing.
        assert admin_succession.run(session, today) == []


def test_switching_succession_on_never_demotes_at_once(succession_off):
    today = date.today()
    deputy = _user(UserRole.SECONDARY, authenticator=True)
    with SessionLocal() as session:
        permissions_service.set_override(session, session.get(User, deputy), "manage_cache", "granted", None, by_owner=True)
        session.query(PermissionOverride).filter_by(user_id=deputy).update({"updated_at": datetime.utcnow() - timedelta(days=300)})
        session.commit()
    _succession(True, 60)  # just switched on: the idle clock starts now
    with SessionLocal() as session:
        assert admin_succession.run(session, today) == []
        assert permissions_service.is_deputy(session, session.get(User, deputy))


def test_off_means_off_and_no_successor_means_powers_return_to_the_owner(succession_off):
    today = date.today()
    deputy = _user(UserRole.SECONDARY, authenticator=True)
    with SessionLocal() as session:
        permissions_service.set_override(session, session.get(User, deputy), "manage_geolock", "granted", None, by_owner=True)
        session.query(PermissionOverride).filter_by(user_id=deputy).update({"updated_at": datetime.utcnow() - timedelta(days=300)})
        session.commit()
    _succession(False)
    with SessionLocal() as session:
        assert admin_succession.run(session, today) == []
    _succession(True, 60, enabled_at=datetime.utcnow() - timedelta(days=100))
    with SessionLocal() as session:
        # Remove every eligible candidate so nobody qualifies.
        session.query(AdminActivityDay).filter(AdminActivityDay.day >= today - timedelta(days=40)).delete()
        session.commit()
        events = admin_succession.run(session, today)
        assert events and events[0]["demoted"] == deputy and "promoted" not in events[0]
        assert permissions_service.deputy_ids(session) == set()


def test_succession_settings_need_the_owners_code(fastapi_client, succession_off):
    owner = _user(UserRole.ADMIN, main=True, authenticator=True)
    no_code = fastapi_client.put("/api/v1/admin/roles/succession", json={"enabled": True, "inactive_days": 60}, headers=_h(owner))
    assert _reason(no_code) == "code_required"
    too_short = fastapi_client.put(
        "/api/v1/admin/roles/succession", json={"enabled": True, "inactive_days": 3, "code": code(owner)}, headers=_h(owner)
    )
    assert too_short.status_code == 422
    ok = fastapi_client.put(
        "/api/v1/admin/roles/succession", json={"enabled": True, "inactive_days": 60, "code": code(owner)}, headers=_h(owner)
    )
    assert ok.status_code == 200 and ok.json()["enabled"] is True
    assert fastapi_client.get("/api/v1/admin/roles/succession", headers=_h(owner)).json()["rules"]["max_deputies"] == 2


def test_admin_pages_record_daily_activity(fastapi_client):
    sub = _user(UserRole.SECONDARY)
    for _ in range(2):
        assert fastapi_client.get("/api/v1/admin/permissions/me", headers=_h(sub)).status_code == 200
    with SessionLocal() as session:
        assert session.query(AdminActivityDay).filter_by(user_id=sub).count() == 1
        reader = _user(UserRole.USER)
        admin_succession.record_activity(session, session.get(User, reader))
        assert session.query(AdminActivityDay).filter_by(user_id=reader).count() == 0
