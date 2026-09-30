"""Regression tests for configurable main-admin auto-promotion (C5 / Blind Spot #12).

Verifies that the hardcoded admin hash is gone, that auto-promotion is disabled
by default, and that the path is audit-logged when it does fire.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from backend_fastapi.app.core import admin_identity
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.settings import settings
from backend_fastapi.app.models import (
    AdminAuditLog,
    AdminBootstrapState,
    AdminPromotionToken,
    User,
    UserRole,
)
from backend_fastapi.app.services import admin_bootstrap
from backend_fastapi.app.services.auth_service import ensure_magic_link_user
from backend_fastapi.app.utils.email_crypto import normalize_email
from _support.db_reset import clear_users

ADMIN_EMAIL = "root@example.com"


def _phc_hash_for(email: str) -> str:
    kdf = Argon2id(salt=os.urandom(16), length=32, iterations=1, lanes=1, memory_cost=8)
    return kdf.derive_phc_encoded(normalize_email(email).encode("utf-8"))


def _reset(session) -> None:
    # admin_audit_logs is append-only (F-3) -- rows from earlier tests are
    # never cleared, so assertions below compare counts against a baseline
    # taken right before the action under test, not an absolute 0.
    clear_users(session)


def test_hardcoded_admin_hash_removed_from_source():
    # The literal Argon2id hash must no longer live in source.
    assert not hasattr(admin_identity, "HARDCODED_ADMIN_EMAIL_ARGON2ID_HASH")
    source_path = admin_identity.__file__
    with open(source_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    assert "$argon2id$" not in source


def test_no_auto_promote_when_hash_unset(fastapi_app, monkeypatch):
    monkeypatch.setattr(settings, "main_admin_email_hash", None, raising=False)
    monkeypatch.setattr(
        settings, "main_admin_auto_promote_enabled", True, raising=False
    )

    session = SessionLocal()
    try:
        _reset(session)
        baseline = session.query(AdminAuditLog).count()
        user = ensure_magic_link_user(session, ADMIN_EMAIL)
        session.refresh(user)
        assert user.role == UserRole.USER
        assert bool(getattr(user, "is_main_admin", False)) is False
        assert session.query(AdminAuditLog).count() == baseline
    finally:
        session.close()


def test_no_auto_promote_when_flag_disabled(fastapi_app, monkeypatch):
    monkeypatch.setattr(
        settings, "main_admin_email_hash", _phc_hash_for(ADMIN_EMAIL), raising=False
    )
    monkeypatch.setattr(
        settings, "main_admin_auto_promote_enabled", False, raising=False
    )

    session = SessionLocal()
    try:
        _reset(session)
        baseline = session.query(AdminAuditLog).count()
        user = ensure_magic_link_user(session, ADMIN_EMAIL)
        session.refresh(user)
        assert user.role == UserRole.USER
        assert bool(getattr(user, "is_main_admin", False)) is False
        assert session.query(AdminAuditLog).count() == baseline
    finally:
        session.close()


def test_auto_promote_when_configured_and_enabled(fastapi_app, monkeypatch):
    monkeypatch.setattr(
        settings, "main_admin_email_hash", _phc_hash_for(ADMIN_EMAIL), raising=False
    )
    monkeypatch.setattr(
        settings, "main_admin_auto_promote_enabled", True, raising=False
    )

    session = SessionLocal()
    try:
        _reset(session)
        baseline = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.auto_promote")
            .count()
        )
        user = ensure_magic_link_user(session, ADMIN_EMAIL)
        session.refresh(user)
        assert user.role == UserRole.PERMANENT
        assert bool(user.permanent) is True
        assert bool(user.is_main_admin) is True
        assert bool(user.is_secondary_admin) is True

        # A non-matching email must not be promoted even while enabled.
        other = ensure_magic_link_user(session, "someone-else@example.com")
        session.refresh(other)
        assert other.role == UserRole.USER

        # The promotion must be recorded in the audit log -- exactly one new
        # entry beyond whatever earlier tests already left behind
        # (admin_audit_logs is append-only, F-3, so old rows are never
        # cleared between tests).
        entries = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == "admin.auto_promote")
            .all()
        )
        assert len(entries) == baseline + 1
        newest = max(entries, key=lambda e: e.id)
        assert newest.user_id == user.id
    finally:
        session.close()


def test_auto_promote_matches_bootstrap_token_role(fastapi_app, monkeypatch):
    """Admin tier consolidation: the config-gated auto-promote path
    (``_apply_main_admin_role``) and the one-time bootstrap-token path
    (``admin_bootstrap.redeem_admin_token``) are two doors onto the same
    single-owner tier -- they must land on identical role/permanent state."""

    monkeypatch.setenv("ADMIN_PROMOTION_SECRET", "consolidation-key")
    monkeypatch.setattr(
        settings, "main_admin_email_hash", _phc_hash_for(ADMIN_EMAIL), raising=False
    )
    monkeypatch.setattr(
        settings, "main_admin_auto_promote_enabled", True, raising=False
    )

    session = SessionLocal()
    try:
        _reset(session)
        # Isolate from any earlier test's bootstrap state so issue_admin_token
        # below doesn't see admin_initialized already set.
        session.query(AdminBootstrapState).delete()
        session.query(AdminPromotionToken).delete()
        session.commit()

        auto_promoted = ensure_magic_link_user(session, ADMIN_EMAIL)
        session.refresh(auto_promoted)

        bootstrapped = User(
            email="bootstrapped@example.com",
            username="bootstrapped",
            provider="magic_link",
        )
        session.add(bootstrapped)
        session.commit()
        session.refresh(bootstrapped)

        token_value = admin_bootstrap.issue_admin_token(session=session)
        session.commit()
        admin_bootstrap.redeem_admin_token(
            bootstrapped, token_value, session=session
        )
        session.refresh(bootstrapped)

        assert auto_promoted.role == bootstrapped.role == UserRole.PERMANENT
        assert bool(auto_promoted.permanent) is True
        assert bool(bootstrapped.permanent) is True
        assert bool(auto_promoted.is_main_admin) is True
        assert bool(bootstrapped.is_main_admin) is True
        assert bool(auto_promoted.is_secondary_admin) is True
        assert bool(bootstrapped.is_secondary_admin) is True
    finally:
        # Other suites (e.g. test_admin_scraper.py::test_admin_token_listing)
        # assume an empty admin_promotion_tokens table; don't leak this
        # test's bootstrap state/token rows into later tests.
        session.query(AdminBootstrapState).delete()
        session.query(AdminPromotionToken).delete()
        session.commit()
        session.close()
