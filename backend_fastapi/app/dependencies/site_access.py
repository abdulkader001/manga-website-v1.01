"""Members-only switch (Admin -> Site Functions -> "Sign-in required").

It is **off by default** (``LOGIN_REQUIRED_DEFAULT``): guests browse and read
until the owner switches it on. While it is on, the catalogue, reader and
community routes answer anonymous visitors with ``LOGIN_REQUIRED``. A site with
no settings row yet gets the default; if the setting can't be read at all the
guard fails closed, so a database hiccup never opens a members-only site.
Sign-in, sign-up, the public site config and every admin/bootstrap route are
never behind it, so the switch can't lock anyone (least of all the owner) out
of signing in.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.db import get_db
from ..models import SystemSettings, User
from ..models.settings import LOGIN_REQUIRED_DEFAULT
from .auth import get_optional_user


def login_required(db: Session) -> bool:
    try:
        row = db.query(SystemSettings.login_required).limit(1).first()
    except Exception:  # unreadable: fail closed
        db.rollback()
        return True
    if row is None or row[0] is None:  # no settings row yet: the default
        return LOGIN_REQUIRED_DEFAULT
    return bool(row[0])


async def require_site_access(
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> None:
    if user is None and login_required(db):
        raise ApiError(
            ErrorCode.LOGIN_REQUIRED,
            "Sign in to read on this site.",
        )


__all__ = ["LOGIN_REQUIRED_DEFAULT", "login_required", "require_site_access"]
