"""Authenticated read history endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import Chapter, Manga, ReadHistory, User
from ...schemas.history import (
    HistoryClearResponse,
    HistoryDeleteResponse,
    HistoryEntryBase,
    HistoryUpsertRequest,
)
from ...services.history_service import record_history as _record_history

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/history", tags=["history"])
legacy_router = APIRouter(prefix="/read_history", tags=["history"])


def _history_entry_to_dict(
    entry: ReadHistory,
    manga: Manga | None,
    chapter: Chapter | None,
) -> HistoryEntryBase:
    last_read = getattr(entry, "last_read_at", None)
    return {
        "id": entry.id,
        "manga_id": entry.manga_id,
        "manga_title": getattr(manga, "title", None),
        "cover_image": getattr(manga, "cover_image", None)
        or getattr(manga, "cover_url", None),
        "chapter_id": entry.chapter_id,
        "chapter_title": getattr(chapter, "chapter_title", None),
        "last_read_at": last_read.isoformat() if last_read else None,
    }


def _list_history_impl(
    user: User, db: Session, skip: int, limit: int
) -> list[HistoryEntryBase]:
    rows = (
        db.query(ReadHistory, Manga, Chapter)
        .join(Manga, ReadHistory.manga_id == Manga.id)
        .join(Chapter, ReadHistory.chapter_id == Chapter.id, isouter=True)
        .filter(ReadHistory.user_id == user.id)
        .order_by(ReadHistory.last_read_at.desc().nullslast(), ReadHistory.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        _history_entry_to_dict(entry, manga, chapter) for entry, manga, chapter in rows
    ]


def _list_history_route(
    skip: int,
    limit: int,
    current_user: User,
    db: Session,
) -> list[HistoryEntryBase]:
    skip = max(skip, 0)
    limit = max(1, min(limit, 200))
    return _list_history_impl(current_user, db, skip, limit)


def _upsert_history_route(
    payload: HistoryUpsertRequest,
    current_user: User,
    db: Session,
    response: Response | None = None,
) -> HistoryEntryBase:
    manga_id = payload.manga_id
    chapter_id = payload.chapter_id

    entry, created = _record_history(current_user, manga_id, chapter_id, db)

    manga = db.get(Manga, entry.manga_id)
    chapter = db.get(Chapter, entry.chapter_id)

    if response:
        response.status_code = (
            status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    return _history_entry_to_dict(entry, manga, chapter)


def _delete_history_route(
    history_id: int,
    current_user: User,
    db: Session,
) -> HistoryDeleteResponse:
    entry = (
        db.query(ReadHistory)
        .filter(ReadHistory.id == history_id, ReadHistory.user_id == current_user.id)
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")

    db.delete(entry)
    db.commit()
    return HistoryDeleteResponse(ok=True, deleted_id=history_id)


def _clear_history_route(current_user: User, db: Session) -> HistoryClearResponse:
    deleted = (
        db.query(ReadHistory).filter(ReadHistory.user_id == current_user.id).delete()
    )
    db.commit()
    return HistoryClearResponse(ok=True, deleted_count=deleted)


@router.get("/", response_model=list[HistoryEntryBase])
def list_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[HistoryEntryBase]:
    """Return read history for the authenticated user."""

    return _list_history_route(skip, limit, current_user, db)


@router.post("/", response_model=HistoryEntryBase)
def upsert_history(
    payload: HistoryUpsertRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryEntryBase:
    """Create or update a read-history entry for the authenticated user."""

    return _upsert_history_route(payload, current_user, db, response)


@router.delete("/{history_id}", response_model=HistoryDeleteResponse)
def delete_history(
    history_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryDeleteResponse:
    """Delete a read-history entry."""

    return _delete_history_route(history_id, current_user, db)


@router.delete("/clear/all", response_model=HistoryClearResponse)
def clear_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryClearResponse:
    """Remove all read-history entries for the authenticated user."""

    return _clear_history_route(current_user, db)


@legacy_router.get("/", response_model=list[HistoryEntryBase], deprecated=True)
def legacy_list_history(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[HistoryEntryBase]:
    logger.info(
        "Deprecated endpoint hit", route="legacy_list_history", user_id=current_user.id
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-07-01"
    return _list_history_route(skip, limit, current_user, db)


@legacy_router.post("/", response_model=HistoryEntryBase, deprecated=True)
def legacy_upsert_history(
    payload: HistoryUpsertRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryEntryBase:
    logger.info(
        "Deprecated endpoint hit",
        route="legacy_upsert_history",
        user_id=current_user.id,
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-07-01"
    return _upsert_history_route(payload, current_user, db, response)


@legacy_router.delete(
    "/{history_id}", response_model=HistoryDeleteResponse, deprecated=True
)
def legacy_delete_history(
    response: Response,
    history_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryDeleteResponse:
    logger.info(
        "Deprecated endpoint hit",
        route="legacy_delete_history",
        user_id=current_user.id,
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-07-01"
    return _delete_history_route(history_id, current_user, db)


@legacy_router.delete(
    "/clear/all", response_model=HistoryClearResponse, deprecated=True
)
def legacy_clear_history(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HistoryClearResponse:
    logger.info(
        "Deprecated endpoint hit", route="legacy_clear_history", user_id=current_user.id
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-07-01"
    return _clear_history_route(current_user, db)


__all__ = ["router", "legacy_router", "_record_history"]
