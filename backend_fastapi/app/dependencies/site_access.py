"""Members-only switch (Admin Settings -> "Sign-in required").

When the main admin turns it on, the catalogue, reader and community routes
answer anonymous visitors with ``LOGIN_REQUIRED``. Sign-in, sign-up, the
public site config and every admin/bootstrap route are never behind it, so
the switch can't lock anyone (least of all the admin) out of signing in.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.db import get_db
from ..models import SystemSettings, User
from .auth import get_optional_user


def login_required(db: Session) -> bool:
    try:
        value = db.query(SystemSettings.login_required).limit(1).scalar()
    except Exception:  # column missing before the migration runs
        db.rollback()
        return False
    return bool(value)


async def require_site_access(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> None:
    if user is None and login_required(db):
        raise ApiError(
            ErrorCode.LOGIN_REQUIRED,
            "Sign in to read on this site.",
        )


__all__ = ["login_required", "require_site_access"]
