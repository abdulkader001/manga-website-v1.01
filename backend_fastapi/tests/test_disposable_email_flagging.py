"""Disposable-email flag-for-review on existing accounts (SRS 1H.7.1 / D5).

New-account creation already refuses a disposable domain outright (tested in
test_disposable_email.py / test_email_verified.py). This covers the residual
case D5 resolves: the blocklist gains a domain after an account already
exists. The safe default is flag-for-review, not auto-ban — a login must
still succeed, and an administrator confirms before any account action.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import AdminAuditLog, User, UserRole
from backend_fastapi.app.services.auth_service import create_magic_login_token
from backend_fastapi.app.services.disposable_email import flag_if_disposable


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _admin(session) -> int:
    u = User(
        email=f"flagadmin-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="FlagAdmin",
        role=UserRole.ADMIN,
        is_main_admin=True,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def test_flag_if_disposable_flags_and_audits_without_banning():
    session = SessionLocal()
    try:
        user = User(
            email=f"legacy-{uuid.uuid4().hex}@mailinator.com",
            is_active=True,
            name="Legacy",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id

        flagged = flag_if_disposable(session, user)
        session.commit()
        assert flagged is True
    finally:
        session.close()

    session = SessionLocal()
    try:
        refreshed = session.get(User, user_id)
        assert refreshed.flagged_for_review is True
        assert refreshed.flag_reason == "disposable_email_domain"
        # Never an auto-ban.
        assert refreshed.is_active is True

        audit = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "DISPOSABLE_EMAIL_FLAGGED")
            .filter(AdminAuditLog.user_id == user_id)
            .first()
        )
        assert audit is not None
        assert audit.metadata_json["result"] == "flagged_for_review"
    finally:
        session.close()


def test_flag_if_disposable_noop_for_normal_domain():
    session = SessionLocal()
    try:
        user = User(
            email=f"normal-{uuid.uuid4().hex}@gmail.com",
            is_active=True,
            name="Normal",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        flagged = flag_if_disposable(session, user)
        assert flagged is False
        assert user.flagged_for_review is False
    finally:
        session.close()


def test_existing_account_login_still_succeeds_when_flagged(fastapi_client):
    """A magic-link click for an account whose domain became blocklisted
    after signup must still authenticate -- flagging, not lockout.

    (The request-magic-link endpoint itself refuses to issue a link for an
    already-blocklisted domain, so this simulates the residual case directly:
    the account and its token existed before the domain was blocklisted.)"""
    session = SessionLocal()
    try:
        user = User(
            email=f"click-{uuid.uuid4().hex}@mailinator.com",
            is_active=True,
            name="Clicker",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        _record, plaintext_token = create_magic_login_token(session, user)
        session.commit()
        user_id = user.id
    finally:
        session.close()

    resp = fastapi_client.get(
        "/api/auth/magic/verify", params={"token": plaintext_token}
    )
    assert resp.status_code == 200
    assert resp.json().get("access_token")

    session = SessionLocal()
    try:
        refreshed = session.get(User, user_id)
        assert refreshed.flagged_for_review is True
        assert refreshed.is_active is True  # login was never blocked
    finally:
        session.close()


def test_admin_review_endpoints(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _admin(session)
        user = User(
            email=f"review-{uuid.uuid4().hex}@mailinator.com",
            is_active=True,
            name="Review",
            role=UserRole.USER,
            provider="magic_link",
            flagged_for_review=True,
            flag_reason="disposable_email_domain",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id
    finally:
        session.close()

    listing = fastapi_client.get("/api/admin/users/flagged", headers=_h(admin_id))
    assert listing.status_code == 200
    ids = {u["id"] for u in listing.json()["users"]}
    assert user_id in ids

    cleared = fastapi_client.post(
        f"/api/admin/users/{user_id}/flag-review",
        headers=_h(admin_id),
        json={"decision": "clear"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["is_active"] is True

    session = SessionLocal()
    try:
        refreshed = session.get(User, user_id)
        assert refreshed.flagged_for_review is False
        assert refreshed.is_active is True
    finally:
        session.close()


def test_admin_can_confirm_ban(fastapi_client):
    session = SessionLocal()
    try:
        admin_id = _admin(session)
        user = User(
            email=f"ban-{uuid.uuid4().hex}@mailinator.com",
            is_active=True,
            name="BanMe",
            role=UserRole.USER,
            provider="magic_link",
            flagged_for_review=True,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id
    finally:
        session.close()

    banned = fastapi_client.post(
        f"/api/admin/users/{user_id}/flag-review",
        headers=_h(admin_id),
        json={"decision": "ban"},
    )
    assert banned.status_code == 200
    assert banned.json()["is_active"] is False
