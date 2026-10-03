"""The owner claims their seat by signing in with Google (no password, no page)."""

from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.settings import settings
from backend_fastapi.app.models import AdminAuditLog, UserRole
from backend_fastapi.app.services import oauth_service
from backend_fastapi.app.services.auth_service import ensure_magic_link_user, get_user_by_email
from _support.db_reset import clear_users

OWNER = "owner@example.com"


def _phc(value: str) -> str:
    kdf = Argon2id(salt=os.urandom(16), length=32, iterations=1, lanes=1, memory_cost=8)
    return kdf.derive_phc_encoded(value.encode("utf-8"))


@pytest.fixture
def fresh_site(fastapi_app, monkeypatch):
    monkeypatch.setattr(settings, "main_admin_email_hash", _phc(OWNER), raising=False)
    with SessionLocal() as session:
        clear_users(session)
    yield


def _google(session, email, *, verified=True, sub=None):
    return oauth_service.ensure_google_user(
        session,
        {"email": email, "email_verified": verified, "sub": sub or f"sub-{email}", "name": "Someone"},
    )


def test_verified_google_sign_in_with_the_owner_email_claims_the_seat(fresh_site):
    with SessionLocal() as session:
        user = _google(session, "Owner@Example.com")
        assert user.role == UserRole.PERMANENT
        assert user.permanent and user.is_main_admin
        newest = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "OWNER_SEAT_CLAIMED")
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        assert newest is not None and newest.user_id == user.id


def test_an_unverified_google_address_never_claims_it(fresh_site):
    # Google sign-in with an unverified address is refused outright (security
    # checklist, 2026-10-03), so it can neither claim the seat nor an account.
    with SessionLocal() as session:
        with pytest.raises(oauth_service.OAuthUserError):
            _google(session, OWNER, verified=False)
        assert get_user_by_email(session, OWNER) is None


def test_other_addresses_stay_readers(fresh_site):
    with SessionLocal() as session:
        user = _google(session, "reader@example.com")
        assert user.role == UserRole.USER and not user.is_main_admin


def test_a_magic_link_with_the_owner_email_never_claims_it(fresh_site):
    with SessionLocal() as session:
        user = ensure_magic_link_user(session, OWNER)
        session.refresh(user)
        assert user.role == UserRole.USER and not user.is_main_admin


def test_google_after_a_magic_link_account_claims_it_on_the_same_account(fresh_site):
    # One inbox gives one account: the owner may have opened a magic link first.
    with SessionLocal() as session:
        earlier = ensure_magic_link_user(session, OWNER)
        session.refresh(earlier)
        earlier_id = earlier.id
        user = _google(session, OWNER)
        assert user.id == earlier_id and user.is_main_admin


def test_ownership_never_passes_to_another_account(fresh_site, monkeypatch):
    with SessionLocal() as session:
        first = _google(session, OWNER)
        assert first.is_main_admin
    # The hash in .env is later pointed at someone else: they stay a reader.
    monkeypatch.setattr(settings, "main_admin_email_hash", _phc("other@example.com"), raising=False)
    with SessionLocal() as session:
        second = _google(session, "other@example.com")
        assert second.role == UserRole.USER and not second.is_main_admin
        assert get_user_by_email(session, OWNER).is_main_admin


def test_signing_in_again_changes_nothing(fresh_site):
    def claims(session):
        return session.query(AdminAuditLog).filter(AdminAuditLog.action == "OWNER_SEAT_CLAIMED").count()

    with SessionLocal() as session:
        before = claims(session)
        first = _google(session, OWNER)
        again = _google(session, OWNER)
        assert again.id == first.id and again.is_main_admin
        assert claims(session) == before + 1


def test_without_an_owner_email_in_env_nobody_is_promoted(fastapi_app, monkeypatch):
    monkeypatch.setattr(settings, "main_admin_email_hash", None, raising=False)
    with SessionLocal() as session:
        clear_users(session)
        user = _google(session, OWNER)
        assert user.role == UserRole.USER and not user.is_main_admin


def test_closed_registration_does_not_lock_the_owner_out(fresh_site, monkeypatch):
    from backend_fastapi.app.services import site_content_service

    monkeypatch.setattr(site_content_service, "registration_open", lambda db: False)
    with SessionLocal() as session:
        with pytest.raises(oauth_service.OAuthUserError):
            _google(session, "reader@example.com")
        assert _google(session, OWNER).is_main_admin


def test_the_old_admin_login_page_is_gone(fastapi_client):
    assert fastapi_client.get("/api/v1/auth/admin/status").status_code == 404
    assert fastapi_client.post("/api/v1/auth/admin/login", json={}).status_code in {404, 405}


def test_magic_link_for_the_owner_email_is_an_ordinary_request(fresh_site, fastapi_client):
    resp = fastapi_client.post("/api/auth/request-magic-link", json={"email": OWNER})
    assert resp.status_code == 200, resp.text
    assert resp.json()["message"] == "magic_link_sent"
