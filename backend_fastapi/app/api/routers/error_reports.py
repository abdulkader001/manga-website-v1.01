"""Admin -> Error Report, and the route browsers use to report their errors.

``POST /errors/report`` is open to everyone (guests' browsers crash too) and
not behind "Sign-in required"; it is rate-limited and stores nothing that
identifies the visitor. The admin routes need ``view_error_reports`` (the
owner and Admins by default; a sub-admin only if given it).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.powers import require_power
from ...models import ErrorReport, User
from ...models.error_report import SOURCE_BROWSER, SOURCES
from ...services import error_report_service as reports
from ...utils.audit_logger import log_admin_action
from ...utils.bounded_threadpool import run_in_db_threadpool
from ...utils.client_ip import resolve_client_ip
from ...utils.endpoint_limiter import async_endpoint_limiter

public_router = APIRouter(prefix="/errors", tags=["error-report"])
router = APIRouter(prefix="/admin/error-reports", tags=["error-report"])

POWER = "view_error_reports"


class BrowserError(BaseModel):
    kind: str = Field("Error", max_length=128)
    message: str = Field("", max_length=4000)
    stack: Optional[str] = Field(None, max_length=16000)
    # The page's path only; anything after ? or # is dropped before saving.
    page: Optional[str] = Field(None, max_length=500)


@public_router.post("/report", status_code=202)
async def report_browser_error(payload: BrowserError, request: Request) -> Dict[str, Any]:
    # Keyed on a hash, so the visitor's address is never stored, even in Redis.
    who = hashlib.sha256(resolve_client_ip(request).encode()).hexdigest()[:24]
    await async_endpoint_limiter.check_limit(request, f"error_report:{who}", limit=20, window_seconds=300)
    await run_in_db_threadpool(
        lambda: reports.record(
            source=SOURCE_BROWSER,
            kind=payload.kind or "Error",
            message=payload.message,
            location=payload.page,
            stack=payload.stack,
        )
    )
    return {"ok": True}


def _summary(db: Session) -> Dict[str, Any]:
    day_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    by_source = dict(
        db.query(ErrorReport.source, func.count(ErrorReport.id))
        .filter(ErrorReport.resolved.is_(False))
        .group_by(ErrorReport.source)
        .all()
    )
    return {
        "open": db.query(ErrorReport.id).filter(ErrorReport.resolved.is_(False)).count(),
        "resolved": db.query(ErrorReport.id).filter(ErrorReport.resolved.is_(True)).count(),
        "last_24h": db.query(ErrorReport.id).filter(ErrorReport.last_seen >= day_ago).count(),
        "by_source": {s: int(by_source.get(s, 0)) for s in SOURCES},
    }


@router.get("")
def list_error_reports(
    status: Literal["open", "resolved", "all"] = "open",
    source: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_power(POWER)),
) -> Dict[str, Any]:
    if source is not None and source not in SOURCES:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Unknown source.", field="source")
    query = db.query(ErrorReport)
    if status == "open":
        query = query.filter(ErrorReport.resolved.is_(False))
    elif status == "resolved":
        query = query.filter(ErrorReport.resolved.is_(True))
    if source:
        query = query.filter(ErrorReport.source == source)
    rows = query.order_by(ErrorReport.last_seen.desc(), ErrorReport.id.desc()).limit(limit).all()
    return {"items": [reports.serialize(r) for r in rows], "summary": _summary(db)}


def _get(db: Session, report_id: int) -> ErrorReport:
    row = db.get(ErrorReport, report_id)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "That error entry no longer exists.")
    return row


@router.post("/{report_id}/resolve")
def resolve_error_report(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_power(POWER)),
) -> Dict[str, Any]:
    row = _get(db, report_id)
    row.resolved = True
    row.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.resolved_by = user.id
    db.commit()
    log_admin_action(db, request, user, "ERROR_REPORT_RESOLVE", "error_report", str(report_id), "success")
    return reports.serialize(row)


@router.post("/{report_id}/reopen")
def reopen_error_report(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_power(POWER)),
) -> Dict[str, Any]:
    row = _get(db, report_id)
    row.resolved = False
    row.resolved_at = None
    row.resolved_by = None
    db.commit()
    log_admin_action(db, request, user, "ERROR_REPORT_REOPEN", "error_report", str(report_id), "success")
    return reports.serialize(row)


@router.delete("/resolved")
def clear_resolved_error_reports(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_power(POWER)),
) -> Dict[str, Any]:
    removed = db.query(ErrorReport).filter(ErrorReport.resolved.is_(True)).delete(synchronize_session=False)
    db.commit()
    log_admin_action(db, request, user, "ERROR_REPORT_CLEAR", "error_report", "resolved", "success", new_value=str(removed))
    return {"removed": int(removed)}
