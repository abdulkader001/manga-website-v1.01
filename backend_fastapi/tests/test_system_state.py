from __future__ import annotations

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import (
    AdminAuditLog,
    AdminBootstrapState,
    AdminPromotionToken,
    SystemState,
    User,
    UserRole,
)
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.services import admin_bootstrap


def _create_user(session: SessionLocal, *, email: str = "secret@example.com") -> User:
    user = User(
        email=email,
        is_active=True,
        name="Secret User",
        provider="magic_link",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _reset_state(session: SessionLocal) -> None:
    session.query(AdminBootstrapState).delete()
    session.query(SystemState).delete()
    session.query(AdminPromotionToken).delete()
    # admin_audit_logs is append-only (F-3): rows from earlier tests are
    # never cleared. Assertions below pick the most recent matching row by
    # id rather than assuming the table starts empty.
    session.commit()


def _issue_token(session: SessionLocal, *, ttl_seconds: int | None = None) -> str:
    token_value = admin_bootstrap.issue_admin_token(
        ttl_seconds=ttl_seconds, session=session
    )
    session.commit()
    return token_value


def test_admin_token_endpoint_promotes_user(fastapi_client, monkeypatch):
    monkeypatch.setenv("ADMIN_PROMOTION_SECRET", "galaxy-key")

    session = SessionLocal()
    try:
        _reset_state(session)
        user = _create_user(session)
        token_value = _issue_token(session)
    finally:
        session.close()

    token = create_access_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    response = fastapi_client.post(
        "/api/system/admin-token/redeem",
        json={"token": token_value},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["system_state"]["secret_phrase_used"] is True

    session = SessionLocal()
    try:
        db_user = session.get(User, user.id)
        assert db_user is not None
        assert db_user.is_main_admin is True
        assert db_user.is_secondary_admin is True
        assert db_user.role in {UserRole.ADMIN, UserRole.PERMANENT}
        state = session.query(SystemState).first()
        assert state is not None
        audit_entry = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin_token.redeem")
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert audit_entry is not None
        assert audit_entry.user_id == db_user.id
        token_row = session.query(AdminPromotionToken).first()
        assert token_row is not None
        assert token_row.redeemed_by_user_id == db_user.id
    finally:
        session.close()


def test_admin_token_endpoint_rejects_after_consumption(fastapi_client, monkeypatch):
    monkeypatch.setenv("ADMIN_PROMOTION_SECRET", "reuse-lock")

    session = SessionLocal()
    try:
        _reset_state(session)
        user = _create_user(session, email="reuse@example.com")
        token_value = _issue_token(session)
    finally:
        session.close()

    token = create_access_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    first = fastapi_client.post(
        "/api/system/admin-token/redeem",
        json={"token": token_value},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["success"] is True

    second = fastapi_client.post(
        "/api/system/admin-token/redeem",
        json={"token": token_value},
        headers=headers,
    )
    assert second.status_code == 200
    payload = second.json()
    assert payload["success"] is False
    assert "already" in payload["message"].lower()

    session = SessionLocal()
    try:
        token_row = session.query(AdminPromotionToken).first()
        assert token_row is not None
        assert token_row.redeemed_by_user_id == user.id
        assert token_row.redeemed_at is not None
        state = session.query(SystemState).first()
        assert state is not None
        assert state.secret_phrase_used is True
    finally:
        session.close()


def test_issue_admin_token_rejected_once_bootstrap_initialized(monkeypatch):
    """#11: issue_admin_token must refuse to mint a new bootstrap token once
    the system already has a main admin (state.admin_initialized is True),
    instead of silently minting a live token nobody asked for."""
    monkeypatch.setenv("ADMIN_PROMOTION_SECRET", "already-initialized-key")

    session = SessionLocal()
    try:
        _reset_state(session)
        user = _create_user(session, email="already-bootstrapped@example.com")
        token_value = _issue_token(session)
    finally:
        session.close()

    session = SessionLocal()
    try:
        admin_bootstrap.redeem_admin_token(user, token_value, session=session)
    finally:
        session.close()

    session = SessionLocal()
    try:
        state = session.query(AdminBootstrapState).first()
        assert state is not None
        assert state.admin_initialized is True

        with pytest.raises(admin_bootstrap.AdminAlreadyInitialized):
            admin_bootstrap.issue_admin_token(session=session)

        # No new token was persisted by the refused call.
        assert session.query(AdminPromotionToken).count() == 1
    finally:
        session.close()


def test_system_state_and_health_endpoints(fastapi_client):
    session = SessionLocal()
    try:
        _reset_state(session)
        state = SystemState(
            secret_phrase_used=True, main_admin_email="root@example.com"
        )
        session.add(state)
        session.commit()
    finally:
        session.close()

    state_response = fastapi_client.get("/api/system/state")
    assert state_response.status_code == 200
    body = state_response.json()
    assert body["secret_phrase_used"] is True
    # H4: the public /system/state route must never leak decrypted PII.
    assert "main_admin_email" not in body
    assert body["admin_configured"] is True

    health_response = fastapi_client.get("/api/system/health")
    assert health_response.status_code == 200
    health = health_response.json()
    assert health["ok"] is True
    assert health["checks"]["database"] is True
    assert health["checks"]["secret_phrase_used"] is True
    # H4: the public /system/health route must never leak decrypted PII.
    assert "main_admin_email" not in health["checks"]
    assert health["checks"]["admin_configured"] is True
