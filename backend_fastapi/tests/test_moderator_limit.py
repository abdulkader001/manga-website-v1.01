"""Moderator role + the 10-moderator limit (SRS 1F.3.3 / Req 6)."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False, limit=None) -> int:
    u = User(
        email=f"u-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="U",
        role=role,
        is_main_admin=main,
        is_secondary_admin=secondary,
        moderator_limit=limit,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _headers(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def _make_plain_users(session, n: int) -> list[int]:
    ids = []
    for _ in range(n):
        ids.append(_user(session, UserRole.USER))
    return ids


def test_secondary_admin_capped_at_10(fastapi_client):
    session = SessionLocal()
    try:
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
        candidates = _make_plain_users(session, 11)
    finally:
        session.close()

    headers = _headers(sec_id)
    # First 10 promotions succeed.
    for uid in candidates[:10]:
        resp = fastapi_client.post(
            "/api/admin/roles/moderators", headers=headers, json={"user_id": uid}
        )
        assert resp.status_code == 200, resp.text

    # The eleventh is rejected with MODERATOR_LIMIT_REACHED.
    resp = fastapi_client.post(
        "/api/admin/roles/moderators", headers=headers, json={"user_id": candidates[10]}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "MODERATOR_LIMIT_REACHED"


def test_demote_frees_a_slot(fastapi_client):
    session = SessionLocal()
    try:
        sec_id = _user(session, UserRole.SECONDARY, secondary=True, limit=1)
        a, b = _make_plain_users(session, 2)
    finally:
        session.close()

    headers = _headers(sec_id)
    assert (
        fastapi_client.post(
            "/api/admin/roles/moderators", headers=headers, json={"user_id": a}
        ).status_code
        == 200
    )
    # Limit is 1 -> second is rejected.
    assert (
        fastapi_client.post(
            "/api/admin/roles/moderators", headers=headers, json={"user_id": b}
        ).status_code
        == 422
    )
    # Free the slot, then it succeeds.
    assert (
        fastapi_client.delete(
            f"/api/admin/roles/moderators/{a}", headers=headers
        ).status_code
        == 200
    )
    assert (
        fastapi_client.post(
            "/api/admin/roles/moderators", headers=headers, json={"user_id": b}
        ).status_code
        == 200
    )


def test_permanent_admin_unlimited_and_can_demote_any(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
        sec_id = _user(session, UserRole.SECONDARY, secondary=True, limit=1)
        u1, u2, u3 = _make_plain_users(session, 3)
    finally:
        session.close()

    pa = _headers(pa_id)
    # PA promotes several moderators with no cap.
    for uid in (u1, u2, u3):
        assert (
            fastapi_client.post(
                "/api/admin/roles/moderators", headers=pa, json={"user_id": uid}
            ).status_code
            == 200
        )

    # A moderator assigned to the secondary admin...
    sec = _headers(sec_id)
    u4 = _make_plain_users(SessionLocal(), 1)[0]
    assert (
        fastapi_client.post(
            "/api/admin/roles/moderators", headers=sec, json={"user_id": u4}
        ).status_code
        == 200
    )
    # ...can be demoted by the Permanent Administrator (reaching past the sec).
    assert (
        fastapi_client.delete(
            f"/api/admin/roles/moderators/{u4}", headers=pa
        ).status_code
        == 200
    )


def test_per_person_limit_is_adjustable(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
    finally:
        session.close()

    # PA raises this secondary admin's cap to 12.
    resp = fastapi_client.put(
        f"/api/admin/users/{sec_id}/moderator-limit",
        headers=_headers(pa_id),
        json={"moderator_limit": 12},
    )
    assert resp.status_code == 200
    assert resp.json()["moderator_limit"] == 12
