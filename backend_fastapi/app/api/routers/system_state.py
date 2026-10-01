"""Public system-state routes (no personal data)."""

from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...models import User

logger = structlog.get_logger("backend_fastapi.system_state")

router = APIRouter(prefix="/system", tags=["system"])


def _admin_configured(db: Session) -> bool:
    return db.query(User.id).filter(User.is_main_admin.is_(True)).first() is not None


@router.get("/state")
def system_state_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Whether the site owner has signed in for the first time.

    Public and unauthenticated: a single boolean, never who the admin is.
    """

    return {"admin_configured": _admin_configured(db)}


@router.get("/health")
def system_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Provide a lightweight system health summary."""

    checks: Dict[str, Any] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Database health check failed")
        checks["database"] = False

    # `ok` is the database check only; whether the owner has signed in yet is
    # informational and never makes a fresh install look unhealthy.
    ok = all(value is True for value in checks.values())
    if checks["database"]:
        checks["admin_configured"] = _admin_configured(db)

    return {"ok": ok, "checks": checks}
