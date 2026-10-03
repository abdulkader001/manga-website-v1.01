"""Visitors' IP addresses are for the owner only (a switch in Site Functions)."""

from __future__ import annotations

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import AdminAuditLog, User
from backend_fastapi.app.services import site_functions as functions
from _support import staff

IP = "203.0.113.77"
OPERATOR_MAIL = "owner.person@example.com"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean():
    staff.reset_staff()
    yield
    with SessionLocal() as session:
        functions.reset_all(session)
        functions.set_enabled(session, "sign_in_required", False, None)
    staff.reset_staff()


def _entry(owner_id: int) -> int:
    with SessionLocal() as session:
        row = AdminAuditLog(
            user_id=owner_id,
            operator=OPERATOR_MAIL,
            action="IP_PRIVACY_TEST",
            metadata_json={"target_type": "test"},
            source_ip=IP,
        )
        session.add(row)
        session.commit()
        return row.id


def _entries(client, who: int) -> list[dict]:
    resp = client.get("/api/v1/admin/audit/logs?limit=500", headers=staff.headers(who))
    assert resp.status_code == 200, resp.text
    return [e for e in resp.json() if e["action"] == "IP_PRIVACY_TEST"]


def test_only_the_owner_sees_the_address_and_the_operator_e_mail(fastapi_client):
    boss = staff.owner()
    _entry(boss)
    seen_by_owner = _entries(fastapi_client, boss)[-1]
    assert seen_by_owner["source_ip"] == IP
    assert seen_by_owner["operator"] == OPERATOR_MAIL

    seen_by_admin = _entries(fastapi_client, staff.admin())[-1]
    assert seen_by_admin["source_ip"] is None
    assert seen_by_admin["operator"] != OPERATOR_MAIL and "@" in seen_by_admin["operator"]
    assert OPERATOR_MAIL not in str(seen_by_admin)


def test_the_search_view_hides_it_too(fastapi_client):
    boss = staff.owner()
    _entry(boss)
    resp = fastapi_client.get(
        "/api/v1/admin/audit/logs/search?per_page=100&action=IP_PRIVACY_TEST",
        headers=staff.headers(staff.admin()),
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert items and all(i["source_ip"] is None for i in items)


def test_the_owner_can_open_it_up_in_site_functions(fastapi_client):
    boss = staff.owner()
    admin = staff.admin()
    _entry(boss)
    off = fastapi_client.put(
        "/api/v1/admin/site-functions/ip_owner_only", json={"enabled": False}, headers=staff.headers(boss)
    )
    assert off.status_code == 200
    assert _entries(fastapi_client, admin)[-1]["source_ip"] == IP
    fastapi_client.put(
        "/api/v1/admin/site-functions/ip_owner_only", json={"enabled": True}, headers=staff.headers(boss)
    )
    assert _entries(fastapi_client, admin)[-1]["source_ip"] is None


def test_new_entries_keep_no_address_while_recording_is_off(fastapi_client, monkeypatch):
    from backend_fastapi.app.utils import audit_logger

    monkeypatch.setattr(audit_logger, "resolve_client_ip", lambda request: IP)
    boss = staff.owner()

    def last_ip(action_target: str) -> str | None:
        with SessionLocal() as session:
            row = (
                session.query(AdminAuditLog)
                .filter(AdminAuditLog.action == "SITE_FUNCTION")
                .order_by(AdminAuditLog.id.desc())
                .first()
            )
            assert row is not None
            return row.source_ip

    fastapi_client.put(
        "/api/v1/admin/site-functions/comments", json={"enabled": False}, headers=staff.headers(boss)
    )
    assert last_ip("comments") == IP
    fastapi_client.put(
        "/api/v1/admin/site-functions/record_ips", json={"enabled": False}, headers=staff.headers(boss)
    )
    fastapi_client.put(
        "/api/v1/admin/site-functions/comments", json={"enabled": True}, headers=staff.headers(boss)
    )
    assert last_ip("comments") is None


def test_the_old_admin_token_list_is_for_the_owner_only(fastapi_client):
    assert fastapi_client.get("/api/v1/admin/admin-tokens", headers=staff.headers(staff.admin())).status_code == 403
    assert fastapi_client.get("/api/v1/admin/admin-tokens", headers=staff.headers(staff.sub_admin())).status_code == 403
    assert fastapi_client.get("/api/v1/admin/admin-tokens", headers=staff.headers(staff.owner())).status_code == 200


def test_both_switches_are_listed_under_privacy():
    from backend_fastapi.app.core import site_functions as registry

    for key in ("ip_owner_only", "record_ips"):
        assert registry.REGISTRY[key].group == registry.G_PRIVACY
        assert registry.REGISTRY[key].default is True


def test_an_unreadable_switch_hides_the_address(monkeypatch):
    from backend_fastapi.app.services import site_functions as sf

    def boom(db, key):
        raise RuntimeError("no table")

    monkeypatch.setattr(sf, "is_enabled", boom)
    with SessionLocal() as session:
        who = session.get(User, staff.admin())
        assert sf.ip_visible_to(session, who) is False
        assert sf.record_ips(session) is True
