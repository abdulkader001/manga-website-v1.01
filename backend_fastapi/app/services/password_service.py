"""Optional account passwords (Argon2id, PHC-encoded, random salt)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from ..models import User

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

# Account-level lockout, on top of the per-IP/per-email rate limits in the
# login endpoint: after this many consecutive wrong passwords the account's
# password login pauses (magic link keeps working, so this never locks a
# reader out of their account).
MAX_FAILED_LOGINS = 8
LOCKOUT = timedelta(minutes=15)

_COMMON_PASSWORDS = {
    "password",
    "password1",
    "12345678",
    "123456789",
    "1234567890",
    "qwertyuiop",
    "iloveyou",
    "11111111",
    "00000000",
    "abc12345",
    "passw0rd",
    "letmein1",
}

# A valid-format hash of a random secret: verifying against it when an
# account has no password (or does not exist) keeps response time the same,
# so login timing does not reveal which emails are registered.
_DUMMY_HASH: str | None = None


def _kdf(salt: bytes) -> Argon2id:
    return Argon2id(
        salt=salt,
        length=32,
        iterations=3,
        lanes=4,
        memory_cost=65536,
    )


def validate_new_password(password: str) -> str | None:
    """Return a user-facing error, or ``None`` if acceptable."""

    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if password.lower() in _COMMON_PASSWORDS:
        return "That password is too common. Please choose another."
    return None


def hash_password(password: str) -> str:
    return _kdf(os.urandom(16)).derive_phc_encoded(password.encode("utf-8"))


def _verify_hash(password: str, encoded: str) -> bool:
    try:
        Argon2id.verify_phc_encoded(password.encode("utf-8"), encoded)
        return True
    except (InvalidKey, ValueError):
        return False


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(os.urandom(24).hex())
    return _DUMMY_HASH


def is_locked(user: User, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    return bool(user.login_locked_until and user.login_locked_until > now)


def check_password(user: User | None, password: str) -> bool:
    """Constant-work verification; also updates the lockout counters."""

    if user is None or not user.password_hash:
        _verify_hash(password, _dummy_hash())
        return False

    ok = _verify_hash(password, user.password_hash)
    if ok:
        user.failed_login_count = 0
        user.login_locked_until = None
    else:
        user.failed_login_count = int(user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.login_locked_until = datetime.utcnow() + LOCKOUT
            user.failed_login_count = 0
    return ok
