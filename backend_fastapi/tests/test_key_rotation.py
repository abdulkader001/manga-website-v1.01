"""Encryption key rotation (roadmap item 16)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services.integration_key_vault import IntegrationKeyVault
from backend_fastapi.app.utils import email_crypto
from backend_fastapi.scripts.rotate_encryption_key import rotate
from _support.db_reset import clear_users

OLD_KEY = Fernet.generate_key().decode()
NEW_KEY = Fernet.generate_key().decode()


@pytest.fixture()
def keys(monkeypatch):
    def use(value: str) -> None:
        monkeypatch.setenv("EMAIL_ENCRYPTION_KEY", value)
        monkeypatch.setenv("EMAIL_HASH_SECRET", "pinned-hash-secret")
        email_crypto.reset_email_crypto_state()

    yield use
    email_crypto.reset_email_crypto_state()


def test_new_key_first_still_reads_old_values(keys):
    keys(OLD_KEY)
    token = email_crypto.encrypt_email("a@example.com")
    keys(f"{NEW_KEY},{OLD_KEY}")
    assert email_crypto.decrypt_email(token) == "a@example.com"
    # New values are written with the first key only.
    fresh = email_crypto.encrypt_email("b@example.com")
    keys(NEW_KEY)
    assert email_crypto.decrypt_email(fresh) == "b@example.com"
    assert email_crypto.decrypt_email(token) is None


def test_lookup_hash_does_not_change_with_key_list(keys, monkeypatch):
    # Without a pinned secret the fallback is the oldest key, so putting a new
    # key in front leaves lookup values alone.
    monkeypatch.delenv("EMAIL_HASH_SECRET", raising=False)
    monkeypatch.setenv("EMAIL_ENCRYPTION_KEY", OLD_KEY)
    email_crypto.reset_email_crypto_state()
    before = email_crypto.email_lookup("a@example.com")
    monkeypatch.setenv("EMAIL_ENCRYPTION_KEY", f"{NEW_KEY},{OLD_KEY}")
    email_crypto.reset_email_crypto_state()
    assert email_crypto.email_lookup("a@example.com") == before


def test_vault_reads_previous_secret_and_reencrypts():
    old = IntegrationKeyVault.from_secret("old-secret")
    token = old.encrypt("sk-live-123")
    rotating = IntegrationKeyVault.from_secret("new-secret", ["old-secret"])
    assert rotating.decrypt(token) == "sk-live-123"
    moved = rotating.reencrypt(token)
    assert moved != token
    # After the rotation the old secret is no longer needed.
    assert IntegrationKeyVault.from_secret("new-secret").decrypt(moved) == "sk-live-123"
    assert IntegrationKeyVault.from_secret("new-secret").decrypt(token) is None


def test_rotate_script_reencrypts_rows(fastapi_app, keys, monkeypatch):
    monkeypatch.setenv("INTEGRATIONS_SECRET", "old-secret")
    keys(OLD_KEY)
    session = SessionLocal()
    try:
        clear_users(session)
        # Rows left by other tests were written under other keys.
        for table in (
            "system_state",
            "provider_credentials",
            "system_provider_instances",
            "user_api_keys",
            "ad_clicks",
            "login_tokens",
        ):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()
        user = User(email="rot@example.com", role=UserRole.USER, provider="magic")
        user.access_token = "oauth-access"
        session.add(user)
        session.commit()
        uid = user.id
        old_email = session.execute(
            text("SELECT email FROM users WHERE id=:i"), {"i": uid}
        ).scalar_one()
    finally:
        session.close()

    monkeypatch.setenv("INTEGRATIONS_SECRET", "new-secret")
    monkeypatch.setenv("INTEGRATIONS_SECRET_PREVIOUS", "old-secret")
    keys(f"{NEW_KEY},{OLD_KEY}")

    dry = rotate(dry_run=True)
    assert dry["rotated"] >= 2 and dry["unreadable"] == 0
    assert rotate()["unreadable"] == 0

    # Old key removed: everything must still decrypt with the new key alone.
    keys(NEW_KEY)
    session = SessionLocal()
    try:
        new_email = session.execute(
            text("SELECT email FROM users WHERE id=:i"), {"i": uid}
        ).scalar_one()
        assert new_email != old_email
        user = session.get(User, uid)
        assert email_crypto.decrypt_email(user.email_encrypted) == "rot@example.com"
        assert user.access_token == "oauth-access"
    finally:
        session.close()
