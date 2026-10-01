from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from ..models import User, LoginToken
from ..core.security import create_access_token, create_refresh_token
from ..schemas.auth import TokenPair

from ..utils.email_crypto import email_identity, email_lookup, hash_email

logger = structlog.get_logger("backend_fastapi.auth_service")


SESSION_EXPIRY_MIN_DAYS = 1
SESSION_EXPIRY_MAX_DAYS = 30
SESSION_EXPIRY_DEFAULT_DAYS = 14


def get_session_expiry_days(db: Session) -> int:
    """Admin-configured session lifetime, clamped to [1, 30] days (SRS 1D.5.1)."""

    from .system_settings_service import get_or_create_system_settings

    try:
        row = get_or_create_system_settings(db)
    except Exception:  # pragma: no cover - defensive
        return SESSION_EXPIRY_DEFAULT_DAYS
    value = getattr(row, "session_expiry_days", None) if row else None
    if not value:
        return SESSION_EXPIRY_DEFAULT_DAYS
    return max(SESSION_EXPIRY_MIN_DAYS, min(SESSION_EXPIRY_MAX_DAYS, int(value)))


def issue_tokens_for_user(user: User, db: Session | None = None) -> TokenPair:
    access_token = create_access_token(subject=str(user.id))
    expiry_days = get_session_expiry_days(db) if db is not None else None
    refresh_token = create_refresh_token(subject=str(user.id), expires_days=expiry_days)
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


def normalize_email(value: str) -> str:
    return value.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    """Find a user by email using an indexed lookup rather than a full scan.

    C2: previously this loaded every user and ran an Argon2id verify per row,
    which is O(n) and a timing/DoS vector. It now queries the indexed
    ``email_lookup_hash`` (fast HMAC). For rows not yet backfilled it falls back
    to the deterministic, *indexed* ``email_hash`` and self-heals the lookup
    value — it never scans the whole table.
    """

    norm_email = normalize_email(email)
    if norm_email is None:
        return None

    # One inbox, one account: every spelling of the same mailbox (gmail dots,
    # googlemail.com, +tags) finds the account that owns it.
    identity = email_identity(norm_email)
    if identity is not None:
        user = db.query(User).filter(User.email_identity_hash == identity).first()
        if user is not None:
            lookup = email_lookup(norm_email)
            if (
                lookup is not None
                and not user.email_lookup_hash
                and normalize_email(user.email_plaintext) == norm_email
            ):
                user.email_lookup_hash = lookup
            return user

    lookup = email_lookup(norm_email)
    if lookup is not None:
        user = db.query(User).filter(User.email_lookup_hash == lookup).first()
        if user is not None:
            _heal_identity(db, user, identity)
            return user

    # Fallback for rows written before the lookup-hash column was backfilled.
    # ``hash_email`` is deterministic and ``email_hash`` is indexed+unique, so
    # this is still an indexed equality lookup (not an O(n) scan).
    deterministic_hash = hash_email(norm_email)
    if deterministic_hash is not None:
        user = db.query(User).filter(User.email_hash == deterministic_hash).first()
        if user is not None:
            if lookup is not None and not user.email_lookup_hash:
                user.email_lookup_hash = lookup
            _heal_identity(db, user, identity)
            return user
    return None


def _heal_identity(db: Session, user: User, identity: str | None) -> None:
    """Fill in the identity key on rows created before it existed. Skipped
    when another account already holds it (an old duplicate the admin can
    review); new duplicates are impossible because the column is unique."""

    if not identity or user.email_identity_hash:
        return
    taken = (
        db.query(User.id)
        .filter(User.email_identity_hash == identity, User.id != user.id)
        .first()
    )
    if taken is None:
        user.email_identity_hash = identity


def ensure_magic_link_user(db: Session, email: str) -> User:
    norm_email = normalize_email(email)
    user = get_user_by_email(db, norm_email)
    if user:
        return user
    user = User(
        email=norm_email,
        username=norm_email.split("@")[0],
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        user = get_user_by_email(db, norm_email)
        if not user:
            raise HTTPException(
                status_code=500, detail="Failed to create user concurrently"
            )
        return user
    return user


def hash_login_token(token_value: str) -> str:
    """Hash a magic-link token for storage/lookup (SRS 1D.1A.3).

    Tokens carry >=128 bits of entropy so a plain SHA-256 (no salt needed for a
    high-entropy secret) is a safe, fast one-way store.
    """

    import hashlib

    return hashlib.sha256(token_value.encode("utf-8")).hexdigest()


def _magic_link_ttl_minutes(db: Session) -> int:
    """Admin-configurable magic-link expiry (SRS 1D.1A.3: 15 min default, 5–60)."""

    from .system_settings_service import get_or_create_system_settings

    default = 15
    try:
        settings_row = get_or_create_system_settings(db)
    except Exception:  # pragma: no cover - defensive
        return default
    value = (
        getattr(settings_row, "magic_link_ttl_minutes", None) if settings_row else None
    )
    if not value:
        return default
    return max(5, min(60, int(value)))


def create_magic_login_token(db: Session, user: User) -> tuple[LoginToken, str]:
    """Create a single-use magic-link token.

    Returns ``(record, plaintext)``. Only the hash is persisted; the plaintext
    is returned to the caller for the email link and never stored. Issuing a new
    link invalidates the user's previous unused links (SRS 1D.1A.3).
    """

    import secrets

    # Invalidate previous unused, unexpired links for this user.
    now = datetime.utcnow()
    (
        db.query(LoginToken)
        .filter(
            LoginToken.user_id == user.id,
            LoginToken.used_at.is_(None),
            LoginToken.expires_at > now,
        )
        .update({LoginToken.used_at: now}, synchronize_session=False)
    )

    token_value = secrets.token_urlsafe(32)  # 256 bits, > 128-bit minimum
    expires_at = now + timedelta(minutes=_magic_link_ttl_minutes(db))
    token_record = LoginToken(
        token_hash=hash_login_token(token_value),
        user_id=user.id,
        email=user.email_plaintext,
        expires_at=expires_at,
    )
    db.add(token_record)
    db.commit()
    return token_record, token_value


def _redeem_login_token(db: Session, token_value: str) -> LoginToken:
    """Atomically mark a magic-link token used, or raise why it couldn't be.

    #55/F-2: the previous read-then-write (``get_valid_login_token`` followed
    by ``token_record.mark_used()``) let two concurrent requests both read
    "unused" and both succeed -- classic corporate mail scanners (Safe Links,
    URL Defense) fetch a link at nearly the same moment the user clicks it.
    A single conditional ``UPDATE ... WHERE used_at IS NULL`` closes that
    window: only one of two racing UPDATEs can match an unused row, because
    the database serializes concurrent writes to it. The loser affects zero
    rows and is rejected below, instead of also succeeding.
    """

    token_hash = hash_login_token(token_value)
    now = datetime.utcnow()

    updated = (
        db.query(LoginToken)
        .filter(
            LoginToken.token_hash == token_hash,
            LoginToken.used_at.is_(None),
            LoginToken.expires_at > now,
        )
        .update({LoginToken.used_at: now}, synchronize_session=False)
    )

    if updated:
        db.commit()
        token_record = (
            db.query(LoginToken)
            .filter(LoginToken.token_hash == token_hash)
            .first()
        )
        if token_record is not None:
            return token_record

    # Either nothing matched or (defensively) the row vanished after the
    # update -- roll back and re-read without a lock, purely to classify the
    # failure into the right error message.
    db.rollback()
    token_record = (
        db.query(LoginToken).filter(LoginToken.token_hash == token_hash).first()
    )
    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid magic link.",
        )
    if token_record.is_used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Magic link has already been used.",
        )
    if token_record.is_expired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Magic link has expired.",
        )
    # Existed, unused, unexpired, yet the conditional UPDATE matched zero rows:
    # a concurrent redemption won the race between our SELECT and UPDATE.
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Magic link has already been used.",
    )


def mark_email_verified(user: User) -> None:
    """Mark the account's email as verified (SRS 1D.2.4).

    Verification's only purpose here is confirming a genuine, reachable email —
    set once and left set.
    """

    if not getattr(user, "email_verified", False):
        user.email_verified = True
        user.email_verified_at = datetime.utcnow()


def consume_magic_link(db: Session, token_value: str) -> dict[str, Any]:
    token_record = _redeem_login_token(db, token_value)
    user = token_record.user
    # Clicking the link proves the user controls the mailbox.
    mark_email_verified(user)

    # Defense-in-depth (SRS 1H.7.1 / D5): the domain may have been added to
    # the blocklist after this account was created. Flags for review; never
    # blocks this login.
    from .disposable_email import flag_if_disposable

    flag_if_disposable(db, user)

    db.commit()

    tokens = issue_tokens_for_user(user, db)

    import uuid

    new_csrf_token = uuid.uuid4().hex
    if hasattr(user, "csrf_token"):
        user.csrf_token = new_csrf_token
        db.commit()

    return {
        "message": "magic_link_authenticated",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": tokens.token_type,
        "user": {
            "id": user.id,
            "email": None,
            "email_hash": user.email_hash,
            "username": user.username,
            "role": user.role.value if hasattr(user.role, "value") else user.role,
            "csrf_token": new_csrf_token,
        },
    }
