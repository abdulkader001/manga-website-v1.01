"""Fail-loud misconfiguration smoke tests (Phase 5 / item 30).

These fail CI (or would fail boot) when a dangerous misconfiguration is present:
- the email-encryption key is unset in a non-plaintext environment,
- the main-admin identity hash is still hardcoded in source,
- the main-admin auto-promote flag is enabled but its hash is missing, or
- Redis is required but unconfigured/unreachable.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from backend_fastapi.app.bootstrap import lifecycle
from backend_fastapi.app.core import settings as settings_module
from backend_fastapi.app.core.settings import Settings

# ---- email-encryption key must be configured (no silent plaintext PII) ----


def test_boot_fails_without_email_key_outside_plaintext(monkeypatch):
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: False)
    with pytest.raises(ValueError):
        Settings(
            secret_key="x" * 12, jwt_secret_key="y" * 12, email_encryption_key=None
        )


# ---- the main-admin hash must not be hardcoded in source ----


def test_no_hardcoded_argon2id_hash_in_core_source():
    core_dir = pathlib.Path(lifecycle.__file__).resolve().parent.parent / "core"
    offenders = []
    for path in core_dir.rglob("*.py"):
        if "$argon2id$" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    assert offenders == [], f"Hardcoded Argon2id hash found in: {offenders}"


# ---- the main-admin hash must not be missing while auto-promote is enabled ----


def test_boot_fails_when_auto_promote_enabled_but_hash_missing(monkeypatch):
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: True)
    with pytest.raises(ValueError, match="MAIN_ADMIN_EMAIL_HASH"):
        Settings(
            secret_key="x" * 12,
            jwt_secret_key="y" * 12,
            email_encryption_key=None,
            main_admin_auto_promote_enabled=True,
            main_admin_email_hash=None,
        )


def test_boot_ok_when_auto_promote_enabled_with_hash(monkeypatch):
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: True)
    # A configured hash + enabled flag is the legitimate bootstrap combination.
    s = Settings(
        secret_key="x" * 12,
        jwt_secret_key="y" * 12,
        email_encryption_key=None,
        main_admin_auto_promote_enabled=True,
        main_admin_email_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaA",
    )
    assert s.main_admin_auto_promote_enabled is True


def test_boot_ok_when_auto_promote_disabled_and_hash_missing(monkeypatch):
    monkeypatch.setattr(settings_module, "allow_plaintext_fallback", lambda: True)
    # The default posture: flag off, no hash — must not raise.
    s = Settings(
        secret_key="x" * 12,
        jwt_secret_key="y" * 12,
        email_encryption_key=None,
        main_admin_auto_promote_enabled=False,
        main_admin_email_hash=None,
    )
    assert s.main_admin_auto_promote_enabled is False


# ---- Redis must fail loud when required ----


def test_redis_required_but_unconfigured_raises(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "redis_required", True)

    class _App:
        state = type("S", (), {})()

    with pytest.raises(RuntimeError, match="REDIS_REQUIRED"):
        asyncio.run(lifecycle.initialize_redis(_App(), None))


def test_redis_required_but_unreachable_raises(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "redis_required", True)

    class _FailingClient:
        async def ping(self):
            raise ConnectionError("no redis")

        async def close(self):
            return None

    monkeypatch.setattr(
        lifecycle.Redis, "from_url", staticmethod(lambda url: _FailingClient())
    )

    class _App:
        state = type("S", (), {})()

    with pytest.raises(RuntimeError, match="unreachable"):
        asyncio.run(lifecycle.initialize_redis(_App(), "redis://localhost:6379/0"))


def test_redis_optional_still_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "redis_required", False)

    class _App:
        state = type("S", (), {})()

    # Not required + unconfigured -> returns None, no raise.
    assert asyncio.run(lifecycle.initialize_redis(_App(), None)) is None
