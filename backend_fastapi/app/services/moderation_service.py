"""Moderator actions against a user's community participation (SRS 1F.4.1).

Distinct from account suspension/ban (``is_active``, User Administration):
these actions only restrict community participation (posting comments)
while leaving the account itself intact.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models import User
from .audit_service import audit_service
from .notification_service import notify_async

MAX_TIMEOUT_HOURS = 24 * 30  # 30 days -- a generous outer bound, not a spec number


def is_blocked(user: User) -> bool:
    return getattr(user, "community_blocked_at", None) is not None


def is_timed_out(user: User) -> bool:
    until = getattr(user, "community_timeout_until", None)
    return until is not None and until > datetime.utcnow()


def assert_can_participate(user: User) -> None:
    """Raise if ``user`` is currently blocked or timed out from posting."""

    if is_blocked(user):
        raise ApiError(
            ErrorCode.COMMUNITY_BLOCKED,
            "You have been blocked from posting comments.",
            details={"reason": user.community_blocked_reason},
        )
    if is_timed_out(user):
        raise ApiError(
            ErrorCode.COMMUNITY_TIMED_OUT,
            "You are temporarily timed out from posting comments.",
            details={
                "reason": user.community_timeout_reason,
                "until": user.community_timeout_until.isoformat(),
            },
        )


def _chain_of_command(moderator: User, target: User, what: str) -> None:
    """Moderate only people of a lower tier: sub-admins act on users, Admins on
    sub-admins and users, nobody on the owner."""

    from .permissions_service import assert_may_act_on

    assert_may_act_on(moderator, target, what)


def block_user(db: Session, *, moderator: User, target: User, reason: str) -> User:
    _chain_of_command(moderator, target, "block")
    target.community_blocked_at = datetime.utcnow()
    target.community_blocked_reason = reason
    target.community_blocked_by_id = moderator.id
    db.commit()
    db.refresh(target)

    audit_service.log_action(
        moderator.id,
        "community.block_user",
        metadata={"target_user_id": target.id, "reason": reason},
    )
    notify_async(
        type="moderation.action",
        user_id=target.id,
        title="You have been blocked from commenting",
        body=reason or "A moderator has blocked you from posting comments.",
        data={"action": "block", "reason": reason},
    )
    return target


def unblock_user(db: Session, *, moderator: User, target: User) -> User:
    _chain_of_command(moderator, target, "unblock")
    target.community_blocked_at = None
    target.community_blocked_reason = None
    target.community_blocked_by_id = None
    db.commit()
    db.refresh(target)

    audit_service.log_action(
        moderator.id, "community.unblock_user", metadata={"target_user_id": target.id}
    )
    notify_async(
        type="moderation.action",
        user_id=target.id,
        title="Your commenting privileges have been restored",
        body="A moderator has lifted your community block.",
        data={"action": "unblock"},
    )
    return target


def timeout_user(
    db: Session, *, moderator: User, target: User, hours: int, reason: str
) -> User:
    _chain_of_command(moderator, target, "time out")
    if hours <= 0 or hours > MAX_TIMEOUT_HOURS:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"Timeout duration must be between 1 and {MAX_TIMEOUT_HOURS} hours.",
        )
    target.community_timeout_until = datetime.utcnow() + timedelta(hours=hours)
    target.community_timeout_reason = reason
    db.commit()
    db.refresh(target)

    audit_service.log_action(
        moderator.id,
        "community.timeout_user",
        metadata={"target_user_id": target.id, "hours": hours, "reason": reason},
    )
    notify_async(
        type="moderation.action",
        user_id=target.id,
        title=f"You have been timed out from commenting for {hours} hour(s)",
        body=reason or "A moderator has temporarily restricted your commenting.",
        data={
            "action": "timeout",
            "hours": hours,
            "reason": reason,
            "until": target.community_timeout_until.isoformat(),
        },
    )
    return target


__all__ = [
    "is_blocked",
    "is_timed_out",
    "assert_can_participate",
    "block_user",
    "unblock_user",
    "timeout_user",
]
