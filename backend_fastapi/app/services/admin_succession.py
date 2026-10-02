"""Admins' activity and automatic succession (owner's rules, 2026-10-02).

* Every day an admin opens the admin panel or uses a delegated power, one row
  goes into ``admin_activity_days`` (``record_activity``).
* When the owner has switched succession on (owner only), a daily job checks
  each Admin. An Admin idle for more than ``succession_inactive_days``
  (default 60, "two months") becomes a user, and the first eligible sub-admin in
  their succession line (``services.admin_roles``) takes the seat, inheriting
  it as it stands. The owner can hand a seat over at any time, without waiting.

Guardrails against abuse:

* Only the owner can switch it on or off or change the idle period, and doing
  so needs the owner's authenticator code. Admins can't touch it.
* The owner is never demoted: only an Admin can fall idle out of a seat.
* The idle clock starts no earlier than when succession was switched on and
  when the Admin took the seat, so switching it on never demotes anybody at
  once. Activity is recorded by the server, never reported by the browser.
* A successor must still be a sub-admin with an active account and an
  authenticator when their turn comes.
* Every automatic change is written to the audit log and sent to the owner's
  notifications; the owner can undo it in Role Management.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.permissions import MAX_ADMINS, effective_role
from ..models import AdminActivityDay, AdminAuditLog, User, UserRole

logger = structlog.get_logger("backend_fastapi.succession")

WINDOW_DAYS = 30
MIN_INACTIVE_DAYS, MAX_INACTIVE_DAYS = 30, 365


# --------------------------------------------------------------------------
# Activity
# --------------------------------------------------------------------------


def record_activity(db: Session, user: User, today: Optional[date] = None) -> None:
    """Mark ``user`` active today (admins only; at most one row a day)."""

    if effective_role(user) == UserRole.USER:
        return
    today = today or datetime.utcnow().date()
    exists = (
        db.query(AdminActivityDay.user_id)
        .filter(AdminActivityDay.user_id == user.id, AdminActivityDay.day == today)
        .first()
    )
    if exists:
        return
    try:
        with db.begin_nested():
            db.add(AdminActivityDay(user_id=user.id, day=today))
        db.commit()
    except IntegrityError:
        db.rollback()


def last_active(db: Session, user_id: int) -> Optional[date]:
    day = db.query(func.max(AdminActivityDay.day)).filter(AdminActivityDay.user_id == user_id).scalar()
    worked = db.query(func.max(AdminAuditLog.timestamp)).filter(AdminAuditLog.user_id == user_id).scalar()
    candidates = [d for d in (day, worked.date() if worked else None) if d is not None]
    return max(candidates) if candidates else None


def stats(db: Session, user: User, today: date) -> Dict[str, Any]:
    since = today - timedelta(days=WINDOW_DAYS - 1)
    active_days = (
        db.query(func.count(AdminActivityDay.day))
        .filter(AdminActivityDay.user_id == user.id, AdminActivityDay.day >= since)
        .scalar()
        or 0
    )
    return {
        "user_id": user.id,
        "name": user.name or user.username,
        "active_days": int(active_days),
        "last_active": last_active(db, user.id),
        "authenticator": bool(user.totp_enabled),
    }


def candidates(db: Session, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Sub-admins, most active first, with why they can't take a seat yet."""

    from .admin_roles import eligibility

    today = today or datetime.utcnow().date()
    out = []
    for user in db.query(User).filter(User.role == UserRole.SECONDARY).all():
        info = stats(db, user, today)
        info["blocked_by"] = eligibility(user)
        out.append(info)
    out.sort(key=lambda i: (not i["blocked_by"], i["active_days"], i["last_active"] or date.min), reverse=True)
    return out


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


def _settings(db: Session):
    from .system_settings_service import get_or_create_system_settings

    return get_or_create_system_settings(db)


def config(db: Session) -> Dict[str, Any]:
    row = _settings(db)
    return {
        "enabled": bool(row.succession_enabled),
        "inactive_days": int(row.succession_inactive_days or 60),
        "enabled_at": row.succession_enabled_at.isoformat() if row.succession_enabled_at else None,
        "rules": {"max_admins": MAX_ADMINS, "window_days": WINDOW_DAYS},
    }


def set_config(db: Session, *, enabled: bool, inactive_days: int) -> Dict[str, Any]:
    if not MIN_INACTIVE_DAYS <= inactive_days <= MAX_INACTIVE_DAYS:
        raise ValueError(f"Idle period must be {MIN_INACTIVE_DAYS}-{MAX_INACTIVE_DAYS} days.")
    row = _settings(db)
    if enabled and not row.succession_enabled:
        row.succession_enabled_at = datetime.utcnow()
    row.succession_enabled = enabled
    row.succession_inactive_days = inactive_days
    db.commit()
    return config(db)


# --------------------------------------------------------------------------
# The daily check
# --------------------------------------------------------------------------


def _idle_since(db: Session, admin: User) -> Optional[date]:
    row = _settings(db)
    points = [last_active(db, admin.id)]
    if admin.admin_since:
        points.append(admin.admin_since.date())
    if row.succession_enabled_at:
        points.append(row.succession_enabled_at.date())
    points = [p for p in points if p is not None]
    return max(points) if points else None


def idle_info(db: Session, admin: User, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or datetime.utcnow().date()
    cfg = config(db)
    idle_from = _idle_since(db, admin)
    idle_days = (today - idle_from).days if idle_from else None
    return {
        "last_active": last_active(db, admin.id),
        "idle_days": idle_days,
        "days_left": (cfg["inactive_days"] - idle_days) if idle_days is not None and cfg["enabled"] else None,
    }


def admins_overview(db: Session, today: Optional[date] = None) -> List[Dict[str, Any]]:
    from .admin_roles import admin_row, admins

    return [admin_row(db, admin) for admin in admins(db)]


def _audit(db: Session, action: str, metadata: Dict[str, Any]) -> None:
    db.add(AdminAuditLog(user_id=None, operator="succession", action=action, metadata_json=metadata))


def _notify(title: str, body: str, data: Dict[str, Any]) -> None:
    from . import notification_service

    notification_service.notify_async(
        type="roles.succession", title=title, body=body, data=data, category="security",
        target_type="user", target_id=data.get("demoted") or data.get("promoted"),
    )


def run(db: Session, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Replace Admins idle too long and hand their seats on. Returns what changed."""

    from .admin_roles import admins, demote_admin, first_eligible, hand_over

    today = today or datetime.utcnow().date()
    cfg = config(db)
    if not cfg["enabled"]:
        return []
    events: List[Dict[str, Any]] = []
    for admin in admins(db):
        if effective_role(admin) != UserRole.CO_ADMIN:
            continue  # never the owner
        idle_from = _idle_since(db, admin)
        idle_days = (today - idle_from).days if idle_from else None
        if idle_days is None or idle_days <= cfg["inactive_days"]:
            continue

        name = admin.name or admin.username or f"user #{admin.id}"
        pick = first_eligible(db, admin)
        if pick is not None:
            event = hand_over(db, None, admin, pick, reason="idle")
            successor_name = pick.name or pick.username or f"user #{pick.id}"
            body = (
                f"{name} was idle for {idle_days} days and is now a user. {successor_name} took the Admin seat "
                "from their succession line and inherits it as it was. Undo it in Role Management if this is wrong."
            )
        else:
            demote_admin(db, None, admin, "user")
            event = {"demoted": admin.id, "reason": "idle"}
            body = (
                f"{name} was idle for {idle_days} days and is now a user. Nobody in their succession line could "
                "take the seat, so it is open: appoint a new Admin in Role Management."
            )
        event["idle_days"] = idle_days
        _audit(db, "roles.succession", event)
        db.commit()
        logger.warning("succession_applied", **event)
        _notify("Admin replaced automatically", body, event)
        events.append(event)
    return events


__all__ = [
    "admins_overview",
    "candidates",
    "config",
    "idle_info",
    "last_active",
    "record_activity",
    "run",
    "set_config",
    "stats",
]
