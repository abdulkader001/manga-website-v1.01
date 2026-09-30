"""Business logic and utility functions for administrative tasks."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..core.permissions import effective_role
from ..models import (
    AdminAuditLog,
    AdminPromotionToken,
    ScrapingJob,
    SystemSettings,
    User,
    UserRole,
)
from ..services.system_state import get_or_create_system_state
from ..utils.email_crypto import (
    allow_email_decryption,
    hash_email,
    mask_email,
    normalize_email,
)


class RateLimitExceeded(Exception):
    """Raised when a caller exceeds the configured rate limit."""


class AdminServiceError(Exception):
    """Base exception for admin service operations."""


def _alert_permanent_admin_tamper_attempt(
    actor: Optional[User], target: User, action: str
) -> None:
    """SRS 1I.3.2 security alert: an attempt to modify the Permanent
    Administrator (1F.2.4). Category=security, so this is never
    suppressible by any recipient's mute/preferences. Mirrors
    ``admin.py``'s router-level alert of the same name for the one path
    (demote-main) that reaches the Permanent Administrator's protected
    fields from within this service module."""

    from .notification_service import notify_async

    notify_async(
        type="security.permanent_admin_tamper_attempt",
        title="Attempt to modify the Permanent Administrator",
        body=(
            f"User {getattr(actor, 'id', 'unknown')} attempted to {action} "
            f"the Permanent Administrator (user {target.id}). The action was "
            "blocked; the Permanent Administrator is immutable via this path."
        ),
        data={"actor_id": getattr(actor, "id", None), "target_id": target.id},
        target_type="user",
        target_id=target.id,
    )


def bool_env(name: str, *, default: bool = False) -> bool:
    """Normalize environment configuration flags to booleans."""
    raw = os.getenv(name)
    if raw is None:
        return default

    normalized = raw.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


@dataclass
class _RateWindow:
    count: int
    expires_at: float


class RescrapeRateLimiter:
    """Simple in-memory rate limiter for admin-triggered rescrapes."""

    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._buckets: dict[str, _RateWindow] = {}

    def _current_window(self) -> float:
        return time.monotonic()

    def consume(self, key: str) -> None:
        now = self._current_window()
        window = self._buckets.get(key)
        if window and window.expires_at > now:
            if window.count >= self.limit:
                raise RateLimitExceeded()
            window.count += 1
        else:
            self._buckets[key] = _RateWindow(
                count=1, expires_at=now + self.window_seconds
            )


def resolve_rescrape_limit() -> RescrapeRateLimiter:
    """Return the shared limiter configured via environment variables."""
    count = int(os.getenv("RESCRAPE_RATE_LIMIT_COUNT", "5"))
    window = int(os.getenv("RESCRAPE_RATE_LIMIT_WINDOW", "60"))
    return RescrapeRateLimiter(limit=count, window_seconds=window)


def user_to_dict(user: User) -> dict[str, object | None]:
    data = user.to_dict()
    data["permanent"] = bool(getattr(user, "permanent", False))
    data["is_main_admin"] = bool(getattr(user, "is_main_admin", False))
    data["is_secondary_admin"] = bool(getattr(user, "is_secondary_admin", False))
    return data


def normalize_role(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"permanent_admin", "admin", "secondary_admin", "user"}:
        return normalized
    return None


def role_to_string(role: object | None) -> Optional[str]:
    if isinstance(role, UserRole):
        return role.value
    if isinstance(role, str):
        return role
    return None


def _normalize_email(value: Optional[str]) -> Optional[str]:
    return normalize_email(value)


def find_user(
    db: Session,
    *,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
) -> User | None:
    if user_id is not None:
        user = db.get(User, int(user_id))
        if user:
            return user
    if email:
        normalized = _normalize_email(email)
        if normalized:
            email_hash = hash_email(normalized)
            if email_hash:
                return db.query(User).filter(User.email_hash == email_hash).first()
    return None


def log_role_change(
    db: Session,
    *,
    actor: User | None,
    target: User,
    action: str,
    method: str,
    from_role: Optional[str],
    to_role: Optional[str],
    extra: Optional[Dict[str, object]] = None,
) -> None:
    with allow_email_decryption():
        target_email = target.email
    details: Dict[str, object] = {
        "method": method,
        "target_user_id": target.id,
        "target_email_hash": getattr(target, "email_hash", None),
        "target_email_masked": mask_email(target_email),
    }
    if from_role is not None:
        details["from_role"] = from_role
    if to_role is not None:
        details["to_role"] = to_role
    if extra:
        details.update(extra)

    audit = AdminAuditLog(
        user_id=getattr(actor, "id", None),
        action=action,
        metadata_json=details,
        operator="admin_router",
    )
    db.add(audit)
    db.commit()

    if to_role is not None:
        from .notification_service import notify_async

        notify_async(
            type="role.changed",
            title="Your role has changed",
            body=f"Your account role changed from {from_role or 'none'} to {to_role}.",
            user_id=target.id,
            data={"from_role": from_role, "to_role": to_role, "method": method},
            target_type="user",
            target_id=target.id,
        )


def audit_entry_to_dict(
    entry: AdminAuditLog, *, viewer_is_main_admin: bool = False
) -> dict[str, object | None]:
    """Serialize an audit-log row.

    F-SSS-01: ``GET /admin/users/{id}/email`` (``reveal_user_email``) gates
    plaintext-email decryption behind ``require_main_admin_user`` -- Secondary
    Admins are explicitly refused it for a single targeted user. This
    function used to decrypt and return every actor's plaintext email
    unconditionally, which any Secondary Admin could already reach via
    ``GET /admin/audit/logs``/``/search`` (gated only by ``require_admin_user``,
    "secondary or higher") -- the same fact protected by two different door
    locks, only one of which was actually locked to the right key.
    ``viewer_is_main_admin`` must be the *caller's* privilege level, not the
    audited actor's; non-main-admin viewers get ``user_email_masked`` only,
    matching what ``reveal_user_email`` already restricts.
    """

    timestamp = getattr(entry, "timestamp", None)
    with allow_email_decryption():
        user_email = entry.user.email if entry.user else None
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "user_email": user_email if viewer_is_main_admin else None,
        # F-78: the argon2id email digest is a lookup key, not audit data.
        # user_id identifies the actor; the masked address labels them.
        "user_email_masked": mask_email(user_email),
        "operator": entry.operator,
        "action": entry.action,
        "metadata": entry.metadata_json or {},
        "source_ip": entry.source_ip,
        "timestamp": timestamp.isoformat() if timestamp else None,
    }


def scraping_job_to_dict(job: ScrapingJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "source_id": job.source_id,
        "manga_id": job.manga_id,
        "source_url": job.source_url,
        "status": job.status,
        "error": job.error,
        "last_chapter_number": job.last_chapter_number,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def token_to_dict(token: AdminPromotionToken) -> dict[str, Any]:
    with allow_email_decryption():
        issued_to_email = token.issued_to_user.email if token.issued_to_user else None
        redeemed_by_email = (
            token.redeemed_by_user.email if token.redeemed_by_user else None
        )
    status = "issued"
    now = datetime.now(timezone.utc)
    if token.revoked_at is not None:
        status = "revoked"
    elif token.redeemed_at is not None:
        status = "redeemed"
    elif token.expires_at is not None:
        expires_at = token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            status = "expired"
    return {
        "id": token.id,
        "token_hash": token.token_hash,
        "issued_at": token.issued_at.isoformat() if token.issued_at else None,
        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        "issued_by_user_id": token.issued_by_user_id,
        "issued_to_user_id": token.issued_to_user_id,
        "issued_to_email_masked": mask_email(issued_to_email),
        "redeemed_at": token.redeemed_at.isoformat() if token.redeemed_at else None,
        "redeemed_by_user_id": token.redeemed_by_user_id,
        "redeemed_by_email_masked": mask_email(redeemed_by_email),
        "redeemed_source_ip": token.redeemed_source_ip,
        "status": status,
    }


DEFAULT_MODERATOR_LIMIT = 10


def effective_moderator_limit(admin: User) -> int:
    """The per-person moderator cap (SRS 1F.3.3): default 10, adjustable."""

    value = getattr(admin, "moderator_limit", None)
    return int(value) if value else DEFAULT_MODERATOR_LIMIT


def count_moderators_for(db: Session, admin_id: int) -> int:
    return (
        db.query(User)
        .filter(
            User.role == UserRole.MODERATOR,
            User.assigned_to_admin_id == admin_id,
        )
        .count()
    )


def promote_to_moderator(db: Session, target: User, current_user: User) -> User:
    """Promote ``target`` to moderator (SRS 1F.3.3 / 1F.4).

    A Secondary Administrator's promotions are assigned to them and capped by
    their effective limit; the eleventh raises MODERATOR_LIMIT_REACHED. The
    Permanent Administrator promotes without limit (unassigned).
    """

    from ..core.api_errors import ApiError, ErrorCode

    if getattr(target, "permanent", False):
        raise AdminServiceError("cannot_modify_permanent_admin")

    previous_role = role_to_string(target.role)
    assigned_to = None
    if effective_role(current_user) not in {UserRole.ADMIN, UserRole.PERMANENT}:
        # A Secondary Administrator: enforce the per-person cap on their group.
        current_count = count_moderators_for(db, current_user.id)
        limit = effective_moderator_limit(current_user)
        if current_count >= limit:
            raise ApiError(
                ErrorCode.MODERATOR_LIMIT_REACHED,
                f"Moderator limit reached ({limit}). Demote one to free a slot.",
                details={"limit": limit, "current": current_count},
            )
        assigned_to = current_user.id

    target.role = UserRole.MODERATOR
    target.assigned_to_admin_id = assigned_to
    db.commit()
    log_role_change(
        db,
        actor=current_user,
        target=target,
        action="admin.promote",
        method="promote-moderator",
        from_role=previous_role,
        to_role="moderator",
    )
    return target


def _assert_moderator_in_scope(current_user: User | None, target: User) -> None:
    """A Secondary Administrator may only act on moderators assigned to them."""

    from ..core.api_errors import ApiError, ErrorCode

    if effective_role(current_user) in {UserRole.ADMIN, UserRole.PERMANENT}:
        return
    if target.assigned_to_admin_id != getattr(current_user, "id", None):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "You can only demote moderators assigned to you.",
            details={"reason": "out_of_scope"},
        )


def demote_moderator(db: Session, target: User, current_user: User) -> User:
    """Demote a moderator to registered user (SRS 1F.3.1 / 1F.2.2).

    The Permanent Administrator can demote ANY moderator, including those
    assigned to a Secondary Administrator. A Secondary Administrator may only
    demote their own moderators.
    """

    if getattr(target, "permanent", False):
        raise AdminServiceError("cannot_modify_permanent_admin")
    if target.role != UserRole.MODERATOR:
        raise AdminServiceError("not_a_moderator")

    _assert_moderator_in_scope(current_user, target)

    previous_role = role_to_string(target.role)
    target.role = UserRole.USER
    target.assigned_to_admin_id = None
    db.commit()
    log_role_change(
        db,
        actor=current_user,
        target=target,
        action="admin.demote",
        method="demote-moderator",
        from_role=previous_role,
        to_role="user",
    )
    return target


def _is_admin_tier(role: UserRole | None) -> bool:
    """True when ``role`` is Secondary Administrator or above."""

    return role in {UserRole.SECONDARY, UserRole.ADMIN, UserRole.PERMANENT}


def assert_may_change_admin_tier(
    db: Session, actor: User | None, target: User, *, grant: bool
) -> None:
    """Enforce the model-wide rule behind every role-changing route (F-70).

    Only a principal holding ``promote_secondary`` / ``demote_secondary`` may
    grant or revoke the Secondary Administrator tier — those two capabilities
    default to the Permanent/Main Administrator only (see
    ``core.permissions._CATALOGUE``).

    The gate lives here, not on a single route, because four endpoints reach
    the same power through three different dependencies:
    ``/admin/promote-secondary`` and ``/admin/demote-secondary`` gate on the
    permission, while ``/admin/promote/{id}``, ``/admin/demote/{id}`` and
    both ``*-by-email`` siblings gated only on ``require_admin_user``
    ("secondary admin *or higher*") — so a Secondary Administrator could
    promote peers and demote other admins through the by-id/by-email routes.
    Enforcing the invariant at the mutation point means a future route
    cannot re-open the hole by picking the weaker dependency.
    """

    # Import locally: permissions_service imports models, and admin_service is
    # imported from the routers that permissions_service's callers also touch.
    from .permissions_service import has_permission

    if actor is None:
        raise AdminServiceError("insufficient_privileges")

    permission = "promote_secondary" if grant else "demote_secondary"
    if not has_permission(db, actor, permission):
        raise AdminServiceError("insufficient_privileges")


def promote_user_to_secondary(db: Session, user: User, current_user: User) -> User:
    assert_may_change_admin_tier(db, current_user, user, grant=True)
    previous_role = role_to_string(user.role)
    user.is_secondary_admin = True
    if not getattr(user, "is_main_admin", False) and getattr(
        user, "role", None
    ) not in {
        UserRole.ADMIN,
        UserRole.PERMANENT,
    }:
        user.role = UserRole.SECONDARY

    db.commit()
    log_role_change(
        db,
        actor=current_user,
        target=user,
        action="admin.promote",
        method="promote-secondary",
        from_role=previous_role,
        to_role="secondary_admin",
    )
    return user


def demote_user_from_secondary(db: Session, user: User, current_user: User) -> User:
    assert_may_change_admin_tier(db, current_user, user, grant=False)
    if getattr(user, "is_main_admin", False):
        raise AdminServiceError("Cannot demote the main admin with this action.")

    previous_role = role_to_string(user.role)
    user.is_secondary_admin = False
    if getattr(user, "role", None) == UserRole.SECONDARY:
        user.role = UserRole.USER

    db.commit()
    log_role_change(
        db,
        actor=current_user,
        target=user,
        action="admin.demote",
        method="demote-secondary",
        from_role=previous_role,
        to_role="user",
    )
    return user


def demote_user_from_main(db: Session, user: User, current_user: User) -> User:
    if getattr(current_user, "id", None) == getattr(user, "id", None):
        raise AdminServiceError("Main admin cannot demote themselves.")

    if getattr(user, "permanent", False):
        # Mirrors the protection in admin.py's set_user_permissions: refuse
        # outright rather than flipping is_main_admin off while leaving role
        # untouched, which would desync the two fields.
        from ..core.api_errors import ApiError, ErrorCode

        _alert_permanent_admin_tamper_attempt(current_user, user, "demote")
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "The Permanent Administrator cannot be demoted.",
            details={"reason": "permanent_admin_immutable"},
        )

    if not getattr(user, "is_main_admin", False):
        raise AdminServiceError("Target user is not the main admin.")

    previous_role = role_to_string(user.role)
    user.is_main_admin = False
    if (not getattr(user, "is_secondary_admin", False)) and getattr(
        user, "role", None
    ) == UserRole.ADMIN:
        user.role = UserRole.USER

    state = get_or_create_system_state(db, for_update=True)
    if state.main_admin_email_hash and getattr(user, "email_hash", None):
        if state.main_admin_email_hash == user.email_hash:
            state.main_admin_email = None

    settings = db.query(SystemSettings).first()
    if settings is not None and hasattr(settings, "main_admin_email"):
        hash_value = getattr(settings, "main_admin_email_hash", None)
        if (
            hash_value
            and getattr(user, "email_hash", None)
            and hash_value == user.email_hash
        ):
            setattr(settings, "main_admin_email", None)
            setattr(settings, "main_admin_email_hash", None)

    db.commit()

    log_role_change(
        db,
        actor=current_user,
        target=user,
        action="admin.demote",
        method="demote-main",
        from_role=previous_role,
        to_role=role_to_string(user.role),
    )
    return user


def promote_user_role(
    db: Session,
    user: User,
    requested_role: str,
    current_user: User,
    method: str = "by_id",
) -> User:
    if getattr(user, "permanent", False) and requested_role != "permanent_admin":
        raise AdminServiceError("cannot_modify_permanent_admin")

    # F-70: this route accepts role="secondary_admin", so it is a
    # promote-to-Secondary path and must clear the same gate its
    # /promote-secondary sibling does. role="user" here demotes, and demoting
    # someone who currently holds an admin tier needs demote_secondary.
    if requested_role == "secondary_admin":
        assert_may_change_admin_tier(db, current_user, user, grant=True)
    elif _is_admin_tier(effective_role(user)):
        assert_may_change_admin_tier(db, current_user, user, grant=False)

    previous_role = role_to_string(user.role)
    if requested_role == "secondary_admin":
        user.role = UserRole.SECONDARY
        user.is_secondary_admin = True
        action = "admin.promote"
    else:
        user.role = UserRole.USER
        user.is_secondary_admin = False
        action = "admin.demote"

    db.commit()
    log_role_change(
        db,
        actor=current_user,
        target=user,
        action=action,
        method=method,
        from_role=previous_role,
        to_role=requested_role,
    )
    return user


def demote_user_role(
    db: Session, user: User, current_user: User, method: str = "by_id"
) -> User:
    if getattr(user, "permanent", False):
        raise AdminServiceError("cannot_demote_permanent_admin")

    # F-70: demoting a peer admin is the Permanent Administrator's call.
    # Demoting an ordinary user stays available to every principal this route
    # already admits; demoting a moderator honours the same assignment scoping
    # the dedicated demote_moderator route enforces, so this generic route
    # cannot be used to step around it.
    if _is_admin_tier(effective_role(user)):
        assert_may_change_admin_tier(db, current_user, user, grant=False)
    elif getattr(user, "role", None) == UserRole.MODERATOR:
        _assert_moderator_in_scope(current_user, user)

    previous_role = role_to_string(user.role)
    user.role = UserRole.USER
    user.is_secondary_admin = False
    db.commit()
    log_role_change(
        db,
        actor=current_user,
        target=user,
        action="admin.demote",
        method=method,
        from_role=previous_role,
        to_role=UserRole.USER.value,
    )
    return user
