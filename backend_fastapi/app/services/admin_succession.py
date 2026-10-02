"""Deputies' activity and automatic succession (owner's rules, 2026-10-02).

* Every day an admin opens the admin panel or uses a delegated power, one row
  goes into ``admin_activity_days`` (``record_activity``).
* When the owner has switched succession on (owner only), a daily job checks
  each deputy -- a sub-admin holding site-owner powers. A deputy idle for more
  than ``succession_inactive_days`` (default 60) is demoted to a user and loses
  every power. The most active eligible sub-admin inherits exactly the
  site-owner powers the idle deputy had.

Guardrails against abuse:

* Only the owner can switch it on or off or change the idle period, and doing
  so needs the owner's authenticator code. Deputies can't touch it.
* The owner is never demoted, and there are never more than ``MAX_DEPUTIES``.
* The idle clock starts no earlier than when succession was switched on and
  when the deputy received their powers, so switching it on never demotes
  anybody at once.
* A successor must have been an admin for ``MIN_TENURE_DAYS``, been active on
  ``MIN_ACTIVE_DAYS`` of the last ``WINDOW_DAYS`` days, done admin work on
  ``MIN_WORK_DAYS`` of them, have an authenticator, and an active account.
  Activity is recorded by the server, never reported by the browser.
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

from ..core.permissions import MAX_DEPUTIES, OWNER_POWERS, effective_role
from ..models import AdminActivityDay, AdminAuditLog, PermissionOverride, User, UserRole

logger = structlog.get_logger("backend_fastapi.succession")

WINDOW_DAYS = 30
MIN_ACTIVE_DAYS = 20
MIN_WORK_DAYS = 10
MIN_TENURE_DAYS = 30
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


def _first_active(db: Session, user_id: int) -> Optional[date]:
    return db.query(func.min(AdminActivityDay.day)).filter(AdminActivityDay.user_id == user_id).scalar()


def stats(db: Session, user: User, today: date) -> Dict[str, Any]:
    since = today - timedelta(days=WINDOW_DAYS - 1)
    active_days = (
        db.query(func.count(AdminActivityDay.day))
        .filter(AdminActivityDay.user_id == user.id, AdminActivityDay.day >= since)
        .scalar()
        or 0
    )
    work_days = (
        db.query(func.count(func.distinct(func.date(AdminAuditLog.timestamp))))
        .filter(AdminAuditLog.user_id == user.id, AdminAuditLog.timestamp >= datetime.combine(since, datetime.min.time()))
        .scalar()
        or 0
    )
    first = _first_active(db, user.id)
    return {
        "user_id": user.id,
        "name": user.name or user.username,
        "active_days": int(active_days),
        "work_days": int(work_days),
        "admin_for_days": (today - first).days if first else 0,
        "last_active": (last_active(db, user.id) or None),
        "authenticator": bool(user.totp_enabled),
    }


def _eligible(info: Dict[str, Any], user: User) -> List[str]:
    reasons = []
    if not user.is_active:
        reasons.append("account not active")
    if not info["authenticator"]:
        reasons.append("no authenticator")
    if info["admin_for_days"] < MIN_TENURE_DAYS:
        reasons.append(f"admin for {info['admin_for_days']} of {MIN_TENURE_DAYS} days")
    if info["active_days"] < MIN_ACTIVE_DAYS:
        reasons.append(f"active {info['active_days']} of {MIN_ACTIVE_DAYS} days")
    if info["work_days"] < MIN_WORK_DAYS:
        reasons.append(f"worked {info['work_days']} of {MIN_WORK_DAYS} days")
    return reasons


def candidates(db: Session, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Sub-admins who aren't deputies, best first, with why they can't be picked yet."""

    from .permissions_service import deputy_ids

    today = today or datetime.utcnow().date()
    deputies = deputy_ids(db)
    out = []
    for user in db.query(User).filter(User.role == UserRole.SECONDARY).all():
        if user.id in deputies:
            continue
        info = stats(db, user, today)
        info["blocked_by"] = _eligible(info, user)
        out.append(info)
    out.sort(key=lambda i: (not i["blocked_by"], i["active_days"], i["work_days"], i["last_active"] or date.min), reverse=True)
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
        "rules": {
            "max_deputies": MAX_DEPUTIES,
            "window_days": WINDOW_DAYS,
            "min_active_days": MIN_ACTIVE_DAYS,
            "min_work_days": MIN_WORK_DAYS,
            "min_tenure_days": MIN_TENURE_DAYS,
        },
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


def _granted_owner_powers(db: Session, user_id: int) -> List[PermissionOverride]:
    return (
        db.query(PermissionOverride)
        .filter(
            PermissionOverride.user_id == user_id,
            PermissionOverride.permission.in_(sorted(OWNER_POWERS)),
            PermissionOverride.state == "granted",
        )
        .all()
    )


def deputies_overview(db: Session, today: Optional[date] = None) -> List[Dict[str, Any]]:
    from .permissions_service import deputy_ids

    today = today or datetime.utcnow().date()
    cfg = config(db)
    out = []
    for user_id in sorted(deputy_ids(db)):
        user = db.get(User, user_id)
        grants = _granted_owner_powers(db, user_id)
        idle_from = _idle_since(db, user_id, grants)
        out.append(
            {
                "user_id": user_id,
                "name": user.name or user.username,
                "powers": sorted(g.permission for g in grants),
                "last_active": last_active(db, user_id),
                "idle_days": (today - idle_from).days if idle_from else None,
                "days_left": (cfg["inactive_days"] - (today - idle_from).days) if idle_from and cfg["enabled"] else None,
            }
        )
    return out


def _idle_since(db: Session, user_id: int, grants: List[PermissionOverride]) -> Optional[date]:
    row = _settings(db)
    points = [last_active(db, user_id)]
    points += [(g.updated_at or g.created_at).date() for g in grants if (g.updated_at or g.created_at)]
    if row.succession_enabled_at:
        points.append(row.succession_enabled_at.date())
    points = [p for p in points if p is not None]
    return max(points) if points else None


def _audit(db: Session, action: str, metadata: Dict[str, Any]) -> None:
    db.add(AdminAuditLog(user_id=None, operator="succession", action=action, metadata_json=metadata))


def _notify(title: str, body: str, data: Dict[str, Any]) -> None:
    from . import notification_service

    notification_service.notify_async(
        type="roles.succession", title=title, body=body, data=data, category="security",
        target_type="user", target_id=data.get("demoted") or data.get("promoted"),
    )


def run(db: Session, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Demote idle deputies and hand their powers on. Returns what changed."""

    from .permissions_service import set_override

    today = today or datetime.utcnow().date()
    cfg = config(db)
    if not cfg["enabled"]:
        return []
    events: List[Dict[str, Any]] = []
    for deputy in deputies_overview(db, today):
        if deputy["idle_days"] is None or deputy["idle_days"] <= cfg["inactive_days"]:
            continue
        user = db.get(User, deputy["user_id"])
        if user is None or effective_role(user) != UserRole.SECONDARY:
            continue  # never the owner
        powers = deputy["powers"]

        # Demote: every site-owner power and every other override goes.
        db.query(PermissionOverride).filter(PermissionOverride.user_id == user.id).delete(synchronize_session=False)
        user.role = UserRole.USER
        user.is_secondary_admin = False
        db.flush()
        event: Dict[str, Any] = {"demoted": user.id, "idle_days": deputy["idle_days"], "powers": powers}

        pick = next((c for c in candidates(db, today) if not c["blocked_by"]), None)
        if pick:
            successor = db.get(User, pick["user_id"])
            for key in powers:
                set_override(db, successor, key, "granted", actor_id=None, by_owner=True)
            event["promoted"] = successor.id
        _audit(db, "roles.succession", event)
        db.commit()
        logger.warning("succession_applied", **event)

        demoted_name = deputy["name"] or f"user #{user.id}"
        if pick:
            body = (
                f"{demoted_name} was idle for {deputy['idle_days']} days and is now a user. "
                f"{pick['name'] or 'Sub-admin #%s' % pick['user_id']} received their site-owner powers "
                f"({', '.join(powers)}). Undo it in Role Management if this is wrong."
            )
        else:
            body = (
                f"{demoted_name} was idle for {deputy['idle_days']} days and is now a user. No sub-admin met "
                "the rules to take over, so their site-owner powers went back to you."
            )
        _notify("Deputy replaced automatically", body, event)
        events.append(event)
    return events


__all__ = [
    "candidates",
    "config",
    "deputies_overview",
    "last_active",
    "record_activity",
    "run",
    "set_config",
    "stats",
]
