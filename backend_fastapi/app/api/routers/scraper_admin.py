"""Series-management scraper tools: previews and custom parser generation.

Everything here only *enqueues* work. The fetching, structure analysis and AI
calls run in the Celery worker (the blocking scraper never runs in the API
process); the admin page polls ``GET /admin/scraper/tasks/{id}``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.auth import get_current_user, is_main_admin, require_permission
from ...models import AdminTaskResult, ParserVersion, User
from ...utils.endpoint_limiter import async_endpoint_limiter

router = APIRouter(prefix="/admin/scraper", tags=["scraper-admin"])

TASK_RETENTION = timedelta(days=2)


def _http_url(raw: str, *, field: str) -> str:
    value = (raw or "").strip()
    candidate = value if "://" in value else f"https://{value}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or " " in candidate:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Enter a valid website address.", field=field)
    return candidate


def _enqueue(db: Session, kind: str, requested_by: int, payload: Dict[str, Any]) -> AdminTaskResult:
    db.query(AdminTaskResult).filter(
        AdminTaskResult.created_at < datetime.utcnow() - TASK_RETENTION
    ).delete(synchronize_session=False)
    row = AdminTaskResult(
        id=str(uuid.uuid4()), kind=kind, requested_by=requested_by, status="queued", payload=payload
    )
    db.add(row)
    db.commit()

    from ...tasks.scraper_tasks import run_source_task

    run_source_task.delay(row.id)
    return row


class PreviewPayload(BaseModel):
    mangaupdates_url: Optional[str] = Field(default=None, max_length=500)
    url: Optional[str] = Field(default=None, max_length=1000)
    base_url: Optional[str] = Field(default=None, max_length=500)
    title: Optional[str] = Field(default=None, max_length=300)


@router.post("/preview", status_code=status.HTTP_202_ACCEPTED)
async def start_preview(
    request: Request,
    payload: PreviewPayload,
    current_user: User = Depends(require_permission("submit_manga_url")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"scraper_preview:{current_user.id}", limit=30, window_seconds=600
    )
    series_url = (payload.url or payload.base_url or "").strip()
    mu = (payload.mangaupdates_url or "").strip()
    if not series_url and not mu:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Enter a MangaUpdates link and a source series URL to preview.",
            field="url",
        )
    body: Dict[str, Any] = {"base_url": (payload.base_url or "").strip() or None}
    if series_url:
        body["url"] = _http_url(series_url, field="url")
    if mu:
        from ...services.mangaupdates_service import MangaUpdatesError, series_id_from_url

        try:
            series_id_from_url(mu)
        except MangaUpdatesError as exc:
            raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), field="mangaupdates_url")
        body["mangaupdates_url"] = mu
    row = _enqueue(db, "preview", current_user.id, body)
    return {"task_id": row.id, "status": row.status}


class GenerateParserPayload(BaseModel):
    url: str = Field(..., min_length=3, max_length=1000)


@router.post("/parsers/generate", status_code=status.HTTP_202_ACCEPTED)
async def start_parser_generation(
    request: Request,
    payload: GenerateParserPayload,
    current_user: User = Depends(require_permission("trigger_scraper_ai")),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    await async_endpoint_limiter.check_limit(
        request, f"scraper_parser_generate:{current_user.id}", limit=15, window_seconds=3600
    )
    row = _enqueue(db, "parser", current_user.id, {"url": _http_url(payload.url, field="url")})
    return {"task_id": row.id, "status": row.status}


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    row = db.get(AdminTaskResult, task_id)
    if row is None or (row.requested_by != current_user.id and not is_main_admin(current_user)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    body: Dict[str, Any] = {"task_id": row.id, "kind": row.kind, "status": row.status}
    if row.status in {"done", "failed"}:
        body.update(row.result or {})
    return body


@router.get("/parsers")
def list_parsers(
    _: User = Depends(require_permission("view_websites")),
    db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    """Latest parser per website (active first) for the custom-parser panel."""

    rows = db.query(ParserVersion).order_by(ParserVersion.domain, ParserVersion.version.desc()).all()
    latest: Dict[str, ParserVersion] = {}
    for row in rows:
        current = latest.get(row.domain)
        if current is None or (row.status == "active" and current.status != "active"):
            latest[row.domain] = row
    return {
        "items": [
            {
                "id": row.id,
                "domain": row.domain,
                "version": row.version,
                "status": row.status,
                "source": row.source,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in sorted(latest.values(), key=lambda r: r.domain)
        ]
    }
