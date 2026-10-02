"""F-70: only a Permanent/Main Administrator may grant or revoke admin tiers.

The regression these tests lock down is *model-wide*, not per-endpoint. Four
routes reach the same power:

* ``POST /admin/promote-secondary`` / ``/demote-secondary`` — gated on the
  ``promote_secondary`` / ``demote_secondary`` permissions (correct).
* ``POST /admin/promote/{id}`` / ``/demote/{id}`` and their ``*-by-email``
  siblings — gated only on ``require_admin_user``, i.e. "Secondary Admin or
  higher", which let a Secondary Administrator promote peers to Secondary
  Administrator and demote other administrators.

Every existing authz test passed while that hole was open, because each one
asserted a single endpoint's gate rather than the invariant across all of
them. These tests assert the invariant: by *any* route, a Secondary
Administrator is refused.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.utils.email_crypto import allow_email_decryption


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _make(session, role, *, main=False, secondary=False) -> int:
    user = User(
        email=f"esc-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Escalation fixture",
        role=role,
        is_main_admin=main,
        is_secondary_admin=secondary,
        provider="magic_link",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user.id


def _email(session, user_id: int) -> str:
    user = session.get(User, user_id)
    with allow_email_decryption():
        return user.email


def _headers(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


def _role_of(user_id: int):
    with SessionLocal() as session:
        session.expire_all()
        return session.get(User, user_id).role


@pytest.fixture()
def actors():
    with SessionLocal() as session:
        ids = {
            "main": _make(session, UserRole.ADMIN, main=True, secondary=True),
            "secondary": _make(session, UserRole.SECONDARY, secondary=True),
            "other_secondary": _make(session, UserRole.SECONDARY, secondary=True),
            "plain": _make(session, UserRole.USER),
        }
        ids["plain_email"] = _email(session, ids["plain"])
        ids["other_secondary_email"] = _email(session, ids["other_secondary"])
    return ids


def test_secondary_admin_cannot_promote_a_peer_by_id(fastapi_client, actors):
    resp = fastapi_client.post(
        f"/api/admin/promote/{actors['plain']}",
        json={"role": "secondary_admin"},
        headers=_headers(actors["secondary"]),
    )
    assert resp.status_code == 403, resp.text
    assert _role_of(actors["plain"]) == UserRole.USER


def test_secondary_admin_cannot_promote_a_peer_by_email(fastapi_client, actors):
    resp = fastapi_client.post(
        "/api/admin/promote-by-email",
        json={"email": actors["plain_email"], "role": "secondary_admin"},
        headers=_headers(actors["secondary"]),
    )
    assert resp.status_code == 403, resp.text
    assert _role_of(actors["plain"]) == UserRole.USER


def test_secondary_admin_cannot_demote_another_admin_by_id(fastapi_client, actors):
    resp = fastapi_client.post(
        f"/api/admin/demote/{actors['other_secondary']}",
        headers=_headers(actors["secondary"]),
    )
    assert resp.status_code == 403, resp.text
    assert _role_of(actors["other_secondary"]) == UserRole.SECONDARY


def test_secondary_admin_cannot_demote_another_admin_by_email(fastapi_client, actors):
    resp = fastapi_client.post(
        "/api/admin/demote-by-email",
        json={"email": actors["other_secondary_email"]},
        headers=_headers(actors["secondary"]),
    )
    assert resp.status_code == 403, resp.text
    assert _role_of(actors["other_secondary"]) == UserRole.SECONDARY


def test_secondary_admin_cannot_demote_a_peer_via_demote_secondary(
    fastapi_client, actors
):
    resp = fastapi_client.post(
        "/api/admin/demote-secondary",
        json={"user_id": actors["other_secondary"]},
        headers=_headers(actors["secondary"]),
    )
    assert resp.status_code == 403, resp.text
    assert _role_of(actors["other_secondary"]) == UserRole.SECONDARY


def test_main_admin_retains_both_promotion_routes(fastapi_client, actors):
    promote = fastapi_client.post(
        f"/api/admin/promote/{actors['plain']}",
        json={"role": "secondary_admin"},
        headers=_headers(actors["main"]),
    )
    assert promote.status_code == 200, promote.text
    assert _role_of(actors["plain"]) == UserRole.SECONDARY

    demote = fastapi_client.post(
        f"/api/admin/demote/{actors['plain']}",
        headers=_headers(actors["main"]),
    )
    assert demote.status_code == 200, demote.text
    assert _role_of(actors["plain"]) == UserRole.USER


def test_secondary_admin_cannot_change_any_role(fastapi_client, actors):
    """Role management is main-admin only (owner's rule): a sub-admin can't
    change even an ordinary user's role; the main admin can."""

    resp = fastapi_client.post(
        f"/api/admin/demote/{actors['plain']}",
        headers=_headers(actors["secondary"]),
    )
    assert resp.status_code == 403, resp.text


def test_main_admin_can_still_demote_an_ordinary_user(fastapi_client, actors):
    resp = fastapi_client.post(
        f"/api/admin/demote/{actors['plain']}",
        headers=_headers(actors["main"]),
    )
    assert resp.status_code == 200, resp.text
