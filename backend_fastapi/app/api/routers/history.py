"""A signed-in reader's read chapters (so they follow the reader to a new device)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import User
from ...schemas.history import HistoryListResponse, HistoryReadEntry, HistorySyncRequest
from ...services import history_service

router = APIRouter(prefix="/history", tags=["history"])


@router.post("/read")
def mark_chapter_read(
    payload: HistoryReadEntry,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The reader just opened one chapter: remember it on their account."""

    at = history_service.parse_read_at(payload.read_at)
    history_service.mark_read(current_user, {payload.chapter_id: at}, db)
    db.commit()
    return {"message": "history_recorded"}


@router.post("/sync", response_model=HistoryListResponse)
def sync_history(
    payload: HistorySyncRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply the browser's changes to the account, then return the account's
    whole list of read chapters (the browser merges it into its own)."""

    if payload.clear_all:
        history_service.clear_history(current_user, db, everything=True)
    elif payload.clear_manga:
        history_service.clear_history(current_user, db, manga_ids=payload.clear_manga)

    now = datetime.utcnow()
    chapters: dict[int, datetime] = {}
    for entry in payload.entries:
        at = history_service.parse_read_at(entry.read_at, now)
        if entry.chapter_id not in chapters or chapters[entry.chapter_id] < at:
            chapters[entry.chapter_id] = at
    history_service.mark_read(current_user, chapters, db)
    db.commit()
    if not payload.return_entries:
        return {"entries": []}
    return {"entries": history_service.list_history(current_user, db)}
