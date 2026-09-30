"""Regression tests for indexed login-by-email (C2 / item 11)."""

from __future__ import annotations

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services.auth_service import get_user_by_email
from backend_fastapi.app.utils.email_crypto import email_lookup, normalize_email
from backend_fastapi.scripts.backfill_email_lookup_hash import backfill
from _support.db_reset import clear_users


def _reset(session) -> None:
    clear_users(session)


def test_new_user_gets_deterministic_lookup_hash(fastapi_app):
    session = SessionLocal()
    try:
        _reset(session)
        user = User(email="Person@Example.com", role=UserRole.USER, provider="magic")
        session.add(user)
        session.commit()
        session.refresh(user)
        assert user.email_lookup_hash == email_lookup("person@example.com")
    finally:
        session.close()


def test_get_user_by_email_uses_lookup_hash(fastapi_app):
    session = SessionLocal()
    try:
        _reset(session)
        user = User(email="finder@example.com", role=UserRole.USER, provider="magic")
        session.add(user)
        session.commit()
        uid = user.id

        found = get_user_by_email(session, "FINDER@example.com")
        assert found is not None
        assert found.id == uid
    finally:
        session.close()


def test_get_user_by_email_fallback_self_heals(fastapi_app):
    """A row missing its lookup hash is still found and then repaired."""
    session = SessionLocal()
    try:
        _reset(session)
        user = User(email="legacy@example.com", role=UserRole.USER, provider="magic")
        session.add(user)
        session.commit()
        uid = user.id

        # Simulate a pre-backfill row.
        user.email_lookup_hash = None
        session.commit()

        found = get_user_by_email(session, "legacy@example.com")
        assert found is not None and found.id == uid
        session.commit()

        refreshed = session.get(User, uid)
        assert refreshed.email_lookup_hash == email_lookup("legacy@example.com")
    finally:
        session.close()


def test_unknown_email_returns_none(fastapi_app):
    session = SessionLocal()
    try:
        _reset(session)
        assert get_user_by_email(session, "nobody@example.com") is None
    finally:
        session.close()


def test_backfill_populates_null_rows(fastapi_app):
    session = SessionLocal()
    try:
        _reset(session)
        user = User(email="backfill@example.com", role=UserRole.USER, provider="magic")
        session.add(user)
        session.commit()
        uid = user.id
        user.email_lookup_hash = None
        session.commit()
    finally:
        session.close()

    updated = backfill(batch_size=100)
    assert updated >= 1

    session = SessionLocal()
    try:
        refreshed = session.get(User, uid)
        assert refreshed.email_lookup_hash == email_lookup(
            normalize_email("backfill@example.com")
        )
    finally:
        session.close()
