"""The site owner's identity: one e-mail hash in ``.env``, claimed by Google.

``MAIN_ADMIN_EMAIL_HASH`` is the only owner value kept on the server. It is an
Argon2id hash of the owner's e-mail, so the address itself is not written
anywhere. There is no admin password and no special sign-in page.

The owner signs in with Google like any reader. If Google says the address is
verified, it matches the hash, and the site has no owner yet, that account
becomes the owner on the spot (``claim_owner_seat``). Ownership never passes:
once an owner exists, nobody else can claim the seat, even if the hash in
``.env`` is later changed to another address.

``scripts/make_admin_hash.py`` prints the line. It is accepted in two forms:

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
from sqlalchemy import or_

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


def owner_sign_in_in_use() -> bool:
    """The site has an owner e-mail set up, so the owner needs an authenticator."""

    return bool(get_main_admin_email_hash())


def owner_exists(db) -> bool:
    from ..models import User, UserRole

    return (
        db.query(User.id)
        .filter(
            or_(
                User.permanent.is_(True),
                User.is_main_admin.is_(True),
                User.role == UserRole.PERMANENT,
            )
        )
        .first()
        is not None
    )


def wants_owner_seat(db, email: str | None) -> bool:
    """True when ``email`` is the configured owner's and nobody holds the seat.

    The cheap "is there an owner" query runs first, so the slow hash check is
    only paid on a site that has no owner yet, never on every later sign-in.
    """

    if not get_main_admin_email_hash() or owner_exists(db):
        return False
    return is_configured_main_admin_email(email)


def claim_owner_seat(db, user) -> bool:
    """Make ``user`` the owner. Caller has checked ``wants_owner_seat``.

    Returns ``True`` when a change was made (the caller commits).
    """

    from ..models import AdminAuditLog, UserRole

    changed = False
    for field, value in (
        ("role", UserRole.PERMANENT),
        ("permanent", True),
        ("is_main_admin", True),
        ("is_secondary_admin", True),
    ):
        if getattr(user, field, None) != value:
            setattr(user, field, value)
            changed = True
    if changed:
        db.add(
            AdminAuditLog(
                user_id=getattr(user, "id", None),
                operator="owner_sign_in",
                action="OWNER_SEAT_CLAIMED",
                metadata_json={"via": "google"},
            )
        )
    return changed
