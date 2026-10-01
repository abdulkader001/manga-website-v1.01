"""Secret vault: main-admin GUI for allow-listed .env settings."""

from __future__ import annotations

import json
import os
import uuid

import pytest

from backend_fastapi.app.api.routers import secret_vault as vault_router
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.core.settings import get_settings
from backend_fastapi.app.models import AdminAuditLog, User, UserRole, VaultSecret
from backend_fastapi.app.services import admin_second_factor as sf
from backend_fastapi.app.services import secret_vault as vault


@pytest.fixture(autouse=True)
def _clean_vault(monkeypatch, fastapi_app):
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("SMTP_HOST", "env-smtp.example.com")
    with SessionLocal() as session:
        session.query(VaultSecret).delete()
        session.commit()
    vault._reset_for_tests()
    yield
    with SessionLocal() as session:
        session.query(VaultSecret).delete()
        session.commit()
    vault._reset_for_tests()


def _user(role: UserRole, main: bool) -> tuple[int, dict[str, str]]:
    with SessionLocal() as session:
        user = User(
            email=f"vault-{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=role,
            is_main_admin=main,
            is_secondary_admin=role == UserRole.SECONDARY,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        uid = user.id
    return uid, {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def _code(uid: int, offset: int = 0) -> str:
    with SessionLocal() as session:
        secret = sf._stored_secret(session.get(User, uid))
    return sf._code_for_step(secret, sf._current_step() + offset)


def _cookie(resp, name: str) -> str:
    for header, value in resp.headers:
        if header.lower() == "set-cookie" and value.startswith(f"{name}="):
            return value.split("=", 1)[1].split(";", 1)[0]
    raise AssertionError(f"no {name} cookie was set")


def _enrolled_main_admin(client) -> tuple[int, dict[str, str]]:
    """Main admin with an authenticator enrolled; headers carry the step-up cookie."""

    uid, headers = _user(UserRole.ADMIN, main=True)
    client.post("/api/admin/2fa/setup", headers=headers)
    resp = client.post("/api/admin/2fa/enable", json={"code": _code(uid)}, headers=headers)
    assert resp.status_code == 200, resp.text
    step_up = _cookie(resp, sf.STEP_UP_COOKIE)
    return uid, {**headers, "Cookie": f"{sf.STEP_UP_COOKIE}={step_up}"}


def _unlock(client, uid: int, headers: dict[str, str]) -> dict[str, str]:
    # The enable call burned the current step, so use the next one.
    resp = client.post("/api/admin/vault/unlock", json={"code": _code(uid, 1)}, headers=headers)
    assert resp.status_code == 200, resp.text
    token = _cookie(resp, vault_router.UNLOCK_COOKIE)
    return {**headers, "Cookie": f"{headers['Cookie']}; {vault_router.UNLOCK_COOKIE}={token}"}


def test_bootstrap_keys_are_never_manageable():
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "SECRET_KEY",
        "JWT_SECRET_KEY",
        "INTEGRATIONS_SECRET",
        "MAIN_ADMIN_EMAIL_HASH",
        "ADMIN_2FA_REQUIRED",
        "EMAIL_ENCRYPTION_KEY",
        "EMAIL_HASH_SECRET",
    ):
        assert key not in vault.MANAGED_KEYS


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SMTP_PORT", "abc"),
        ("SMTP_PORT", "70000"),
        ("SMTP_USE_TLS", "maybe"),
        ("GOOGLE_OAUTH_REDIRECT_URI", "javascript:alert(1)"),
        ("EMAIL_FROM_ADDRESS", "not-an-email"),
        ("SMTP_HOST", "evil\nX-Injected: 1"),
        ("SMTP_HOST", "   "),
    ],
)
def test_invalid_values_are_rejected(key, value):
    with pytest.raises(vault.VaultError):
        vault.normalize_value(key, value)


def test_secondary_admin_is_refused(fastapi_client):
    _, headers = _user(UserRole.SECONDARY, main=False)
    assert fastapi_client.get("/api/admin/vault", headers=headers).status_code == 403


def test_main_admin_needs_an_authenticator(fastapi_client):
    _, headers = _user(UserRole.ADMIN, main=True)
    resp = fastapi_client.get("/api/admin/vault", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["reason"] == "enrolment_required"


def test_full_lifecycle(fastapi_client):
    uid, headers = _enrolled_main_admin(fastapi_client)

    listing = fastapi_client.get("/api/admin/vault", headers=headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["unlocked"] is False
    smtp_host = next(e for e in body["entries"] if e["key"] == "SMTP_HOST")
    assert smtp_host["source"] == "env"
    assert smtp_host["preview"] == "env-smtp.example.com"

    # Writes need the vault unlock on top of the step-up.
    locked = fastapi_client.put(
        "/api/admin/vault/SMTP_PASSWORD", json={"value": "hunter2-secret"}, headers=headers
    )
    assert locked.status_code == 403
    assert locked.json()["error"]["details"]["reason"] == "vault_locked"

    unlocked = _unlock(fastapi_client, uid, headers)

    resp = fastapi_client.put(
        "/api/admin/vault/SMTP_PASSWORD", json={"value": "hunter2-secret"}, headers=unlocked
    )
    assert resp.status_code == 200, resp.text
    entry = resp.json()["entry"]
    assert entry["source"] == "vault"
    assert "hunter2" not in entry["preview"] and entry["preview"].endswith("cret")

    # Live in this process for both os.getenv and settings readers.
    assert os.environ["SMTP_PASSWORD"] == "hunter2-secret"
    assert get_settings().smtp_password == "hunter2-secret"

    # Encrypted at rest.
    with SessionLocal() as session:
        stored = session.query(VaultSecret).filter_by(key="SMTP_PASSWORD").one()
        assert "hunter2" not in stored.value_encrypted

    # Typed settings are coerced, and the override wins over .env.
    resp = fastapi_client.put(
        "/api/admin/vault/SMTP_PORT", json={"value": "2525"}, headers=unlocked
    )
    assert resp.status_code == 200
    assert get_settings().smtp_port == 2525
    resp = fastapi_client.put(
        "/api/admin/vault/SMTP_HOST", json={"value": "vault-smtp.example.com"}, headers=unlocked
    )
    assert resp.status_code == 200
    assert os.environ["SMTP_HOST"] == "vault-smtp.example.com"

    reveal = fastapi_client.post("/api/admin/vault/SMTP_PASSWORD/reveal", headers=unlocked)
    assert reveal.status_code == 200
    assert reveal.json()["value"] == "hunter2-secret"

    # Removing falls back to what .env had at boot.
    resp = fastapi_client.delete("/api/admin/vault/SMTP_HOST", headers=unlocked)
    assert resp.status_code == 200
    assert resp.json()["entry"]["source"] == "env"
    assert os.environ["SMTP_HOST"] == "env-smtp.example.com"
    resp = fastapi_client.delete("/api/admin/vault/SMTP_PASSWORD", headers=unlocked)
    assert resp.status_code == 200
    assert "SMTP_PASSWORD" not in os.environ

    # Unknown / bootstrap keys are not reachable at all.
    assert (
        fastapi_client.put(
            "/api/admin/vault/DATABASE_URL", json={"value": "sqlite://"}, headers=unlocked
        ).status_code
        == 404
    )

    # The audit trail records actions but never a plaintext value.
    with SessionLocal() as session:
        rows = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action.like("VAULT_%"))
            .all()
        )
        actions = {row.action for row in rows}
        assert {"VAULT_UNLOCK", "VAULT_SET", "VAULT_REVEAL", "VAULT_REMOVE"} <= actions
        dumped = json.dumps([row.metadata_json for row in rows], default=str)
        assert "hunter2" not in dumped


def test_unlock_cookie_of_another_admin_is_refused(fastapi_client):
    uid_a, headers_a = _enrolled_main_admin(fastapi_client)
    _, headers_b = _enrolled_main_admin(fastapi_client)
    unlocked_a = _unlock(fastapi_client, uid_a, headers_a)
    stolen = unlocked_a["Cookie"].split("; ", 1)[1]
    forged = {**headers_b, "Cookie": f"{headers_b['Cookie']}; {stolen}"}
    resp = fastapi_client.put(
        "/api/admin/vault/SMTP_HOST", json={"value": "x.example.com"}, headers=forged
    )
    assert resp.status_code == 403


def test_other_process_picks_up_changes():
    """A worker that did not make the edit sees it on its next refresh."""

    with SessionLocal() as session:
        vault.store(session, "TENOR_API_KEY", "tenor-from-vault", actor_id=None)
    # Simulate a different process: forget everything that was applied.
    vault._reset_for_tests()
    assert os.environ.get("TENOR_API_KEY") != "tenor-from-vault"
    vault.refresh_if_stale()
    assert os.environ["TENOR_API_KEY"] == "tenor-from-vault"
