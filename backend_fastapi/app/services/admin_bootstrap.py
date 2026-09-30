"""Admin bootstrap helpers for FastAPI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import structlog
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models import (
    AdminBootstrapState,
    AdminPromotionToken,
    User,
    UserRole,
)
from ..utils.email_crypto import allow_email_decryption, mask_email
from .audit_service import audit_service
from .system_state import get_or_create_system_state

logger = structlog.get_logger(__name__)

UTC = timezone.utc


class AdminTokenError(Exception):
    """Base exception for admin promotion token issues."""


class AdminTokenNotConfigured(AdminTokenError):
    """Raised when the promotion secret is missing."""


class AdminTokenInvalid(AdminTokenError):
    """Raised when the token structure or signature is invalid."""


class AdminTokenExpired(AdminTokenError):
    """Raised when the token has expired."""


class AdminTokenRedeemed(AdminTokenError):
    """Raised when the token has already been redeemed or revoked."""


class AdminAlreadyInitialized(AdminTokenError):
    """Raised when bootstrap has already completed and a new bootstrap token
    is requested (#11: issuance must not mint further one-time-admin tokens
    once the system already has its main admin)."""


@contextmanager
def _session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - defensive rollback
        session.rollback()
        raise
    finally:
        session.close()


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _get_secret() -> str:
    secret = os.getenv("ADMIN_PROMOTION_SECRET", "").strip()
    if not secret:
        raise AdminTokenNotConfigured("ADMIN_PROMOTION_SECRET is not configured")
    return secret


def _default_ttl_seconds() -> int:
    try:
        value = int(os.getenv("ADMIN_PROMOTION_TOKEN_TTL_SECONDS", "1800"))
        return max(0, value)
    except (TypeError, ValueError):  # pragma: no cover - environment parsing
        return 1800


def _max_ttl_seconds() -> Optional[int]:
    raw = os.getenv("ADMIN_PROMOTION_TOKEN_MAX_TTL_SECONDS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:  # pragma: no cover - environment parsing
        logger.warning("Invalid ADMIN_PROMOTION_TOKEN_MAX_TTL_SECONDS=%s", raw)
        return None
    return value if value > 0 else None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _sign_payload(secret: str, payload: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _build_token(secret: str) -> tuple[str, str]:
    payload = secrets.token_urlsafe(32)
    signature = _sign_payload(secret, payload)
    token = f"{payload}.{signature}"
    return token, payload


def _parse_token(secret: str, token: str) -> tuple[str, str]:
    if not token:
        raise AdminTokenInvalid("Token is empty")

    if "." not in token:
        raise AdminTokenInvalid("Token is malformed")

    payload, signature = token.split(".", 1)
    expected = _sign_payload(secret, payload)
    if not hmac.compare_digest(signature, expected):
        raise AdminTokenInvalid("Token signature mismatch")
    return token, payload


def _get_or_create_bootstrap_state(session: Session) -> AdminBootstrapState:
    state = session.query(AdminBootstrapState).first()
    if state is None:
        state = AdminBootstrapState(id=1, admin_initialized=False)
        session.add(state)
        session.flush()
    return state


def issue_admin_token(
    *,
    operator_user_id: Optional[int] = None,
    operator_label: Optional[str] = None,
    source_ip: Optional[str] = None,
    issued_to_user_id: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
    session: Optional[Session] = None,
) -> str:
    """Create a one-time admin promotion token and persist its hash."""

    secret = _get_secret()
    default_ttl = _default_ttl_seconds()
    max_ttl = _max_ttl_seconds()

    ttl = ttl_seconds if ttl_seconds is not None else default_ttl
    if ttl is None:
        ttl = default_ttl
    ttl = max(0, ttl)
    if max_ttl is not None and ttl > max_ttl:
        ttl = max_ttl

    def _issue(db: Session) -> str:
        state = _get_or_create_bootstrap_state(db)
        if state.admin_initialized:
            # The only caller of this function today (the CLI bootstrap
            # command) mints the one-time token that establishes the main
            # admin; once that has happened, issuing another live token would
            # let a second, unrelated promotion succeed against a system that
            # is already initialized. Refuse rather than mint it.
            raise AdminAlreadyInitialized(
                "Admin bootstrap has already completed; refusing to issue a "
                "new bootstrap token."
            )

        token, payload = _build_token(secret)
        token_hash = _hash_token(token)

        expires_at = _utcnow() + timedelta(seconds=ttl) if ttl > 0 else None

        record = AdminPromotionToken(
            token_hash=token_hash,
            expires_at=expires_at,
            issued_by_user_id=operator_user_id,
            issued_to_user_id=issued_to_user_id,
        )
        db.add(record)
        state.last_token_issued_at = _utcnow()

        db.flush()

        audit_metadata = {
            "token_id": record.id,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "issued_to_user_id": issued_to_user_id,
            "payload_hint": payload[:6],
        }
        try:
            audit_service.log_action(
                operator_user_id,
                "admin_token.issue",
                metadata=audit_metadata,
                operator=operator_label,
                source_ip=source_ip,
            )
        except Exception:  # pragma: no cover - audit logging is best effort
            logger.exception("Failed to record admin token issuance audit entry")
        logger.info("Admin promotion token issued id=%s", record.id)
        return token

    if session is not None:
        return _issue(session)

    with _session_scope() as db:
        return _issue(db)


def redeem_admin_token(
    user: User,
    token: str,
    *,
    source_ip: Optional[str] = None,
    session: Optional[Session] = None,
) -> bool:
    """Redeem a token for the provided user, promoting them to admin."""

    secret = _get_secret()

    def _redeem(db: Session) -> bool:
        parsed_token, _ = _parse_token(secret, token.strip())
        token_hash = _hash_token(parsed_token)

        stmt = (
            select(AdminPromotionToken)
            .where(AdminPromotionToken.token_hash == token_hash)
            .with_for_update()
        )
        record = db.execute(stmt).scalar_one_or_none()
        if record is None:
            raise AdminTokenInvalid("Token not recognized")

        now = _utcnow()
        if record.revoked_at is not None:
            raise AdminTokenRedeemed("Token has been revoked")
        if record.redeemed_at is not None:
            raise AdminTokenRedeemed("Token already redeemed")
        if record.expires_at is not None:
            expires_at = record.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < now:
                raise AdminTokenExpired("Token expired")

        db_user = db.get(User, user.id)
        if db_user is None:
            raise AdminTokenError("User not found")

        if hasattr(db_user, "promote_to_permanent_admin"):
            db_user.promote_to_permanent_admin()
        else:
            db_user.role = UserRole.PERMANENT
            db_user.permanent = True

        db_user.is_main_admin = True
        db_user.is_secondary_admin = True

        state = _get_or_create_bootstrap_state(db)
        state.admin_initialized = True
        state.initialized_at = now
        state.initialized_by_user_id = db_user.id
        state.last_token_redeemed_at = now

        system_state = get_or_create_system_state(db, for_update=True)
        system_state.secret_phrase_used = True
        with allow_email_decryption():
            main_admin_email = db_user.email
        system_state.main_admin_email = main_admin_email

        record.redeemed_at = now
        record.redeemed_by_user_id = db_user.id
        record.redeemed_source_ip = source_ip[:45] if source_ip else None

        db.flush()
        db.commit()
        db.refresh(db_user)
        db.refresh(system_state)

        audit_metadata = {
            "token_id": record.id,
            "token_hash": record.token_hash,
            "redeemed_by": db_user.id,
            "source_ip": record.redeemed_source_ip,
        }
        try:
            audit_service.log_action(
                db_user.id,
                "admin_token.redeem",
                metadata=audit_metadata,
                operator="user",
                source_ip=source_ip,
            )
        except Exception:  # pragma: no cover - audit best effort
            logger.exception("Failed to record admin token redemption audit entry")

        with allow_email_decryption():
            masked = mask_email(main_admin_email)
        logger.info(
            "Admin promotion token redeemed by user_id=%s email=%s",
            db_user.id,
            masked,
        )
        return True

    if session is not None:
        return _redeem(session)

    with _session_scope() as db:
        return _redeem(db)


__all__ = [
    "AdminAlreadyInitialized",
    "AdminTokenError",
    "AdminTokenExpired",
    "AdminTokenInvalid",
    "AdminTokenNotConfigured",
    "ensure_bootstrap_state_initialized",
    "issue_admin_token",
    "redeem_admin_token",
]


def ensure_bootstrap_state_initialized() -> None:
    """Ensure the singleton row exists."""
    with _session_scope() as session:
        _get_or_create_bootstrap_state(session)
