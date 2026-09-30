"""Tests for encrypted environment bootstrap helpers."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from structlog.testing import capture_logs

from backend_fastapi.app.utils import crypto_utils


def test_ensure_encrypted_env_loaded_from_file(tmp_path, monkeypatch):
    crypto_utils.reset_loader_state()

    key = Fernet.generate_key()
    plaintext = b"SECRET_TOKEN=swordfish\n"
    encrypted = Fernet(key).encrypt(plaintext)

    enc_path = tmp_path / ".env.enc"
    enc_path.write_bytes(encrypted)

    monkeypatch.setenv("ENCRYPTED_ENV_FILE", str(enc_path))
    monkeypatch.setenv("ENV_SECRETS_KEY", key.decode("utf-8"))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ALLOW_PLAINTEXT_SECRETS", raising=False)

    loaded = crypto_utils.ensure_encrypted_env_loaded(force=True)

    assert loaded is True
    assert os.getenv("SECRET_TOKEN") == "swordfish"

    crypto_utils.reset_loader_state()
    monkeypatch.delenv("SECRET_TOKEN", raising=False)


def test_ensure_encrypted_env_loaded_requires_encrypted_sources(monkeypatch):
    crypto_utils.reset_loader_state()

    monkeypatch.delenv("ENCRYPTED_ENV_FILE", raising=False)
    monkeypatch.delenv("ENCRYPTED_ENV_PAYLOAD", raising=False)
    monkeypatch.delenv("KMS_ENV_PAYLOAD", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("ALLOW_PLAINTEXT_SECRETS", raising=False)
    monkeypatch.setenv("FORCE_ENCRYPTED_SECRETS", "true")

    with pytest.raises(RuntimeError):
        crypto_utils.ensure_encrypted_env_loaded(force=True)


def test_plaintext_fallback_allowed(monkeypatch):
    crypto_utils.reset_loader_state()

    monkeypatch.delenv("ENCRYPTED_ENV_FILE", raising=False)
    monkeypatch.setenv("ALLOW_PLAINTEXT_SECRETS", "true")

    loaded = crypto_utils.ensure_encrypted_env_loaded(force=True)

    assert loaded is False


def test_missing_encrypted_env_logs_warning(monkeypatch):
    # Captured through structlog rather than caplog. This is a structlog
    # logger, and it only reaches caplog once configure_logging() has pointed
    # structlog at stdlib logging -- so the assertion passed in a full-suite
    # run (something earlier builds the app, configuring it as a side effect)
    # and failed under `pytest tests/test_crypto_utils.py`, making this the
    # one order-dependent module in the suite. caplog cannot be rescued by
    # calling configure_logging() here either: it does
    # `root_logger.handlers.clear()`, which evicts caplog's own handler.
    # structlog.testing.capture_logs swaps the processor chain instead, so it
    # works whatever the ambient configuration is.
    crypto_utils.reset_loader_state()

    monkeypatch.delenv("ENCRYPTED_ENV_FILE", raising=False)
    monkeypatch.delenv("ENCRYPTED_ENV_PAYLOAD", raising=False)
    monkeypatch.delenv("KMS_ENV_PAYLOAD", raising=False)
    monkeypatch.delenv("ALLOW_PLAINTEXT_SECRETS", raising=False)
    monkeypatch.delenv("FORCE_ENCRYPTED_SECRETS", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    with capture_logs() as events:
        loaded = crypto_utils.ensure_encrypted_env_loaded(force=True)

    assert loaded is False
    warnings = [e for e in events if e.get("log_level") == "warning"]
    assert any("Encrypted environment not provided" in e.get("event", "") for e in warnings), (
        f"expected a plaintext-fallback warning, got: {events}"
    )
