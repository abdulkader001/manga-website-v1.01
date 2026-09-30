"""The bell: notification list/read/delete + per-account preferences (1I.6)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.pagination import MAX_OFFSET
from ...dependencies.auth import get_current_user
from ...models import User
from ...services import notification_service

router = APIRouter(tags=["notifications"])


def _is_permanent_admin(user: User) -> bool:
    return bool(
        getattr(user, "is_main_admin", False) or getattr(user, "permanent", False)
    )


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Paginated list — the panel uses a small ``limit``; the full
    notifications page pages through the rest (never the entire history,
    1I.2.2)."""

    items = notification_service.notifications_for(
        db,
        user_id=current_user.id,
        is_permanent_admin=_is_permanent_admin(current_user),
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
    return {"items": [n.to_dict() for n in items], "limit": limit, "offset": offset}


@router.get("/notifications/unread-count")
def get_unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, int]:
    count = notification_service.unread_count(
        db,
        user_id=current_user.id,
        is_permanent_admin=_is_permanent_admin(current_user),
    )
    return {"count": count}


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    note = notification_service.mark_read(
        db,
        notification_id,
        user_id=current_user.id,
        is_permanent_admin=_is_permanent_admin(current_user),
    )
    if note is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="notification_not_found"
        )
    return note.to_dict()


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, int]:
    updated = notification_service.mark_all_read(
        db,
        user_id=current_user.id,
        is_permanent_admin=_is_permanent_admin(current_user),
    )
    return {"updated": updated}


@router.delete("/notifications/{notification_id}")
def dismiss_notification(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, bool]:
    deleted = notification_service.delete_notification(
        db,
        notification_id,
        user_id=current_user.id,
        is_permanent_admin=_is_permanent_admin(current_user),
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="notification_not_found"
        )
    return {"deleted": True}


class NotificationPrefsPayload(BaseModel):
    global_mute: Optional[bool] = None
    muted_types: Optional[List[str]] = None
    email_types: Optional[List[str]] = None
    digest_types: Optional[List[str]] = None


@router.get("/users/me/notification-prefs")
def get_notification_prefs(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    prefs = notification_service.get_preferences(db, user_id=current_user.id)
    return prefs.to_dict()


@router.put("/users/me/notification-prefs")
def update_notification_prefs(
    payload: NotificationPrefsPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    prefs = notification_service.set_preferences(
        db,
        user_id=current_user.id,
        global_mute=payload.global_mute,
        muted_types=payload.muted_types,
        email_types=payload.email_types,
        digest_types=payload.digest_types,
    )
    return prefs.to_dict()


__all__ = ["router"]
