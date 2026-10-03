"""``require_function(key)``: a route that only answers while the owner has the
function switched on (Admin -> Site Functions). Off answers ``FUNCTION_DISABLED``.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.site_functions import REGISTRY
from ..services import site_functions as functions
from .auth import release_connection


def require_function(key: str):
    if key not in REGISTRY:  # a typo here is a bug, fail at import time
        raise KeyError(f"unknown site function {key!r}")

    def _dependency(db: Session = Depends(get_db)) -> None:
        enabled = functions.is_enabled(db, key)
        release_connection(db)
        if not enabled:
            raise functions.disabled_error(key)

    _dependency.__name__ = f"require_function_{key}"
    _dependency.function = key  # type: ignore[attr-defined]
    return _dependency


__all__ = ["require_function"]
