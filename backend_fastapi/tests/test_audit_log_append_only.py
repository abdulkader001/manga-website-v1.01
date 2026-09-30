"""F-3: admin_audit_logs must be genuinely append-only, not just documented
as such.

Prior to this fix, an ORM attribute update + commit, a bulk
``Query.filter(...).update(...)``, an ORM ``session.delete()``, and a bulk
``Query.filter(...).delete()`` all succeeded against a live row -- the
"append-only" docstring claim was aspirational. A database-level trigger
(registered in ``models/settings.py`` for ``Base.metadata.create_all()``, and
in migration ``20260827_admin_audit_logs_append_only`` for a real deployment)
now rejects all four, while still allowing the one legitimate mutation: the
``users.id`` foreign key's ``ON DELETE SET NULL``, which must keep clearing
``user_id`` on a deleted actor's audit rows rather than losing the trail.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import DatabaseError

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import AdminAuditLog, User


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _make_row(session) -> AdminAuditLog:
    row = AdminAuditLog(
        user_id=None,
        operator="operator@example.com",
        action="admin.promote",
        metadata_json={"target_id": 1},
        source_ip="127.0.0.1",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_orm_attribute_update_is_rejected():
    session = SessionLocal()
    try:
        row = _make_row(session)
        row.action = "tampered"
        with pytest.raises(DatabaseError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_bulk_update_is_rejected():
    session = SessionLocal()
    try:
        row = _make_row(session)
        with pytest.raises(DatabaseError):
            session.query(AdminAuditLog).filter(AdminAuditLog.id == row.id).update(
                {"action": "bulk-tampered"}
            )
        session.rollback()
    finally:
        session.close()


def test_orm_delete_is_rejected():
    session = SessionLocal()
    try:
        row = _make_row(session)
        session.delete(row)
        with pytest.raises(DatabaseError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_bulk_delete_is_rejected():
    session = SessionLocal()
    try:
        row = _make_row(session)
        with pytest.raises(DatabaseError):
            session.query(AdminAuditLog).filter(AdminAuditLog.id == row.id).delete()
        session.rollback()
    finally:
        session.close()


def test_deleting_the_actor_user_nulls_user_id_but_row_survives():
    session = SessionLocal()
    try:
        user = User(
            email=f"actor-{uuid.uuid4().hex}@example.com", username="actor"
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        row = AdminAuditLog(
            user_id=user.id,
            operator=user.email_plaintext,
            action="admin.promote",
            metadata_json=None,
            source_ip=None,
        )
        session.add(row)
        session.commit()
        row_id = row.id

        session.delete(user)
        session.commit()

        survivor = (
            session.query(AdminAuditLog).filter(AdminAuditLog.id == row_id).first()
        )
        assert survivor is not None
        assert survivor.user_id is None
        assert survivor.action == "admin.promote"
    finally:
        session.close()
