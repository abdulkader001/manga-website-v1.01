"""Automatic succession settings (the owner only -- never delegable)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.auth import require_main_admin_user
from ...models import User
from ...services import admin_second_factor, admin_succession
from ...utils.audit_logger import log_admin_action

router = APIRouter(prefix="/admin/roles/succession", tags=["roles"])


def _overview(db: Session) -> Dict[str, Any]:
    return {
        **admin_succession.config(db),
        "deputies": admin_succession.deputies_overview(db),
        "candidates": admin_succession.candidates(db)[:10],
    }


@router.get("")
def get_succession(db: Session = Depends(get_db), _: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    return _overview(db)


class SuccessionPayload(BaseModel):
    enabled: bool
    inactive_days: int = Field(..., ge=admin_succession.MIN_INACTIVE_DAYS, le=admin_succession.MAX_INACTIVE_DAYS)
    code: Optional[str] = Field(default=None, max_length=12)


@router.put("")
def save_succession(
    payload: SuccessionPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    if not admin_second_factor.verify_user_code(db, user, payload.code or "", enabled_only=True):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Enter the code from your authenticator app to change automatic succession.",
            details={"reason": "code_required"},
        )
    result = admin_succession.set_config(db, enabled=payload.enabled, inactive_days=payload.inactive_days)
    log_admin_action(
        db, request, user, "roles.succession_settings", "roles", "succession", "success",
        new_value=f"enabled={payload.enabled} inactive_days={payload.inactive_days}",
    )
    return {**result, "deputies": admin_succession.deputies_overview(db), "candidates": admin_succession.candidates(db)[:10]}


__all__ = ["router"]
