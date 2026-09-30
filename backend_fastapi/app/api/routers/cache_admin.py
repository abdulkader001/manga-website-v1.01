"""Cache administration endpoints (SRS 2C.4.3).

Clear/refresh are destructive-scale actions, staged the same way a full
series rescrape is (1G.12.7): a typed confirmation, not a single click,
and an abort (400, nothing touched) rather than a silent no-op when the
named target doesn't exist. Every clear/refresh is audited with actor,
scope, and the chapter count affected (1H.7).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.auth import require_main_admin_user
from ...models import Manga
from ...services import cache_admin_service as cache_admin
from ...utils.audit_logger import log_admin_action

router = APIRouter(prefix="/admin/cache", tags=["admin-cache"])


class CachePriorityPayload(BaseModel):
    cache_priority: str = Field(..., description="on | reduced | off")


@router.get("", dependencies=[Depends(require_main_admin_user)])
def get_cache_admin_overview(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return cache_admin.cache_statistics(db)


@router.patch("/priority", dependencies=[Depends(require_main_admin_user)])
def update_cache_priority(
    request: Request,
    payload: CachePriorityPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_main_admin_user),
) -> Dict[str, Any]:
    try:
        value = cache_admin.set_cache_priority(db, payload.cache_priority)
    except cache_admin.CacheAdminError as exc:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, str(exc), field="cache_priority"
        ) from exc

    log_admin_action(
        db,
        request,
        current_user,
        "CACHE_PRIORITY_CHANGE",
        "system_settings",
        "cache_priority",
        "success",
        new_value=value,
    )
    return {"cache_priority": value}


class CacheActionPayload(BaseModel):
    scope: str = Field(..., description="all | series | website")
    manga_id: Optional[int] = None
    domain: Optional[str] = None
    # Typed confirmation (1G.12.7 pattern): "CLEAR CACHE" / "REFRESH CACHE"
    # for scope=all, the series title for scope=series, the domain for
    # scope=website.
    confirm: str = Field(..., min_length=1, max_length=512)


def _expected_confirmation(db: Session, payload: CacheActionPayload, verb: str) -> str:
    if payload.scope == cache_admin.SCOPE_ALL:
        return f"{verb} CACHE"
    if payload.scope == cache_admin.SCOPE_SERIES:
        if not payload.manga_id:
            raise ApiError(
                ErrorCode.VALIDATION_FAILED,
                "manga_id is required for scope=series",
                field="manga_id",
            )
        manga = db.get(Manga, payload.manga_id)
        if manga is None:
            # Abort safely rather than silently clearing nothing.
            raise ApiError(
                ErrorCode.VALIDATION_FAILED,
                "No series found with that manga_id; nothing was touched.",
                field="manga_id",
            )
        return (manga.title or "").strip()
    if payload.scope == cache_admin.SCOPE_WEBSITE:
        if not payload.domain:
            raise ApiError(
                ErrorCode.VALIDATION_FAILED,
                "domain is required for scope=website",
                field="domain",
            )
        return payload.domain.strip().lower()
    raise ApiError(
        ErrorCode.VALIDATION_FAILED,
        f"scope must be one of {cache_admin.SCOPES}",
        field="scope",
    )


def _run_scoped_action(
    request: Request,
    payload: CacheActionPayload,
    db: Session,
    current_user,
    *,
    verb: str,
    action_fn,
    audit_action: str,
) -> Dict[str, Any]:
    expected = _expected_confirmation(db, payload, verb)
    if payload.confirm.strip() != expected:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"Type {expected!r} exactly to confirm.",
            field="confirm",
            details={"expected": expected},
        )

    try:
        result = action_fn(
            db, scope=payload.scope, manga_id=payload.manga_id, domain=payload.domain
        )
    except cache_admin.CacheAdminError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc)) from exc

    log_admin_action(
        db,
        request,
        current_user,
        audit_action,
        "cache",
        payload.scope,
        "success",
        new_value=(
            f"translation_rows={result['translation_rows']} "
            f"ocr_rows={result['ocr_rows']} "
            f"chapters_affected={result['chapters_affected']}"
        ),
    )
    return result


@router.post("/clear", dependencies=[Depends(require_main_admin_user)])
def clear_cache(
    request: Request,
    payload: CacheActionPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_main_admin_user),
) -> Dict[str, Any]:
    return _run_scoped_action(
        request,
        payload,
        db,
        current_user,
        verb="CLEAR",
        action_fn=cache_admin.clear_cache,
        audit_action="CACHE_CLEAR",
    )


@router.post("/refresh", dependencies=[Depends(require_main_admin_user)])
def refresh_cache(
    request: Request,
    payload: CacheActionPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_main_admin_user),
) -> Dict[str, Any]:
    return _run_scoped_action(
        request,
        payload,
        db,
        current_user,
        verb="REFRESH",
        action_fn=cache_admin.refresh_cache,
        audit_action="CACHE_REFRESH",
    )


__all__ = ["router"]
