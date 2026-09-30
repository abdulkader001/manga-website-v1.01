"""Searchable, filterable, paginated audit log (SRS 1H.7.2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import AdminAuditLog, User, UserRole


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _admin(session) -> int:
    u = User(
        email=f"audit-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Audit",
        role=UserRole.ADMIN,
        is_main_admin=True,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _secondary_admin(session) -> int:
    u = User(
        email=f"secondary-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="Secondary",
        role=UserRole.SECONDARY,
        is_main_admin=False,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def test_search_filters_by_actor_action_target_outcome_and_paginates(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _admin(session)
        other_admin_id = _admin(session)

        marker = uuid.uuid4().hex[:8]
        session.add(
            AdminAuditLog(
                user_id=admin_id,
                action=f"TEST_ACTION_{marker}",
                metadata_json={
                    "target_type": "series",
                    "target_id": f"series-{marker}",
                    "result": "success",
                },
                operator="admin_router",
            )
        )
        session.add(
            AdminAuditLog(
                user_id=other_admin_id,
                action=f"TEST_ACTION_{marker}",
                metadata_json={
                    "target_type": "series",
                    "target_id": f"series-{marker}",
                    "result": "failed",
                },
                operator="admin_router",
            )
        )
        for i in range(3):
            session.add(
                AdminAuditLog(
                    user_id=admin_id,
                    action=f"OTHER_ACTION_{marker}_{i}",
                    metadata_json={"target_id": "unrelated"},
                    operator="admin_router",
                )
            )
        session.commit()
    finally:
        session.close()

    headers = _h(admin_id)

    by_actor = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=headers,
        params={"actor_id": admin_id, "action": marker},
    )
    assert by_actor.status_code == 200
    body = by_actor.json()
    assert body["total"] == 4  # admin_id's 1 TEST_ACTION + 3 OTHER_ACTION rows
    assert all(e["user_id"] == admin_id for e in body["items"])

    by_target = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=headers,
        params={"target_id": f"series-{marker}"},
    )
    assert by_target.status_code == 200
    target_body = by_target.json()
    assert target_body["total"] == 2
    assert {e["user_id"] for e in target_body["items"]} == {admin_id, other_admin_id}

    by_outcome = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=headers,
        params={"target_id": f"series-{marker}", "outcome": "failed"},
    )
    assert by_outcome.status_code == 200
    outcome_body = by_outcome.json()
    assert outcome_body["total"] == 1
    assert outcome_body["items"][0]["user_id"] == other_admin_id

    paged = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=headers,
        params={"action": marker, "per_page": 2, "page": 1},
    )
    paged_body = paged.json()
    assert paged_body["per_page"] == 2
    assert len(paged_body["items"]) == 2
    assert paged_body["pages"] == 3  # 5 rows total for this marker / 2 per page

    page2 = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=headers,
        params={"action": marker, "per_page": 2, "page": 2},
    )
    assert len(page2.json()["items"]) == 2
    # No overlap between pages.
    ids_p1 = {e["id"] for e in paged_body["items"]}
    ids_p2 = {e["id"] for e in page2.json()["items"]}
    assert ids_p1.isdisjoint(ids_p2)


def test_search_filters_by_date_range(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _admin(session)
        marker = uuid.uuid4().hex[:8]
        # F-3: admin_audit_logs is append-only -- a row's timestamp can no
        # longer be backdated after insert (that's exactly the kind of
        # tampering the trigger exists to block), so the old row is created
        # with its backdated timestamp already set, well outside any
        # "recent" window, instead of inserted-then-updated.
        old_row = AdminAuditLog(
            user_id=admin_id,
            action=f"OLD_{marker}",
            metadata_json={},
            operator="admin_router",
            timestamp=datetime.utcnow() - timedelta(days=400),
        )
        session.add(old_row)
        session.commit()
        session.add(
            AdminAuditLog(
                user_id=admin_id,
                action=f"RECENT_{marker}",
                metadata_json={},
                operator="admin_router",
            )
        )
        session.commit()
    finally:
        session.close()

    headers = _h(admin_id)
    recent_only = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=headers,
        params={
            "actor_id": admin_id,
            "date_from": (datetime.utcnow() - timedelta(days=1)).isoformat(),
        },
    )
    actions = {e["action"] for e in recent_only.json()["items"]}
    assert f"RECENT_{marker}" in actions
    assert f"OLD_{marker}" not in actions


def test_secondary_admin_gets_masked_email_main_admin_gets_plaintext(fastapi_client):
    """F-SSS-01: reveal_user_email (GET /admin/users/{id}/email) refuses
    Secondary Admins with require_main_admin_user -- the audit-log endpoints
    must not let the same Secondary Admin reach the same plaintext email
    through a different door. Only user_email_masked should be present for
    them; user_email_masked + the real user_email are both expected for a
    main admin.
    """
    session = SessionLocal()
    try:
        actor_id = _admin(session)
        actor_email = session.get(User, actor_id).email_plaintext
        secondary_id = _secondary_admin(session)
        main_id = _admin(session)

        marker = uuid.uuid4().hex[:8]
        session.add(
            AdminAuditLog(
                user_id=actor_id,
                action=f"LEAK_CHECK_{marker}",
                metadata_json={},
                operator="admin_router",
            )
        )
        session.commit()
    finally:
        session.close()

    as_secondary = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=_h(secondary_id),
        params={"action": marker},
    )
    assert as_secondary.status_code == 200
    secondary_items = as_secondary.json()["items"]
    assert len(secondary_items) == 1
    assert secondary_items[0]["user_email"] is None
    assert secondary_items[0]["user_email_masked"]

    as_main = fastapi_client.get(
        "/api/admin/audit/logs/search",
        headers=_h(main_id),
        params={"action": marker},
    )
    assert as_main.status_code == 200
    main_items = as_main.json()["items"]
    assert len(main_items) == 1
    assert main_items[0]["user_email"] == actor_email

    # The unfiltered /audit/logs list endpoint must behave the same way.
    unfiltered_secondary = fastapi_client.get(
        "/api/admin/audit/logs", headers=_h(secondary_id)
    )
    assert unfiltered_secondary.status_code == 200
    assert all(
        item["user_email"] is None for item in unfiltered_secondary.json()
    )
