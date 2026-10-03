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


def test_startup_preload_applies_only_allow_listed_keys(tmp_path):
    """The loader runs before any module reads its config; a planted
    non-allow-listed row (e.g. DATABASE_URL) must never reach the environment."""

    import sqlalchemy as sa

    from backend_fastapi.app import vault_preload
    from backend_fastapi.app.services.integration_key_vault import IntegrationKeyVault

    db_url = f"sqlite:///{tmp_path / 'vault.db'}"
    engine = sa.create_engine(db_url)
    cipher = IntegrationKeyVault.from_secret("preload-secret")
    other = IntegrationKeyVault.from_secret("some-other-secret")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE vault_secrets (key TEXT, value_encrypted TEXT)"))
        for key, token in (
            ("OCR_MODE", cipher.encrypt("local")),
            ("SMTP_PASSWORD", cipher.encrypt("pw-from-vault")),
            ("DATABASE_URL", cipher.encrypt("postgresql://attacker")),
            ("SMTP_HOST", other.encrypt("wrong-key.example")),
        ):
            conn.execute(sa.text("INSERT INTO vault_secrets VALUES (:k, :v)"), {"k": key, "v": token})
    engine.dispose()

    environ = {"INTEGRATIONS_SECRET": "preload-secret", "OCR_MODE": "remote", "DATABASE_URL": db_url}
    saved = (dict(vault_preload.ORIGINALS), dict(vault_preload.APPLIED))
    try:
        applied = vault_preload.preload(environ, env_file=tmp_path / "missing.env")
        assert applied == {"OCR_MODE": "local", "SMTP_PASSWORD": "pw-from-vault"}
        assert environ["OCR_MODE"] == "local"
        assert environ["DATABASE_URL"] == db_url  # never taken from the table
        assert "SMTP_HOST" not in environ  # undecryptable row skipped
        assert vault_preload.ORIGINALS["OCR_MODE"] == "remote"
    finally:
        vault_preload.ORIGINALS.clear()
        vault_preload.ORIGINALS.update(saved[0])
        vault_preload.APPLIED.clear()
        vault_preload.APPLIED.update(saved[1])


def test_startup_preload_without_table_is_a_no_op(tmp_path):
    from backend_fastapi.app import vault_preload

    environ = {"INTEGRATIONS_SECRET": "x", "DATABASE_URL": f"sqlite:///{tmp_path / 'empty.db'}"}
    assert vault_preload.preload(environ, env_file=tmp_path / "missing.env") == {}


def test_removing_a_startup_value_restores_env(monkeypatch):
    """A value the loader applied before Settings existed falls back to .env."""

    from backend_fastapi.app import vault_preload

    monkeypatch.setenv("SMTP_PORT", "2525")  # what the loader wrote
    vault_preload.ORIGINALS["SMTP_PORT"] = "587"  # what .env had
    vault_preload.APPLIED["SMTP_PORT"] = "2525"
    vault._boot_env["SMTP_PORT"] = "587"
    vault._applied["SMTP_PORT"] = "2525"

    with SessionLocal() as session:
        vault.refresh(session, force=True)  # table is empty -> drop the override
    assert os.environ["SMTP_PORT"] == "587"
    assert get_settings().smtp_port == 587


def test_large_numbers_are_accepted_where_ports_are_not():
    assert vault.normalize_value("RATE_LIMIT_MAX_BLOCK_SECONDS", "86400") == "86400"
    assert vault.normalize_value("SSRF_FETCH_MAX_BYTES", "20971520") == "20971520"
    with pytest.raises(vault.VaultError):
        vault.normalize_value("SMTP_PORT", "70000")
    with pytest.raises(vault.VaultError):
        vault.normalize_value("OCR_SERVICE_TESSERACT_CMD", "/bin/sh")  # never manageable


# --------------------------- website domain ---------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.COM", "example.com"),
        ("https://www.Example.com/some/path?x=1", "www.example.com"),
        ("http://user@new-site.net:8443/", "new-site.net"),
        ("  sub.domain.co.uk. ", "sub.domain.co.uk"),
    ],
)
def test_domain_is_normalised(raw, expected):
    assert vault.normalize_domain(raw) == expected


@pytest.mark.parametrize("bad", ["", "localhost", "192.168.1.5", "10.0.0.1", "single", "a b.com", "evil.local", "-x.com", "x..com"])
def test_bad_domains_are_refused(bad):
    with pytest.raises(vault.VaultError):
        vault.normalize_domain(bad)


def test_domain_derives_every_address():
    from backend_fastapi.app.vault_keys import derived_from_domain, with_domain

    derived = derived_from_domain("new-site.net")
    assert derived["FRONTEND_URL"] == "https://new-site.net"
    assert json.loads(derived["CORS_ALLOWED_ORIGINS"]) == ["https://new-site.net", "https://www.new-site.net"]
    assert derived["MAGIC_LINK_REDIRECT_URL"] == "https://new-site.net/"
    assert derived["GOOGLE_OAUTH_REDIRECT_URI"] == "https://new-site.net/api/auth/google/callback"
    # a value saved explicitly wins over the derived one
    merged = with_domain({"SITE_DOMAIN": "new-site.net", "FRONTEND_URL": "https://custom.example"})
    assert merged["FRONTEND_URL"] == "https://custom.example"
    assert merged["MAGIC_LINK_REDIRECT_URL"].startswith("https://new-site.net")


def test_changing_the_domain_moves_the_live_settings_and_back(fastapi_app, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://old-site.org")
    settings = get_settings()
    before = settings.frontend_url
    try:
        with SessionLocal() as db:
            vault.store(db, "SITE_DOMAIN", "https://New-Site.net/", actor_id=None)
        assert settings.frontend_url == "https://new-site.net"
        assert settings.cors_allowed_origins == ["https://new-site.net", "https://www.new-site.net"]
        assert settings.magic_link_redirect_url == "https://new-site.net/"
        assert os.environ["FRONTEND_URL"] == "https://new-site.net"

        with SessionLocal() as db:
            vault.remove(db, "SITE_DOMAIN")
        assert settings.frontend_url == before
        assert os.environ["FRONTEND_URL"] == "https://old-site.org"
    finally:
        vault._reset_for_tests()


def test_cors_follows_the_domain_without_a_restart(fastapi_app):
    """Production starts with a fixed origin list; after the vault changes the
    domain the new origin must be accepted at once and the old one dropped."""

    from starlette.applications import Starlette

    from backend_fastapi.app.bootstrap.middleware import LiveCORSMiddleware

    cors = LiveCORSMiddleware(
        Starlette(), allow_origins=["https://old-site.org"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    new = "https://moved-domain.example.net"
    assert cors.is_allowed_origin("https://old-site.org")
    assert not cors.is_allowed_origin(new)
    assert not cors.is_allowed_origin("https://evil.example")
    with SessionLocal() as db:
        vault.store(db, "SITE_DOMAIN", "moved-domain.example.net", actor_id=None)
    try:
        assert cors.is_allowed_origin(new)
        assert cors.is_allowed_origin("https://www.moved-domain.example.net")
        assert not cors.is_allowed_origin("https://evil.example")
    finally:
        vault._reset_for_tests()


def test_domain_check_endpoint_reports_dns_and_https(fastapi_client, monkeypatch):
    from backend_fastapi.app.api.routers import secret_vault as router_mod

    uid, headers = _enrolled_main_admin(fastapi_client)
    monkeypatch.setattr(
        router_mod,
        "_probe_domain",
        lambda domain: {"domain": domain, "resolves": True, "addresses": ["203.0.113.5"], "https": True, "is_this_site": True, "detail": "Ready"},
    )
    resp = fastapi_client.post("/api/admin/vault/domain/check", json={"domain": "https://Fresh-Domain.org/x"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["domain"] == "fresh-domain.org"
    bad = fastapi_client.post("/api/admin/vault/domain/check", json={"domain": "192.168.0.1"}, headers=headers)
    assert bad.status_code == 422

    status = fastapi_client.get("/api/admin/vault/domain", headers=headers)
    assert status.status_code == 200 and "derived" in status.json()


def test_set_domain_script_writes_the_vault(fastapi_app, capsys):
    from backend_fastapi.scripts import set_site_domain

    try:
        assert set_site_domain.main(["rescue-domain.org"]) == 0
        assert "https://rescue-domain.org" in capsys.readouterr().out
        with SessionLocal() as db:
            assert vault.current_value(db, "SITE_DOMAIN") == "rescue-domain.org"
        assert set_site_domain.main(["not a domain"]) == 2
        assert set_site_domain.main(["--clear"]) == 0
    finally:
        vault._reset_for_tests()
