"""``require_power(key)``: a route the owner can delegate.

The owner (main admin) always passes. A sub-admin passes when they hold
``key`` (``permissions_service.has_permission``). For a site-owner power
(``OWNER_POWERS``) they must also have an authenticator and have entered a
code recently (the admin step-up, same ``ADMIN_CODE_VALID_HOURS`` window the
owner uses), so a stolen sign-in alone can't reach them.
"""

from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.db import get_db
from ..core.permissions import DESCRIPTIONS, OWNER_POWERS
from ..models import User
from ..services import admin_second_factor as second_factor
from ..services.admin_succession import record_activity
from ..services.permissions_service import has_permission
from .auth import is_main_admin, require_admin_user


def require_power(permission: str):
    def _dependency(
        request: Request,
        db: Session = Depends(get_db),
        current_user: User = Depends(require_admin_user),
    ) -> User:
        if is_main_admin(current_user):
            return current_user
        record_activity(db, current_user)
        if not has_permission(db, current_user, permission):
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "You don't have this power. Ask the site owner.",
                details={"reason": "missing_power", "permission": permission, "description": DESCRIPTIONS.get(permission)},
            )
        if permission in OWNER_POWERS and not second_factor.step_up_valid(
            current_user, request.cookies.get(second_factor.STEP_UP_COOKIE)
        ):
            raise ApiError(
                ErrorCode.REVERIFICATION_REQUIRED,
                "Enter the code from your authenticator app to use site-owner powers.",
                details={"reason": "step_up_required", "permission": permission},
            )
        return current_user

    _dependency.__name__ = f"require_power_{permission}"
    _dependency.power = permission  # type: ignore[attr-defined]
    return _dependency


__all__ = ["require_power"]
