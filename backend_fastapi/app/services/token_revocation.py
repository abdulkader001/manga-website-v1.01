"""Server-side revocation for the stateless JWTs (Tier 2.9).

Access and refresh tokens are signed and self-contained: without this module
nothing the server does can invalidate one before it expires. ``POST
/auth/logout`` cleared the browser's cookies and nothing else, so a refresh
token captured off the wire, pulled out of a stolen browser profile, or left
behind on a shared machine stayed usable for the entire configured session
length — up to 30 days.

Two mechanisms, deliberately different in cost:

* **Per-token denylist** (``revoked_tokens``) — for revoking one specific
  token: logout, and the old refresh token on each rotation. One indexed
  lookup on the read path.
* **Per-user cutoff** (``users.sessions_revoked_before``) — for "sign out
  everywhere" and administrative revocation. One timestamp invalidates every
  outstanding token for that account without writing a row per token, and the
  users row is already loaded by the auth dependency, so it costs nothing
  extra to check.

Refresh-token *rotation* is what makes the denylist worth having: each refresh
consumes its token and issues a new one, so presenting an already-consumed
refresh token means either a replay or that someone else got there first. That
is treated as a compromise and revokes the whole account's sessions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import RevokedToken, User

logger = structlog.get_logger("backend_fastapi.token_revocation")


def _as_naive_utc(value: datetime) -> datetime:
    """Store timestamps naive-UTC, matching the rest of this schema."""

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _expiry_from_payload(payload: Mapping[str, Any]) -> datetime:
    raw = payload.get("exp")
    if raw is None:
        # A token with no exp should never have been issued; treat it as
        # already expired so the row is purged rather than kept forever.
        return datetime.now(tz=timezone.utc).replace(tzinfo=None)
    return datetime.fromtimestamp(int(raw), tz=timezone.utc).replace(tzinfo=None)


def revoke(db: Session, payload: Mapping[str, Any], *, reason: str) -> bool:
    """Deny future use of the token described by ``payload``.

    Returns False when the token carries no ``jti`` — tokens issued before
    this feature existed. Those are not individually revocable; they expire on
    their own, and ``revoke_all_for_user`` covers them in the meantime.
    """

    jti = payload.get("jti")
    if not jti:
        return False

    subject = payload.get("sub")
    try:
        user_id: int | None = int(subject) if subject is not None else None
    except (TypeError, ValueError):
        user_id = None

    db.add(
        RevokedToken(
            jti=str(jti),
            user_id=user_id,
            token_type=str(payload.get("type") or "unknown"),
            reason=reason,
            expires_at=_expiry_from_payload(payload),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Already revoked — two logouts racing, or a replayed token. The
        # outcome the caller wants is already true.
        db.rollback()
    return True


def is_revoked(db: Session, payload: Mapping[str, Any]) -> bool:
    """Whether this exact token has been revoked."""

    jti = payload.get("jti")
    if not jti:
        return False
    return (
        db.query(RevokedToken.id).filter(RevokedToken.jti == str(jti)).first()
        is not None
    )


def issued_before_cutoff(user: User, payload: Mapping[str, Any]) -> bool:
    """Whether ``payload`` predates the account's sign-out-everywhere cutoff."""

    cutoff = getattr(user, "sessions_revoked_before", None)
    if cutoff is None:
        return False

    issued_ms = payload.get("iat_ms")
    if issued_ms is not None:
        # Millisecond resolution: an exact comparison, no rounding either way.
        issued = datetime.fromtimestamp(int(issued_ms) / 1000, tz=timezone.utc).replace(
            tzinfo=None
        )
        return issued < _as_naive_utc(cutoff)

    issued_at = payload.get("iat")
    if issued_at is None:
        # No issue time to compare against: refuse rather than let a token of
        # unknown vintage survive an explicit revocation.
        return True

    # Legacy token minted before iat_ms existed: only whole seconds are
    # available, so round in the safe direction and refuse anything issued in
    # or before the revocation second.
    issued = datetime.fromtimestamp(int(issued_at), tz=timezone.utc).replace(
        tzinfo=None
    )
    return issued <= _as_naive_utc(cutoff)


def revoke_all_for_user(db: Session, user: User, *, reason: str) -> None:
    """Invalidate every outstanding token for ``user`` (sign out everywhere)."""

    user.sessions_revoked_before = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    db.commit()
    logger.info(
        "user_sessions_revoked",
        user_id=getattr(user, "id", None),
        reason=reason,
    )


def purge_expired(db: Session) -> int:
    """Drop denylist rows for tokens that have expired on their own.

    Past ``expires_at`` the signature check refuses the token anyway, so the
    row carries no information — without this the table grows forever.
    """

    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    deleted = (
        db.query(RevokedToken)
        .filter(RevokedToken.expires_at < now)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


__all__ = [
    "is_revoked",
    "issued_before_cutoff",
    "purge_expired",
    "revoke",
    "revoke_all_for_user",
]
