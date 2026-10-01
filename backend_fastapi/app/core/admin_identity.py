"""Configurable main-administrator identity (C5).

The Argon2id hash of the main admin's email address is supplied via the
``MAIN_ADMIN_EMAIL_HASH`` environment variable and must never be committed to
source control. Auto-promotion of a matching account to main admin on login is
disabled by default and must be explicitly enabled via
``MAIN_ADMIN_AUTO_PROMOTE_ENABLED`` — this is intended only for first-time
bootstrap and should be disabled again immediately afterwards.
"""

from __future__ import annotations

import structlog
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .settings import settings
from ..utils.email_crypto import normalize_email

logger = structlog.get_logger("backend_fastapi.admin_identity")


def get_main_admin_email_hash() -> str | None:
    """Return the configured main-admin email hash, or ``None`` when unset."""

    value = getattr(settings, "main_admin_email_hash", None)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def auto_promote_enabled() -> bool:
    """Return ``True`` when login-time auto-promotion is explicitly enabled."""

    return bool(getattr(settings, "main_admin_auto_promote_enabled", False))


def is_configured_main_admin_email(email: str | None) -> bool:
    """Return ``True`` when ``email`` matches the configured main-admin hash.

    Returns ``False`` when no hash is configured. This does **not** consider the
    ``MAIN_ADMIN_AUTO_PROMOTE_ENABLED`` flag; callers must gate the actual
    promotion on :func:`auto_promote_enabled` separately.
    """

    hash_value = get_main_admin_email_hash()
    if not hash_value:
        return False

    normalized = normalize_email(email)
    if normalized is None:
        return False

    try:
        Argon2id.verify_phc_encoded(normalized.encode("utf-8"), hash_value)
        return True
    except InvalidKey:
        return False
    except Exception:  # pragma: no cover - defensive: malformed hash config
        logger.warning(
            "invalid_main_admin_email_hash",
            message="MAIN_ADMIN_EMAIL_HASH is not a valid Argon2id PHC string; "
            "ignoring auto-promotion",
        )
        return False


def get_main_admin_password_hash() -> str | None:
    value = getattr(settings, "main_admin_password_hash", None)
    value = str(value).strip() if value is not None else ""
    return value or None


def admin_password_configured() -> bool:
    """Admin sign-in is set up: both the email hash and the password hash."""

    return bool(get_main_admin_email_hash() and get_main_admin_password_hash())


def verify_main_admin_password(password: str | None) -> bool:
    hash_value = get_main_admin_password_hash()
    if not hash_value or not password:
        return False
    try:
        Argon2id.verify_phc_encoded(password.encode("utf-8"), hash_value)
        return True
    except InvalidKey:
        return False
    except Exception:  # malformed hash config
        logger.warning(
            "invalid_main_admin_password_hash",
            message="MAIN_ADMIN_PASSWORD_HASH is not a valid Argon2id PHC string",
        )
        return False
