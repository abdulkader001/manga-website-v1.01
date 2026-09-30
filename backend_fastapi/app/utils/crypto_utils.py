"""Utilities for decrypting environment configuration secrets."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import structlog
import os
import threading
from pathlib import Path
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from dotenv import dotenv_values

logger = structlog.get_logger("backend_fastapi.crypto")

_LOCK = threading.Lock()
_INITIALISED = False
_LAST_RESULT = False


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def _scrub_bytearray(data: bytearray) -> None:
    for index in range(len(data)):
        data[index] = 0


def _mask_identifier(identifier: str) -> str:
    if not identifier:
        return "<empty>"
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:8]
    sample = identifier.strip()
    if len(sample) <= 6:
        masked = "*" * len(sample)
    else:
        masked = f"{sample[:3]}***{sample[-2:]}"
    return f"{masked} ({digest})"


def allow_plaintext_fallback() -> bool:
    if _truthy(os.getenv("FORCE_ENCRYPTED_SECRETS")):
        return False
    env = os.getenv("APP_ENV") or os.getenv("ENVIRONMENT")
    if _truthy(os.getenv("ALLOW_PLAINTEXT_SECRETS")):
        return True
    if env and env.strip().lower() in {
        "dev",
        "development",
        "local",
        "test",
        "testing",
    }:
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return False


def _load_env_from_bytes(data: bytearray, *, overwrite: bool) -> None:
    try:
        buffer = io.StringIO(data.decode("utf-8"))
    finally:
        _scrub_bytearray(data)

    try:
        parsed = dotenv_values(stream=buffer)
    finally:
        buffer.close()

    for key, value in parsed.items():
        if value is None:
            continue
        if not overwrite and key in os.environ:
            continue
        os.environ[key] = value


def _decrypt_payload(payload: bytes, *, key: str) -> bytearray:
    try:
        fernet = Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:  # pragma: no cover - defensive branch
        raise RuntimeError(
            "Invalid Fernet key provided for environment decryption"
        ) from exc

    try:
        decrypted = fernet.decrypt(payload)
    except InvalidToken as exc:
        raise RuntimeError(
            "Unable to decrypt environment payload: invalid token"
        ) from exc

    return bytearray(decrypted)


def ensure_encrypted_env_loaded(
    *,
    force: bool = False,
    overwrite: bool = True,
    kms_decrypter: Callable[[bytes], bytes] | None = None,
    log: logging.Logger | None = None,
) -> bool:
    global _INITIALISED, _LAST_RESULT

    target_logger = log or logger

    if not force and _INITIALISED:
        return _LAST_RESULT

    with _LOCK:
        if not force and _INITIALISED:
            return _LAST_RESULT

        encrypted_file = os.getenv("ENCRYPTED_ENV_FILE")
        key = os.getenv("ENV_SECRETS_KEY")
        payload_b64 = os.getenv("ENCRYPTED_ENV_PAYLOAD")
        kms_payload_b64 = os.getenv("KMS_ENV_PAYLOAD")
        force_encrypted = _truthy(os.getenv("FORCE_ENCRYPTED_SECRETS"))

        loaded = False

        try:
            if payload_b64:
                if not key:
                    raise RuntimeError(
                        "ENCRYPTED_ENV_PAYLOAD set but ENV_SECRETS_KEY missing; cannot decrypt"
                    )
                payload = base64.b64decode(payload_b64)
                decrypted = _decrypt_payload(payload, key=key)
                _load_env_from_bytes(decrypted, overwrite=overwrite)
                loaded = True
                target_logger.info(
                    "Encrypted environment variables loaded from payload %s",
                    _mask_identifier(payload_b64[:24]),
                )
            elif encrypted_file:
                path = Path(encrypted_file)
                if not path.exists():
                    raise RuntimeError(
                        f"Encrypted environment file not found at {path!s}"
                    )
                if not key:
                    raise RuntimeError(
                        "ENV_SECRETS_KEY missing; cannot decrypt encrypted environment file"
                    )
                encrypted_data = bytearray(path.read_bytes())
                try:
                    decrypted = _decrypt_payload(bytes(encrypted_data), key=key)
                finally:
                    _scrub_bytearray(encrypted_data)
                _load_env_from_bytes(decrypted, overwrite=overwrite)
                loaded = True
                target_logger.info(
                    "Encrypted environment variables loaded from file %s",
                    _mask_identifier(path.name),
                )
            elif kms_payload_b64:
                if kms_decrypter is None:
                    raise RuntimeError(
                        "KMS_ENV_PAYLOAD provided but no kms_decrypter callable supplied"
                    )
                encrypted = base64.b64decode(kms_payload_b64)
                decrypted_payload = kms_decrypter(encrypted)
                decrypted_bytes = bytearray(decrypted_payload)
                _load_env_from_bytes(decrypted_bytes, overwrite=overwrite)
                loaded = True
                target_logger.info(
                    "Encrypted environment variables loaded from KMS payload %s",
                    _mask_identifier(kms_payload_b64[:24]),
                )
            else:
                if force_encrypted:
                    raise RuntimeError(
                        "Encrypted environment required but no ENCRYPTED_ENV_FILE, "
                        "ENCRYPTED_ENV_PAYLOAD, or KMS_ENV_PAYLOAD provided"
                    )

                if allow_plaintext_fallback():
                    target_logger.info(
                        "Encrypted environment sources not configured; relying on plaintext dev configuration",
                    )
                else:
                    target_logger.warning(
                        "⚠️ Encrypted environment not provided; continuing startup with plaintext configuration."
                    )
        finally:
            _INITIALISED = True
            _LAST_RESULT = loaded

        return loaded


def reset_loader_state() -> None:
    global _INITIALISED, _LAST_RESULT
    with _LOCK:
        _INITIALISED = False
        _LAST_RESULT = False


__all__ = [
    "allow_plaintext_fallback",
    "ensure_encrypted_env_loaded",
    "reset_loader_state",
]
