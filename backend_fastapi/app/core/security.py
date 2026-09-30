"""Authentication helpers for JWT handling."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import JWTError, jwt

from .settings import settings

REFRESH_TOKEN_EXPIRE_DAYS = 7


def _get_secret_key() -> str:
    """Return the configured JWT secret key."""

    if not settings.jwt_secret_key:
        raise RuntimeError("JWT_SECRET_KEY is not configured.")
    return settings.jwt_secret_key


def _get_algorithm() -> str:
    """Return the configured JWT signing algorithm."""

    algorithm = (settings.algorithm or "").strip()
    if not algorithm:
        raise RuntimeError("ALGORITHM is not configured.")
    return algorithm


def _get_access_token_expiry_minutes() -> int:
    """Return the configured access token lifetime in minutes."""

    minutes = settings.access_token_expire_minutes
    if minutes is None:
        raise RuntimeError("ACCESS_TOKEN_EXPIRE_MINUTES is not configured.")
    return minutes


def get_access_token_expiry_minutes() -> int:
    """Public accessor for the access token's lifetime (F-6: cookie Max-Age)."""

    return _get_access_token_expiry_minutes()


def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    """Create a signed JWT for the provided subject."""

    now = datetime.now(tz=timezone.utc)
    expire = now + expires_delta
    payload: Dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        # Millisecond-resolution issue time. The standard `iat` is whole
        # seconds, which cannot distinguish "minted just before a
        # sign-out-everywhere" from "minted just after" -- so a second-
        # resolution comparison either refuses the user's immediate re-login
        # or lets a token minted in the revocation second survive. This claim
        # removes the ambiguity; `iat` stays an integer for any consumer that
        # expects the standard shape.
        "iat_ms": int(now.timestamp() * 1000),
        "exp": expire,
        # Unique token id. Without it these JWTs are unrevocable: signed,
        # self-contained, and valid until they expire no matter what the
        # server does. services.token_revocation keys its denylist on this,
        # which is what makes logout and refresh-token rotation real rather
        # than cosmetic.
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=_get_algorithm())


def create_access_token(subject: str) -> str:
    """Create a short-lived access token for the given subject."""

    expires = timedelta(minutes=_get_access_token_expiry_minutes())
    return _create_token(subject, "access", expires)


def create_refresh_token(subject: str, expires_days: int | None = None) -> str:
    """Create a refresh token for the given subject.

    ``expires_days`` is the admin-configured session lifetime (SRS 1D.5.1);
    when omitted the built-in default applies.
    """

    days = (
        expires_days if expires_days and expires_days > 0 else REFRESH_TOKEN_EXPIRE_DAYS
    )
    expires = timedelta(days=days)
    return _create_token(subject, "refresh", expires)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode a JWT and return its payload."""

    try:
        return jwt.decode(token, _get_secret_key(), algorithms=[_get_algorithm()])
    except JWTError as exc:  # pragma: no cover - jose normalizes errors
        raise exc
