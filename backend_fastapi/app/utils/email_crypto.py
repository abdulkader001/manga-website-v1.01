"""Helpers for encrypting and decrypting email addresses at rest."""

from __future__ import annotations

import hashlib
import hmac
import structlog
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .crypto_utils import allow_plaintext_fallback, ensure_encrypted_env_loaded

logger = structlog.get_logger("backend_fastapi.email_crypto")

_EMAIL_CIPHER: Fernet | None = None
_EMAIL_KEY_BYTES: bytes | None = None
_EMAIL_HASH_SECRET: bytes | None = None
_EMAIL_DECRYPT_ALLOWED: ContextVar[bool] = ContextVar(
    "email_decrypt_allowed", default=False
)

EMAIL_KEY_ENV = "EMAIL_ENCRYPTION_KEY"
EMAIL_HASH_SECRET_ENV = "EMAIL_HASH_SECRET"
ARGON2_MEMORY_COST = 65536
ARGON2_ITERATIONS = 3
ARGON2_LANES = 4
ARGON2_HASH_LENGTH = 32


class EmailCipherError(RuntimeError):
    """Raised when email encryption helpers cannot be initialised."""


def _load_email_cipher() -> Fernet | None:
    global _EMAIL_CIPHER, _EMAIL_KEY_BYTES

    if _EMAIL_CIPHER is not None:
        return _EMAIL_CIPHER

    ensure_encrypted_env_loaded()

    key = os.getenv(EMAIL_KEY_ENV)
    if not key:
        if allow_plaintext_fallback():
            logger.warning(
                "EMAIL_ENCRYPTION_KEY not configured; email addresses will be stored in plaintext"
            )
            _EMAIL_CIPHER = None
            return None
        message = "EMAIL_ENCRYPTION_KEY is required when plaintext fallback is disabled"
        logger.error(message)
        raise EmailCipherError(message)

    raw_key = key.encode("utf-8") if isinstance(key, str) else key

    try:
        _EMAIL_CIPHER = Fernet(raw_key)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive branch
        logger.error(
            "Invalid EMAIL_ENCRYPTION_KEY configured; expected 32 url-safe base64 encoded bytes"
        )
        raise EmailCipherError(
            "Invalid EMAIL_ENCRYPTION_KEY configured; expected 32 url-safe base64 encoded bytes"
        ) from exc

    _EMAIL_KEY_BYTES = raw_key
    return _EMAIL_CIPHER


def _load_hash_secret() -> bytes:
    global _EMAIL_HASH_SECRET

    if _EMAIL_HASH_SECRET is not None:
        return _EMAIL_HASH_SECRET

    ensure_encrypted_env_loaded()

    secret = os.getenv(EMAIL_HASH_SECRET_ENV)
    if secret:
        value = secret.encode("utf-8")
    else:
        _load_email_cipher()
        if _EMAIL_KEY_BYTES is None:
            # Fallback to deterministic but less secure hashing for development environments.
            value = b"development-email-hash"
        else:
            value = _EMAIL_KEY_BYTES

    _EMAIL_HASH_SECRET = value
    return value


def can_decrypt_emails() -> bool:
    """Return ``True`` when the current context is permitted to view plaintext emails."""

    return bool(_EMAIL_DECRYPT_ALLOWED.get())


@contextmanager
def allow_email_decryption() -> Iterator[None]:
    """Temporarily allow email decryption in the current context."""

    previous = _EMAIL_DECRYPT_ALLOWED.get()
    _EMAIL_DECRYPT_ALLOWED.set(True)
    try:
        yield
    finally:
        _EMAIL_DECRYPT_ALLOWED.set(previous)


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized or None


def encrypt_email(value: str | None) -> str | None:
    if value is None:
        return None

    cipher = _load_email_cipher()
    if cipher is None:
        return value

    token = cipher.encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_email(value: str | None) -> str | None:
    if value is None:
        return None

    cipher = _load_email_cipher()
    if cipher is None:
        return value

    try:
        decrypted = cipher.decrypt(value.encode("utf-8"))
    except InvalidToken:
        logger.warning(
            "Failed to decrypt email ciphertext; returning masked placeholder"
        )
        return None
    return decrypted.decode("utf-8")


def encrypt_secret(value: str | None) -> str | None:
    """Encrypt an arbitrary secret (e.g. OAuth token) with the Fernet key.

    Blind Spot #16: reuses the same symmetric cipher as email encryption so
    OAuth access/refresh tokens are never stored in plaintext at rest.
    """

    return encrypt_email(value)


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a value produced by :func:`encrypt_secret`.

    Tolerates already-plaintext values (returns them unchanged) so it is safe
    across the migration window before the backfill runs.
    """

    if value is None:
        return None

    cipher = _load_email_cipher()
    if cipher is None:
        return value

    try:
        decrypted = cipher.decrypt(value.encode("utf-8"))
    except InvalidToken:
        # Not (yet) encrypted — return as-is rather than dropping the value.
        return value
    return decrypted.decode("utf-8")


def render_email(ciphertext: str | None) -> str | None:
    """Return plaintext when authorised, otherwise ``None``."""

    if ciphertext is None:
        return None
    if not can_decrypt_emails():
        return None
    return decrypt_email(ciphertext)


def mask_email(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    local, _, domain = plaintext.partition("@")
    if not local:
        return "***"
    if len(local) <= 2:
        local_masked = local[0] + "*"
    else:
        local_masked = f"{local[0]}***{local[-1]}"
    return f"{local_masked}@{domain}" if domain else f"{local_masked}@"


def hash_email(value: str | None) -> str | None:
    normalized = normalize_email(value)
    if normalized is None:
        return None

    secret = _load_hash_secret()
    salt = hmac.new(secret, normalized.encode("utf-8"), hashlib.sha256).digest()[:16]
    kdf = Argon2id(
        salt=salt,
        length=ARGON2_HASH_LENGTH,
        iterations=ARGON2_ITERATIONS,
        lanes=ARGON2_LANES,
        memory_cost=ARGON2_MEMORY_COST,
    )
    return kdf.derive_phc_encoded(normalized.encode("utf-8"))


def email_lookup(value: str | None) -> str | None:
    """Return a deterministic, indexable HMAC-SHA256 lookup value for ``value``.

    C2: emails are encrypted at rest and ``email_hash`` uses (deliberately slow)
    Argon2id, so login must not scan and per-row Argon2id-verify every user. This
    fast HMAC digest is stored in the indexed ``email_lookup_hash`` column so an
    email can be found with a single indexed equality lookup.
    """

    normalized = normalize_email(value)
    if normalized is None:
        return None

    secret = _load_hash_secret()
    return hmac.new(secret, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_email_hash(value: str | None, stored_hash: str | None) -> bool:
    normalized = normalize_email(value)
    if normalized is None or not stored_hash:
        return False

    if stored_hash.startswith("$argon2id$"):
        try:
            Argon2id.verify_phc_encoded(normalized.encode("utf-8"), stored_hash)
            return True
        except InvalidKey:
            return False

    # Backward compatibility with previously-stored HMAC-SHA256 hashes.
    secret = _load_hash_secret()
    digest = hmac.new(secret, normalized.encode("utf-8"), "sha256").hexdigest()
    return hmac.compare_digest(digest, stored_hash)


def reset_email_crypto_state() -> None:
    """Reset cached cipher and hash secret (useful for tests)."""

    global _EMAIL_CIPHER, _EMAIL_HASH_SECRET, _EMAIL_KEY_BYTES
    _EMAIL_CIPHER = None
    _EMAIL_HASH_SECRET = None
    _EMAIL_KEY_BYTES = None


__all__ = [
    "allow_email_decryption",
    "can_decrypt_emails",
    "decrypt_email",
    "encrypt_email",
    "hash_email",
    "mask_email",
    "normalize_email",
    "render_email",
    "reset_email_crypto_state",
    "verify_email_hash",
]
