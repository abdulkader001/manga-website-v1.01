"""Role Management -> Tab access: which admin tabs each person sees.

Owner only, and **not delegable**: no permission opens these routes, so an Admin
can't change anyone's tabs, not even a sub-admin's (owner's rule, 2026-10-02).
The owner can also switch **all** of a person's powers off: the Admin or
sub-admin keeps the title and the seat (and the seat count), but the admin area
no longer answers them. Every change is audited.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core import admin_tabs
from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...core.permissions import effective_role
from ...dependencies.auth import require_main_admin_user
from ...models import User, UserRole
from ...utils.audit_logger import log_admin_action

router = APIRouter(prefix="/admin/roles/tab-access", tags=["roles"])


def _person(user: User) -> Dict[str, Any]:
    role = effective_role(user)
    return {
        "user_id": user.id,
        "name": user.name or user.username or f"user #{user.id}",
        "role": "admin" if role == UserRole.CO_ADMIN else "sub_admin",
        "tabs": user.visible_admin_tabs,
        "suspended": bool(user.powers_suspended),
        "authenticator": bool(getattr(user, "totp_enabled", False)),
    }


def _overview(db: Session) -> Dict[str, Any]:
    people = (
        db.query(User)
        .filter(User.role.in_([UserRole.CO_ADMIN, UserRole.SECONDARY]))
        .order_by(User.role.asc(), User.id.asc())
        .all()
    )
    return {
        "tabs": [t for t in admin_tabs.catalogue() if not t["owner_only"]],
        "people": [_person(u) for u in people],
    }


@router.get("")
def tab_access_overview(
    db: Session = Depends(get_db), _: User = Depends(require_main_admin_user)
) -> Dict[str, Any]:
    return _overview(db)


class TabAccessPayload(BaseModel):
    # None keeps "follow the person's permissions"; [] means no tab at all.
    tabs: Optional[List[str]] = Field(default=None, max_length=40)
    suspended: bool = False


@router.put("/{user_id}")
def set_tab_access(
    user_id: int,
    payload: TabAccessPayload,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(ErrorCode.NOT_FOUND, "User not found.", details={"reason": "user_not_found"})
    role = effective_role(target)
    if role not in (UserRole.CO_ADMIN, UserRole.SECONDARY):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Tab access is for Admins and sub-admins. The owner's own access is fixed.",
            details={"reason": "not_staff"},
        )
    unknown = [k for k in (payload.tabs or []) if k not in admin_tabs.RESTRICTABLE]
    if unknown:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, f"Unknown tab: {unknown[0]}", field="tabs",
            details={"unknown": unknown},
        )
    target.visible_admin_tabs = admin_tabs.clean_tabs(
        payload.tabs, sub_admin=role == UserRole.SECONDARY
    )
    target.powers_suspended = bool(payload.suspended)
    db.commit()
    log_admin_action(
        db, request, owner, "ROLES_TAB_ACCESS", "user", str(user_id), "success",
        new_value=(
            "powers off" if target.powers_suspended
            else "default" if target.visible_admin_tabs is None
            else ",".join(target.visible_admin_tabs) or "no tabs"
        ),
    )
    return _overview(db)


__all__ = ["router"]
