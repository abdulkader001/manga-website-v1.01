"""1F.5 permission-matrix acceptance (SRS 1F.5.1).

Every row is verified by direct API call bypassing the UI, as each role.
"Allowed" means the permission gate passes — the request proceeds to business
logic (404/422/200), never 403. "Denied" means 403 from the permission engine.
"""

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


def _make(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"m-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="M",
        role=role,
        is_main_admin=main,
        is_secondary_admin=secondary,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


@pytest.fixture(scope="module")
def roles():
    session = SessionLocal()
    try:
        return {
            "main": _make(session, UserRole.ADMIN, main=True, secondary=True),
            "secondary": _make(session, UserRole.SECONDARY, secondary=True),
            "user": _make(session, UserRole.USER),
        }
    finally:
        session.close()


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


# (method, path, json, {role: allowed}) — nonexistent ids so allowed roles hit
# business outcomes (404/422), proving the gate passed without side effects.
MATRIX = [
    (
        "post",
        "/api/admin/series",
        {"url": "https://unapproved-matrix.example/m/1"},
        {"main": True, "secondary": True, "user": False},
    ),
    (
        "delete",
        "/api/admin/series/99999999",
        None,
        {"main": True, "secondary": True, "user": False},
    ),
    (
        "post",
        "/api/admin/series/99999999/rescrape",
        None,
        {"main": True, "secondary": True, "user": False},
    ),
    (
        "post",
        "/api/admin/chapters/99999999/rescrape",
        {},
        {"main": True, "secondary": True, "user": False},
    ),
    (
        "post",
        "/api/admin/approved-domains",
        {"url": "https://matrix-never.example"},
        {"main": True, "secondary": False, "user": False},
    ),
    (
        "delete",
        "/api/admin/approved-domains/99999999",
        None,
        {"main": True, "secondary": False, "user": False},
    ),
    (
        "put",
        "/api/admin/config/session",
        {"session_expiry_days": 14},
        {"main": True, "secondary": False, "user": False},
    ),
    (
        "post",
        "/api/admin/promote-secondary",
        {"user_id": 99999999},
        {"main": True, "secondary": False, "user": False},
    ),
    (
        "get",
        "/api/admin/users",
        None,
        {"main": True, "secondary": True, "user": False},
    ),
]


@pytest.mark.parametrize("method,path,body,expectations", MATRIX)
def test_matrix_row(fastapi_client, roles, method, path, body, expectations):
    for role, allowed in expectations.items():
        kwargs = {"headers": _h(roles[role])}
        if body is not None and method != "get":
            kwargs["json"] = body
        resp = getattr(fastapi_client, method)(path, **kwargs)
        if allowed:
            assert resp.status_code != 403, (
                f"{role} should pass the gate on {method.upper()} {path}, "
                f"got 403: {resp.text}"
            )
        else:
            assert resp.status_code == 403, (
                f"{role} should be denied on {method.upper()} {path}, "
                f"got {resp.status_code}: {resp.text}"
            )


def test_override_applies_to_wired_endpoint(fastapi_client, roles):
    """Revoking rescrape_chapter strips a sub-admin's matrix default (1F.6)."""
    revoke = fastapi_client.put(
        f"/api/admin/users/{roles['secondary']}/permissions",
        headers=_h(roles["main"]),
        json={"overrides": [{"permission": "rescrape_chapter", "state": "revoked"}]},
    )
    assert revoke.status_code == 200

    resp = fastapi_client.post(
        "/api/admin/chapters/99999999/rescrape",
        headers=_h(roles["secondary"]),
        json={},
    )
    assert resp.status_code == 403

    # Restore for other tests.
    reset = fastapi_client.post(
        f"/api/admin/users/{roles['secondary']}/permissions/reset",
        headers=_h(roles["main"]),
    )
    assert reset.status_code == 200
