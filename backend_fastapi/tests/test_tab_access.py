"""Role Management -> Tab access: the owner chooses which admin tabs a person sees.

Owner only (not delegable). A person without a tab loses the permissions bound
to it, so the tab is hidden and its API refuses them; permissions used outside
the panel (moderating comments from the reader) are not touched. The owner can
also switch **all** of a person's powers off while the person keeps the seat.
"""

from __future__ import annotations

import pytest

from backend_fastapi.app.core import admin_tabs
from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.permissions import ALL_PERMISSIONS, OWNER_POWERS, effective_role
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services import admin_roles, permissions_service
from _support import staff

URL = "/api/v1/admin/roles/tab-access"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean():
    staff.reset_staff()
    yield
    staff.reset_staff()


def _put(client, boss, target, **body):
    return client.put(f"{URL}/{target}", json=body, headers=staff.headers(boss))


def _has(uid: int, key: str) -> bool:
    with SessionLocal() as session:
        return permissions_service.has_permission(session, session.get(User, uid), key)


def _mine(client, uid: int) -> dict:
    resp = client.get("/api/v1/admin/permissions/me", headers=staff.headers(uid))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ------------------------------------------------------------------ owner only


def test_only_the_owner_can_see_or_set_tab_access(fastapi_client):
    admin = staff.admin()
    victim = staff.sub_admin()
    # Even an Admin who may manage roles has no way in: nobody can be given this.
    with SessionLocal() as session:
        permissions_service.set_override(session, session.get(User, admin), "manage_roles", "granted", None, by_owner=True)
        session.commit()
    for who in (admin, staff.sub_admin(), staff.reader()):
        h = staff.headers(who)
        assert fastapi_client.get(URL, headers=h).status_code == 403
        assert fastapi_client.put(f"{URL}/{victim}", json={"tabs": []}, headers=h).status_code == 403
    assert fastapi_client.get(URL, headers=staff.headers(staff.owner())).status_code == 200


def test_the_list_names_every_admin_and_sub_admin(fastapi_client):
    boss = staff.owner()
    a, s = staff.admin(), staff.sub_admin()
    body = fastapi_client.get(URL, headers=staff.headers(boss)).json()
    people = {p["user_id"]: p for p in body["people"]}
    assert people[a]["role"] == "admin" and people[s]["role"] == "sub_admin"
    assert people[a]["tabs"] is None and people[a]["suspended"] is False
    keys = {t["key"] for t in body["tabs"]}
    assert "functions" not in keys  # the owner's own tab can't be handed out
    assert {"series", "chapter-reports", "api-management", "vault"} <= keys


def test_refuses_the_owner_a_reader_and_unknown_tabs(fastapi_client):
    boss = staff.owner()
    other_owner = staff.owner()
    assert _put(fastapi_client, boss, other_owner, tabs=[]).status_code == 403
    assert _put(fastapi_client, boss, staff.reader(), tabs=[]).status_code == 403
    bad = _put(fastapi_client, boss, staff.sub_admin(), tabs=["series", "functions"])
    assert bad.status_code == 422 and "functions" in bad.json()["error"]["details"]["unknown"]
    assert _put(fastapi_client, boss, 999999999, tabs=[]).status_code == 404


# ----------------------------------------------------------- what a tab list does


def test_a_report_moderator_sees_reports_and_nothing_to_scrape_or_configure(fastapi_client):
    boss = staff.owner()
    mod = staff.sub_admin()
    assert _has(mod, "edit_series") and _has(mod, "handle_reports") and _has(mod, "view_system_health") is False
    assert _has(mod, "view_scraper_health")

    resp = _put(fastapi_client, boss, mod, tabs=["chapter-reports"])
    assert resp.status_code == 200, resp.text

    assert _has(mod, "handle_reports")
    for key in ("edit_series", "submit_manga_url", "view_user_list", "view_scraper_health", "manage_ads"):
        assert not _has(mod, key), key
    held = _mine(fastapi_client, mod)
    assert "handle_reports" in held["permissions"] and "edit_series" not in held["permissions"]
    assert held["tabs"] == ["chapter-reports"]


def test_the_api_refuses_a_hidden_tab_not_just_the_menu(fastapi_client):
    boss = staff.owner()
    mod = staff.sub_admin()
    _put(fastapi_client, boss, mod, tabs=["chapter-reports"])
    # Series import is the series tab's: refused for this person.
    resp = fastapi_client.post(
        "/api/v1/admin/series", json={"url": "https://example.com/x"}, headers=staff.headers(mod)
    )
    assert resp.status_code == 403, resp.text
    assert fastapi_client.get("/api/v1/admin/users", headers=staff.headers(mod)).status_code == 403


def test_permissions_used_outside_the_panel_are_not_touched(fastapi_client):
    boss = staff.owner()
    mod = staff.sub_admin()
    _put(fastapi_client, boss, mod, tabs=[])
    for key in ("remove_comments", "block_user", "timeout_user", "correct_translation", "rescrape_chapter"):
        assert admin_tabs.tabs_of(key) == ()
        assert _has(mod, key), key


def test_follow_permissions_again_restores_everything(fastapi_client):
    boss = staff.owner()
    mod = staff.sub_admin()
    _put(fastapi_client, boss, mod, tabs=[])
    assert not _has(mod, "edit_series")
    _put(fastapi_client, boss, mod, tabs=None)
    assert _has(mod, "edit_series")


def test_a_tab_never_gives_a_power_the_person_does_not_hold(fastapi_client):
    boss = staff.owner()
    mod = staff.sub_admin()
    _put(fastapi_client, boss, mod, tabs=["vault", "settings", "series"])
    with SessionLocal() as session:
        stored = session.get(User, mod).visible_admin_tabs
    assert stored == ["series"]  # a sub-admin can never hold the site-owner tabs
    assert not _has(mod, "manage_secret_vault")


def test_every_bound_permission_exists_and_only_shared_tabs_share_one():
    shared = {"view_system_health": {"health", "audit-report"}}
    for tab in admin_tabs.TABS.values():
        for key in tab.permissions:
            assert key in ALL_PERMISSIONS, f"{tab.key}: unknown permission {key}"
    for key in ALL_PERMISSIONS:
        owners = set(admin_tabs.tabs_of(key))
        assert len(owners) <= 1 or owners == shared.get(key), f"{key} is bound to {owners}"
    for tab in admin_tabs.TABS.values():
        if tab.owner_power:
            assert any(k in OWNER_POWERS for k in tab.permissions), tab.key


# ------------------------------------------------------- switch all powers off


def test_an_admin_with_powers_off_keeps_the_seat_and_holds_nothing(fastapi_client):
    boss = staff.owner()
    admin = staff.admin()
    with SessionLocal() as session:
        before = len(admin_roles.admins(session))
    assert _has(admin, "edit_series") and _has(admin, "manage_backups")

    resp = _put(fastapi_client, boss, admin, suspended=True)
    assert resp.status_code == 200, resp.text

    with SessionLocal() as session:
        person = session.get(User, admin)
        assert effective_role(person) == UserRole.CO_ADMIN  # still an Admin by name
        assert len(admin_roles.admins(session)) == before    # the seat stays filled
    assert not any(_has(admin, key) for key in ALL_PERMISSIONS)

    held = _mine(fastapi_client, admin)
    assert held["suspended"] is True and held["permissions"] == [] and held["role"] == "admin"
    for method, path in (("get", "/api/v1/admin/audit/logs"), ("get", "/api/v1/admin/roles/admins"), ("get", "/api/v1/admin/users")):
        r = getattr(fastapi_client, method)(path, headers=staff.headers(admin))
        assert r.status_code == 403, (path, r.text)

    again = _put(fastapi_client, boss, admin, suspended=False)
    assert again.status_code == 200 and _has(admin, "edit_series")


def test_powers_off_blocks_a_sub_admin_too(fastapi_client):
    boss = staff.owner()
    mod = staff.sub_admin()
    _put(fastapi_client, boss, mod, suspended=True)
    assert not _has(mod, "remove_comments")
    assert fastapi_client.get("/api/v1/admin/audit/logs", headers=staff.headers(mod)).status_code == 403


def test_the_owner_is_never_restricted(fastapi_client):
    boss = staff.owner()
    with SessionLocal() as session:
        row = session.get(User, boss)
        row.visible_admin_tabs = []
        row.powers_suspended = True
        session.commit()
    assert _has(boss, "edit_series") and _has(boss, "manage_secret_vault")
    assert fastapi_client.get("/api/v1/admin/audit/logs", headers=staff.headers(boss)).status_code == 200
    with SessionLocal() as session:
        row = session.get(User, boss)
        row.visible_admin_tabs = None
        row.powers_suspended = False
        session.commit()


# ------------------------------------------------------ seats and succession


def test_leaving_and_taking_a_seat_clears_or_passes_the_restrictions(fastapi_client):
    boss = staff.owner()
    old = staff.admin()
    heir = staff.sub_admin()
    _put(fastapi_client, boss, old, tabs=["chapter-reports"], suspended=False)
    with SessionLocal() as session:
        admin_roles.hand_over(session, session.get(User, boss), session.get(User, old), session.get(User, heir), reason="owner")
        session.commit()
        new_admin, former = session.get(User, heir), session.get(User, old)
        assert new_admin.visible_admin_tabs == ["chapter-reports"]  # the seat passes as it is
        assert former.visible_admin_tabs is None and former.powers_suspended is False


def test_promoting_a_sub_admin_starts_from_the_admin_defaults(fastapi_client):
    boss = staff.owner()
    mod = staff.sub_admin()
    _put(fastapi_client, boss, mod, tabs=["chapter-reports"], suspended=True)
    with SessionLocal() as session:
        admin_roles.promote_to_admin(session, session.get(User, boss), session.get(User, mod))
        session.commit()
        person = session.get(User, mod)
        assert person.visible_admin_tabs is None and person.powers_suspended is False


def test_every_change_is_audited(fastapi_client):
    from backend_fastapi.app.models import AdminAuditLog

    boss = staff.owner()
    mod = staff.sub_admin()
    _put(fastapi_client, boss, mod, tabs=["chapter-reports"])
    with SessionLocal() as session:
        row = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "ROLES_TAB_ACCESS")
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert row is not None and row.metadata_json["new_value"] == "chapter-reports"
