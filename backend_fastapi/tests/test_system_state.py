"""Public system-state routes, and the retired admin-promotion paths."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from backend_fastapi.app.core import admin_identity
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.core.settings import settings
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services.auth_service import ensure_magic_link_user
from _support.db_reset import clear_users


def _phc(value: str) -> str:
    kdf = Argon2id(salt=os.urandom(16), length=32, iterations=1, lanes=1, memory_cost=8)
    return kdf.derive_phc_encoded(value.encode("utf-8"))


def test_no_admin_hash_hardcoded_in_source():
    with open(admin_identity.__file__, "r", encoding="utf-8") as handle:
        assert "$argon2id$" not in handle.read()


def test_signing_in_with_the_owner_email_never_promotes(fastapi_app, monkeypatch):
    # A magic link with the owner's e-mail never makes the owner: only a
    # verified Google sign-in does (tests/test_owner_google_sign_in.py). Old
    # .env files may still carry MAIN_ADMIN_AUTO_PROMOTE_ENABLED=true; it is
    # ignored.
    monkeypatch.setattr(settings, "main_admin_email_hash", _phc("root@example.com"), raising=False)
    monkeypatch.setenv("MAIN_ADMIN_AUTO_PROMOTE_ENABLED", "true")
    with SessionLocal() as session:
        clear_users(session)
        user = ensure_magic_link_user(session, "root@example.com")
        session.refresh(user)
        assert user.role == UserRole.USER
        assert not user.is_main_admin


def test_retired_promotion_endpoints_are_gone(fastapi_client):
    with SessionLocal() as session:
        user = User(email="someone@example.com", is_active=True, provider="magic_link")
        session.add(user)
        session.commit()
        uid = user.id
    headers = {"Authorization": f"Bearer {create_access_token(str(uid))}"}
    resp = fastapi_client.post("/api/system/admin-token/redeem", json={"token": "x"}, headers=headers)
    assert resp.status_code in {404, 405}
    assert fastapi_client.get("/api/system/bootstrap", headers=headers).status_code == 404


def test_state_and_health_on_a_fresh_install(fastapi_client):
    with SessionLocal() as session:
        clear_users(session)
    state = fastapi_client.get("/api/system/state")
    assert state.status_code == 200
    assert state.json() == {"admin_configured": False}
    health = fastapi_client.get("/api/system/health").json()
    # Healthy before the owner has signed in (the old secret-phrase flag kept
    # this false for ever on installs set up through Admin sign-in).
    assert health["ok"] is True
    assert health["checks"]["database"] is True
    assert health["checks"]["admin_configured"] is False


def test_state_and_health_after_the_owner_signed_in(fastapi_client):
    with SessionLocal() as session:
        clear_users(session)
        session.add(
            User(email="root@example.com", is_active=True, provider="magic_link", is_main_admin=True)
        )
        session.commit()
    body = fastapi_client.get("/api/system/state").json()
    assert body == {"admin_configured": True}  # never who the admin is
    health = fastapi_client.get("/api/system/health").json()
    assert health["ok"] is True and health["checks"]["admin_configured"] is True
    assert "main_admin_email" not in health["checks"]
