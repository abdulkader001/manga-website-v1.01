"""Admin seats, the sub-admin pool and succession lines (owner's rules, 2026-10-02).

* There are at most ``MAX_ADMINS`` Admins. Only the owner makes or removes
  one (with the owner's authenticator code, checked by the route), and a new
  Admin must already be a sub-admin with an authenticator.
* The owner shares ``SUB_ADMIN_POOL`` sub-admin seats between the Admins. An
  Admin appoints sub-admins only while they have seats left; the owner's own
  appointments are unlimited.
* Every Admin keeps a succession line of up to two sub-admins. When the seat
  falls idle (``admin_succession.run``) or the owner hands it over, the first
  eligible person in the line becomes the Admin and **inherits the seat as it
  is**: the owner's restrictions on the old Admin, their seat quota and the
  sub-admins they appointed. The old Admin becomes a user.

Everything here changes rows only; the routes check who is allowed to ask.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.permissions import MAX_ADMINS, SUB_ADMIN_POOL, effective_role, rank
from ..models import AdminAuditLog, AdminSuccessor, PermissionOverride, User, UserRole

MAX_LINE = 2


def _refuse(message: str, reason: str, **details: Any) -> ApiError:
    return ApiError(ErrorCode.FORBIDDEN, message, details={"reason": reason, **details})


def _name(user: User) -> str:
    return user.name or user.username or f"user #{user.id}"


def _audit(db: Session, user_id: Optional[int], action: str, metadata: Dict[str, Any], operator: str = "admin_router") -> None:
    db.add(AdminAuditLog(user_id=user_id, operator=operator, action=action, metadata_json=metadata))


def admins(db: Session) -> List[User]:
    return db.query(User).filter(User.role == UserRole.CO_ADMIN).order_by(User.id.asc()).all()


# --------------------------------------------------------------------------
# The sub-admin pool
# --------------------------------------------------------------------------


def quotas(db: Session) -> Dict[int, int]:
    """Seats each Admin may fill. Explicit quotas stand; Admins without one
    split what is left of the pool equally."""

    people = admins(db)
    explicit = sum(a.sub_admin_quota for a in people if a.sub_admin_quota is not None)
    unset = [a for a in people if a.sub_admin_quota is None]
    share = max(0, SUB_ADMIN_POOL - explicit) // len(unset) if unset else 0
    return {a.id: (a.sub_admin_quota if a.sub_admin_quota is not None else share) for a in people}


def appointed_count(db: Session, admin_id: int) -> int:
    return (
        db.query(func.count(User.id))
        .filter(User.appointed_by == admin_id, User.role == UserRole.SECONDARY)
        .scalar()
        or 0
    )


def seats_left(db: Session, admin: User) -> int:
    return max(0, quotas(db).get(admin.id, 0) - appointed_count(db, admin.id))


def set_quota(db: Session, admin: User, quota: int) -> None:
    if effective_role(admin) != UserRole.CO_ADMIN:
        raise _refuse("Seats are set for Admins only.", "not_an_admin")
    if not 0 <= quota <= SUB_ADMIN_POOL:
        raise ApiError(ErrorCode.VALIDATION_FAILED, f"Seats must be 0-{SUB_ADMIN_POOL}.", field="quota")
    others = sum(a.sub_admin_quota or 0 for a in admins(db) if a.id != admin.id and a.sub_admin_quota is not None)
    if others + quota > SUB_ADMIN_POOL:
        raise _refuse(
            f"The Admins can share {SUB_ADMIN_POOL} seats in all; {SUB_ADMIN_POOL - others} are left for this one.",
            "pool_exceeded",
            pool=SUB_ADMIN_POOL,
            available=SUB_ADMIN_POOL - others,
        )
    admin.sub_admin_quota = quota
    db.flush()


def claim_seat(db: Session, actor: User, target: User) -> None:
    """Record who appoints ``target`` as a sub-admin: an Admin spends one of
    their seats (refused when none is left); the owner's appointments are free."""

    if effective_role(actor) == UserRole.CO_ADMIN:
        if seats_left(db, actor) <= 0:
            raise _refuse(
                "You have no sub-admin seats left. Remove one, or ask the site owner for more.",
                "no_seats_left",
                quota=quotas(db).get(actor.id, 0),
            )
        target.appointed_by = actor.id
    else:
        target.appointed_by = None


# --------------------------------------------------------------------------
# Succession lines
# --------------------------------------------------------------------------


def eligibility(user: Optional[User]) -> List[str]:
    """Why ``user`` can't take an Admin seat right now (empty = they can)."""

    if user is None:
        return ["no longer exists"]
    reasons: List[str] = []
    if effective_role(user) != UserRole.SECONDARY:
        reasons.append("not a sub-admin any more")
    if not user.is_active:
        reasons.append("account not active")
    if not getattr(user, "totp_enabled", False):
        reasons.append("no authenticator")
    return reasons


def line(db: Session, admin_id: int) -> List[User]:
    rows = (
        db.query(AdminSuccessor)
        .filter(AdminSuccessor.admin_id == admin_id)
        .order_by(AdminSuccessor.position.asc())
        .all()
    )
    out = []
    for row in rows:
        user = db.get(User, row.successor_id)
        if user is not None:
            out.append(user)
    return out


def set_line(db: Session, admin: User, successor_ids: List[int]) -> List[User]:
    """Replace ``admin``'s succession line (up to two sub-admins, in order)."""

    if effective_role(admin) != UserRole.CO_ADMIN:
        raise _refuse("Only an Admin has a succession line.", "not_an_admin")
    ids = list(successor_ids)
    if len(ids) > MAX_LINE:
        raise ApiError(ErrorCode.VALIDATION_FAILED, f"A succession line holds at most {MAX_LINE} people.", field="successor_ids")
    if len(set(ids)) != len(ids):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Name each person once.", field="successor_ids")
    people: List[User] = []
    for uid in ids:
        person = db.get(User, uid)
        if person is None or person.id == admin.id or effective_role(person) != UserRole.SECONDARY:
            raise _refuse("Only a sub-admin can be in a succession line.", "not_a_sub_admin", user_id=uid)
        if not person.is_active:
            raise _refuse("That account isn't active.", "not_eligible", user_id=uid)
        people.append(person)
    db.query(AdminSuccessor).filter(AdminSuccessor.admin_id == admin.id).delete(synchronize_session=False)
    db.flush()
    for position, person in enumerate(people, start=1):
        db.add(AdminSuccessor(admin_id=admin.id, position=position, successor_id=person.id))
    db.flush()
    return people


def _leave_lines(db: Session, user_id: int) -> None:
    """Take ``user_id`` out of everybody's succession line (they stopped being a sub-admin)."""

    db.query(AdminSuccessor).filter(AdminSuccessor.successor_id == user_id).delete(synchronize_session=False)


def first_eligible(db: Session, admin: User) -> Optional[User]:
    return next((person for person in line(db, admin.id) if not eligibility(person)), None)


# --------------------------------------------------------------------------
# Making and removing Admins (owner only; the route checks the owner's code)
# --------------------------------------------------------------------------


def promote_to_admin(db: Session, actor: User, target: User) -> User:
    if effective_role(target) != UserRole.SECONDARY:
        raise _refuse("Only a sub-admin can become an Admin. Appoint them as a sub-admin first.", "not_a_sub_admin")
    if not target.is_active:
        raise _refuse("That account isn't active.", "not_eligible")
    if not getattr(target, "totp_enabled", False):
        raise _refuse(
            "This person must set up an authenticator app (Admin -> Security) before becoming an Admin.",
            "authenticator_required",
        )
    if len(admins(db)) >= MAX_ADMINS:
        raise _refuse(
            f"There can be only {MAX_ADMINS} Admins. Remove one first, or hand a seat over.",
            "admin_limit",
            limit=MAX_ADMINS,
        )
    # A fresh Admin starts from the Admin defaults, whatever their sub-admin toggles were.
    db.query(PermissionOverride).filter(PermissionOverride.user_id == target.id).delete(synchronize_session=False)
    _leave_lines(db, target.id)
    target.role = UserRole.CO_ADMIN
    target.is_secondary_admin = True
    target.admin_since = datetime.utcnow()
    target.appointed_by = None
    target.sub_admin_quota = None
    target.visible_admin_tabs = None
    target.powers_suspended = False
    db.flush()
    _audit(db, actor.id, "roles.admin_promoted", {"target_user_id": target.id})
    return target


def _release(db: Session, user: User, *, hand_appointees_to: Optional[int]) -> None:
    """An Admin leaves the seat: their line goes, their restrictions go, and
    the sub-admins they appointed pass to ``hand_appointees_to`` (or the owner)."""

    db.query(AdminSuccessor).filter(AdminSuccessor.admin_id == user.id).delete(synchronize_session=False)
    db.query(User).filter(User.appointed_by == user.id).update({"appointed_by": hand_appointees_to}, synchronize_session=False)
    db.query(PermissionOverride).filter(PermissionOverride.user_id == user.id).delete(synchronize_session=False)
    user.sub_admin_quota = None
    user.admin_since = None
    user.visible_admin_tabs = None
    user.powers_suspended = False


def demote_admin(db: Session, actor: Optional[User], target: User, to: str, *, hand_appointees_to: Optional[int] = None) -> User:
    """Take the Admin seat from ``target``: they become a user or a sub-admin."""

    if effective_role(target) != UserRole.CO_ADMIN:
        raise _refuse("That person isn't an Admin.", "not_an_admin")
    if to not in ("user", "sub_admin"):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "to must be 'user' or 'sub_admin'.", field="to")
    _release(db, target, hand_appointees_to=hand_appointees_to)
    target.appointed_by = None
    if to == "sub_admin":
        target.role = UserRole.SECONDARY
        target.is_secondary_admin = True
    else:
        target.role = UserRole.USER
        target.is_secondary_admin = False
        _leave_lines(db, target.id)
    db.flush()
    _audit(db, getattr(actor, "id", None), "roles.admin_demoted", {"target_user_id": target.id, "to": to})
    return target


def hand_over(db: Session, actor: Optional[User], old: User, successor: User, *, reason: str) -> Dict[str, Any]:
    """Give ``old``'s Admin seat to ``successor`` now. ``old`` becomes a user.

    The successor inherits the seat as it stands: the owner's restrictions on
    the old Admin, their seat quota, and the sub-admins they appointed.
    """

    if effective_role(old) != UserRole.CO_ADMIN:
        raise _refuse("That person isn't an Admin.", "not_an_admin")
    reasons = eligibility(successor)
    if reasons:
        raise _refuse("That person can't take the seat: " + ", ".join(reasons) + ".", "not_eligible", reasons=reasons)

    inherited = [(o.permission, o.state) for o in db.query(PermissionOverride).filter(PermissionOverride.user_id == old.id)]
    quota = old.sub_admin_quota
    tabs = old.visible_admin_tabs  # the owner's tab list and "powers off" pass on too
    powers_off = bool(old.powers_suspended)
    db.query(PermissionOverride).filter(PermissionOverride.user_id == successor.id).delete(synchronize_session=False)
    _leave_lines(db, successor.id)
    successor.role = UserRole.CO_ADMIN
    successor.is_secondary_admin = True
    successor.admin_since = datetime.utcnow()
    successor.appointed_by = None
    successor.sub_admin_quota = quota
    successor.visible_admin_tabs = tabs
    successor.powers_suspended = powers_off
    db.flush()
    for permission, state in inherited:
        db.add(PermissionOverride(user_id=successor.id, permission=permission, state=state, updated_by=getattr(actor, "id", None)))

    demote_admin(db, actor, old, "user", hand_appointees_to=successor.id)
    event = {"demoted": old.id, "promoted": successor.id, "reason": reason}
    _audit(
        db,
        getattr(actor, "id", None),
        "roles.admin_seat_handed_over",
        event,
        operator="succession" if actor is None else "admin_router",
    )
    return event


# --------------------------------------------------------------------------
# Overview for the Role Management page
# --------------------------------------------------------------------------


def person(user: User) -> Dict[str, Any]:
    return {"user_id": user.id, "name": _name(user)}


def admin_row(db: Session, admin: User) -> Dict[str, Any]:
    from .admin_succession import idle_info
    from .permissions_service import modified_count

    quota = quotas(db).get(admin.id, 0)
    used = appointed_count(db, admin.id)
    return {
        **person(admin),
        "authenticator": bool(getattr(admin, "totp_enabled", False)),
        "modified_count": modified_count(db, admin),
        "quota": quota,
        "quota_set": admin.sub_admin_quota is not None,
        "used": used,
        "left": max(0, quota - used),
        "line": [{**person(p), "blocked_by": eligibility(p)} for p in line(db, admin.id)],
        **idle_info(db, admin),
    }


def overview(db: Session, viewer: User) -> Dict[str, Any]:
    """Everything the page needs. The owner sees every Admin; an Admin sees
    only their own row."""

    owner = rank(viewer) >= 3
    rows = [admin_row(db, a) for a in admins(db) if owner or a.id == viewer.id]
    candidates = [
        {**person(u), "blocked_by": eligibility(u), "appointed_by": u.appointed_by}
        for u in db.query(User).filter(User.role == UserRole.SECONDARY).order_by(User.id.asc()).all()
    ]
    return {
        "max_admins": MAX_ADMINS,
        "pool": SUB_ADMIN_POOL,
        "pool_used": sum(quotas(db).values()),
        "admins": rows,
        "sub_admins": candidates,
    }


__all__ = [
    "admins",
    "appointed_count",
    "claim_seat",
    "demote_admin",
    "eligibility",
    "first_eligible",
    "hand_over",
    "line",
    "overview",
    "promote_to_admin",
    "quotas",
    "seats_left",
    "set_line",
    "set_quota",
]
