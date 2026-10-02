"""Admins, their seats and succession lines, and the sub-admin ceiling.

Owner's rules (2026-10-02): only the owner makes, removes or restricts an Admin,
shares the sub-admin seats between them and sets the ceiling on what a
sub-admin may ever hold. An Admin sees their own seat and keeps their own
succession line. Everything the owner gives needs the owner's authenticator
code; taking away does not.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...core.permissions import ALL_PERMISSIONS, OWNER_POWERS, is_owner
from ...dependencies.auth import require_main_admin_user
from ...dependencies.powers import require_power
from ...models import User
from ...services import admin_roles, admin_second_factor
from ...services.admin_service import log_role_change
from ...services.system_settings_service import get_or_create_system_settings
from ...utils.audit_logger import log_admin_action

router = APIRouter(prefix="/admin/roles", tags=["roles"])


def _owner_code(db: Session, owner: User, code: Optional[str], what: str) -> None:
    if not admin_second_factor.verify_user_code(db, owner, code or "", enabled_only=True):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            f"Enter the code from your authenticator app to {what}.",
            details={"reason": "code_required"},
        )


def _target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(ErrorCode.NOT_FOUND, "User not found.", details={"reason": "user_not_found"})
    return target


@router.get("/admins")
def list_admins(
    db: Session = Depends(get_db), user: User = Depends(require_power("manage_roles"))
) -> Dict[str, Any]:
    """The owner sees every Admin; an Admin sees only their own seat."""

    return admin_roles.overview(db, user)


class PromoteAdminPayload(BaseModel):
    user_id: int
    code: Optional[str] = Field(default=None, max_length=12)


@router.post("/admins")
def make_admin(
    payload: PromoteAdminPayload,
    db: Session = Depends(get_db),
    owner: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Make a sub-admin an Admin (at most two). Needs the owner's code."""

    _owner_code(db, owner, payload.code, "make someone an Admin")
    target = _target(db, payload.user_id)
    admin_roles.promote_to_admin(db, owner, target)
    db.commit()
    log_role_change(
        db, actor=owner, target=target, action="admin.promote", method="promote-admin",
        from_role="secondary_admin", to_role="co_admin",
    )
    return admin_roles.overview(db, owner)


class DemoteAdminPayload(BaseModel):
    to: str = Field(default="user", pattern="^(user|sub_admin)$")


@router.post("/admins/{user_id}/demote")
def remove_admin(
    user_id: int,
    payload: DemoteAdminPayload,
    db: Session = Depends(get_db),
    owner: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Take an Admin's seat away: they become a user or a sub-admin."""

    target = _target(db, user_id)
    admin_roles.demote_admin(db, owner, target, payload.to)
    db.commit()
    log_role_change(
        db, actor=owner, target=target, action="admin.demote", method="demote-admin",
        from_role="co_admin", to_role="secondary_admin" if payload.to == "sub_admin" else "user",
    )
    return admin_roles.overview(db, owner)


class QuotaPayload(BaseModel):
    quota: int = Field(..., ge=0, le=admin_roles.SUB_ADMIN_POOL)


@router.put("/admins/{user_id}/quota")
def set_quota(
    user_id: int,
    payload: QuotaPayload,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """How many sub-admins this Admin may have appointed at once."""

    target = _target(db, user_id)
    admin_roles.set_quota(db, target, payload.quota)
    db.commit()
    log_admin_action(
        db, request, owner, "ROLES_ADMIN_QUOTA", "user", str(user_id), "success", new_value=str(payload.quota)
    )
    return admin_roles.overview(db, owner)


class SuccessorsPayload(BaseModel):
    successor_ids: List[int] = Field(default_factory=list, max_length=admin_roles.MAX_LINE)


@router.put("/admins/{user_id}/successors")
def set_successors(
    user_id: int,
    payload: SuccessorsPayload,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_power("manage_roles")),
) -> Dict[str, Any]:
    """An Admin names up to two sub-admins, in order, to take their seat; the
    owner can set any Admin's line."""

    if not is_owner(actor) and actor.id != user_id:
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "You can only change your own succession line.",
            details={"reason": "not_your_line"},
        )
    target = _target(db, user_id)
    admin_roles.set_line(db, target, payload.successor_ids)
    db.commit()
    log_admin_action(
        db, request, actor, "ROLES_ADMIN_SUCCESSORS", "user", str(user_id), "success",
        new_value=",".join(str(i) for i in payload.successor_ids),
    )
    return admin_roles.overview(db, actor)


class HandOverPayload(BaseModel):
    successor_id: Optional[int] = None
    code: Optional[str] = Field(default=None, max_length=12)


@router.post("/admins/{user_id}/hand-over")
def hand_over_seat(
    user_id: int,
    payload: HandOverPayload,
    db: Session = Depends(get_db),
    owner: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Give an Admin's seat to a successor now, without waiting for the idle
    period. With no ``successor_id`` the first eligible person in the Admin's
    line takes it; the owner can also name any sub-admin."""

    _owner_code(db, owner, payload.code, "hand an Admin seat over")
    old = _target(db, user_id)
    if payload.successor_id is not None:
        successor: Optional[User] = _target(db, payload.successor_id)
    else:
        successor = admin_roles.first_eligible(db, old)
    if successor is None:
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Nobody in this Admin's succession line can take the seat. Pick a sub-admin.",
            details={"reason": "no_eligible_successor"},
        )
    event = admin_roles.hand_over(db, owner, old, successor, reason="owner")
    db.commit()
    log_role_change(
        db, actor=owner, target=successor, action="admin.promote", method="hand-over",
        from_role="secondary_admin", to_role="co_admin", extra={"replaced": event["demoted"]},
    )
    log_role_change(
        db, actor=owner, target=old, action="admin.demote", method="hand-over",
        from_role="co_admin", to_role="user", extra={"replaced_by": event["promoted"]},
    )
    return admin_roles.overview(db, owner)


# --------------------------------------------------------------------------
# The ceiling on what a sub-admin may ever hold
# --------------------------------------------------------------------------


class LimitsPayload(BaseModel):
    blocked: List[str] = Field(default_factory=list)
    code: Optional[str] = Field(default=None, max_length=12)


def _limits(db: Session) -> Dict[str, Any]:
    row = get_or_create_system_settings(db)
    return {
        "blocked": sorted(row.sub_admin_blocked_permissions or []),
        # Site-owner powers are always out of a sub-admin's reach; listed so the page can say so.
        "always_blocked": sorted(OWNER_POWERS),
    }


@router.get("/sub-admin-limits")
def get_limits(db: Session = Depends(get_db), _: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    return _limits(db)


@router.put("/sub-admin-limits")
def save_limits(
    payload: LimitsPayload,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """Powers no sub-admin can hold, even if an Admin tries to give them."""

    _owner_code(db, owner, payload.code, "change what sub-admins may hold")
    unknown = sorted(set(payload.blocked) - set(ALL_PERMISSIONS))
    if unknown:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, f"Unknown permission: {unknown[0]}.", field="blocked"
        )
    row = get_or_create_system_settings(db)
    row.sub_admin_blocked_permissions = sorted(set(payload.blocked) - OWNER_POWERS)
    db.commit()
    log_admin_action(
        db, request, owner, "ROLES_SUB_ADMIN_LIMITS", "roles", "sub-admin-limits", "success",
        new_value=",".join(row.sub_admin_blocked_permissions),
    )
    return _limits(db)


__all__ = ["router"]
