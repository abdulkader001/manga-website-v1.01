"""Main-administrator identity for the one-time Admin sign-in (/admin-login).

Two values in ``.env`` (never in source control) identify the site owner:

* ``MAIN_ADMIN_EMAIL_HASH``    -- Argon2id hash of the owner's e-mail,
* ``MAIN_ADMIN_PASSWORD_HASH`` -- Argon2id hash of the ONE-TIME admin password.

``scripts/make_admin_hash.py`` prints them. Both are accepted in two forms:

* ``a2:<base64url>`` (what the tool prints): the Argon2id PHC string wrapped in
  base64url, so it has no ``$`` in it. Docker Compose, ``source .env`` and
  PowerShell all treat ``$`` as "insert a variable here" and silently mangle a
  raw hash; this form survives every one of them, quoted or not.
* the raw Argon2id PHC string (starts with a dollar sign), for hashes made
  before.

Surrounding quotes are tolerated too (``docker run --env-file`` and some
hosting panels keep them as part of the value).
"""

from __future__ import annotations

import base64
import binascii

import structlog
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .settings import settings
from ..utils.email_crypto import normalize_email

logger = structlog.get_logger("backend_fastapi.admin_identity")

WRAPPED_PREFIX = "a2:"


def decode_admin_hash(value: str | None) -> str | None:
    """Return the Argon2id PHC string from an env value, or ``None``."""

    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    if not text:
        return None
    if text.startswith(WRAPPED_PREFIX):
        body = text[len(WRAPPED_PREFIX):]
        try:
            text = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
        except (binascii.Error, ValueError):
            return None
    return text or None


def get_main_admin_email_hash() -> str | None:
    return decode_admin_hash(getattr(settings, "main_admin_email_hash", None))


def get_main_admin_password_hash() -> str | None:
    return decode_admin_hash(getattr(settings, "main_admin_password_hash", None))


def _verify(secret: bytes, hash_value: str, name: str) -> bool:
    try:
        Argon2id.verify_phc_encoded(secret, hash_value)
        return True
    except InvalidKey:
        return False
    except Exception:  # malformed hash in .env
        logger.warning(
            "invalid_admin_hash",
            setting=name,
            message=f"{name} is not a valid hash; make a new one with "
            "scripts/make_admin_hash.py",
        )
        return False


def is_configured_main_admin_email(email: str | None) -> bool:
    """True when ``email`` matches ``MAIN_ADMIN_EMAIL_HASH``."""

    hash_value = get_main_admin_email_hash()
    normalized = normalize_email(email)
    if not hash_value or normalized is None:
        return False
    return _verify(normalized.encode("utf-8"), hash_value, "MAIN_ADMIN_EMAIL_HASH")


def admin_password_configured() -> bool:
    """Admin sign-in is set up: both the email hash and the password hash."""

    return bool(get_main_admin_email_hash() and get_main_admin_password_hash())


def verify_main_admin_password(password: str | None) -> bool:
    """True when ``password`` matches ``MAIN_ADMIN_PASSWORD_HASH``.

    Spaces or a line break at either end (a copy-paste accident) are ignored;
    the hash tool strips them the same way.
    """

    hash_value = get_main_admin_password_hash()
    if not hash_value or not password:
        return False
    candidates = [password.strip()]
    if password != candidates[0]:
        candidates.append(password)  # hashes made before trimming existed
    return any(
        c and _verify(c.encode("utf-8"), hash_value, "MAIN_ADMIN_PASSWORD_HASH")
        for c in candidates
    )


def admin_sign_in_in_use(session=None) -> bool:
    """This site's owner is protected by the one-time Admin sign-in.

    True while a one-time password is set in .env, and for ever once one has
    been used -- so deleting the used hash from .env afterwards does NOT switch
    off the authenticator requirement for the main admin.
    """

    if admin_password_configured():
        return True
    from ..models import SystemSettings

    def _used(db) -> bool:
        row = db.query(SystemSettings.admin_setup_password_used).first()
        return bool(row and row[0])

    try:
        if session is not None:
            used = _used(session)
        else:
            from .db import SessionLocal

            with SessionLocal() as db:
                used = _used(db)
    except Exception:  # pragma: no cover - defensive
        logger.exception("admin_sign_in_marker_unreadable")
        return False
    return used
