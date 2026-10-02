"""Second factor for administrators (roadmap item 15).

Login is Google or a magic link, so an attacker who controls the admin's mailbox
or Google account would own the site. This adds a TOTP check (RFC 6238, the
codes an authenticator app shows) on top of that:

* An admin enrols an authenticator app (``setup`` then ``enable``).
* From then on, admin routes also need a short-lived *step-up* cookie, which
  the admin gets by entering a current code (``verify``).
* It is mandatory for the main admin once the owner e-mail is set up
  (``MAIN_ADMIN_EMAIL_HASH``). The owner enrols from the admin area right after
  the first Google sign-in; admin features stay shut until they have.

Standard library only; the secret is encrypted at rest like OAuth tokens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta
from urllib.parse import quote

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..core.security import _create_token, _get_algorithm, _get_secret_key
from ..models import User
from ..utils.email_crypto import decrypt_secret, encrypt_secret

STEP_SECONDS = 30
DIGITS = 6
# Accept the previous and next step too, for clock drift between phone and server.
WINDOW = 1
STEP_UP_COOKIE = "admin_stepup_cookie"
STEP_UP_TOKEN_TYPE = "stepup"
STEP_UP_MINUTES = 30
ISSUER = "Manga Site"


def generate_secret() -> str:
    """A new random base32 secret (160 bits)."""

    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _code_for_step(secret: str, step: int) -> str:
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def _current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def check_code(
    secret: str, code: str, *, now: float | None = None, after_step: int | None = None
) -> int | None:
    """Return the matching step, or ``None``.

    Steps at or before ``after_step`` are refused, so a code works only once.
    """

    cleaned = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(cleaned) != DIGITS:
        return None
    current = _current_step(now)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if after_step is not None and step <= after_step:
            continue
        if hmac.compare_digest(_code_for_step(secret, step), cleaned):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
        f"&digits={DIGITS}&period={STEP_SECONDS}"
    )


def start_enrolment(db: Session, user: User) -> str:
    """Store a fresh, not yet enabled secret and return it."""

    secret = generate_secret()
    user.totp_secret_encrypted = encrypt_secret(secret)
    user.totp_enabled = False
    user.totp_last_step = None
    db.commit()
    return secret


def _stored_secret(user: User) -> str | None:
    if not user.totp_secret_encrypted:
        return None
    return decrypt_secret(user.totp_secret_encrypted)


def verify_user_code(db: Session, user: User, code: str, *, enabled_only: bool) -> bool:
    """Check a code against the user's secret and burn the step on success."""

    if enabled_only and not user.totp_enabled:
        return False
    secret = _stored_secret(user)
    if not secret:
        return False
    step = check_code(secret, code, after_step=user.totp_last_step)
    if step is None:
        return False
    user.totp_last_step = step
    db.commit()
    return True


def enable(db: Session, user: User, code: str) -> bool:
    if not verify_user_code(db, user, code, enabled_only=False):
        return False
    user.totp_enabled = True
    db.commit()
    return True


def disable(db: Session, user: User) -> None:
    user.totp_secret_encrypted = None
    user.totp_enabled = False
    user.totp_last_step = None
    db.commit()


def create_step_up_token(user: User) -> str:
    return _create_token(str(user.id), STEP_UP_TOKEN_TYPE, timedelta(minutes=STEP_UP_MINUTES))


def step_up_valid(user: User, token: str | None) -> bool:
    """True when ``token`` is a live step-up token for this very user."""

    if not token:
        return False
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[_get_algorithm()])
    except JWTError:
        return False
    if payload.get("type") != STEP_UP_TOKEN_TYPE or payload.get("sub") != str(user.id):
        return False
    from . import token_revocation

    # "Sign out everywhere" also ends a step-up.
    return not token_revocation.issued_before_cutoff(user, payload)
