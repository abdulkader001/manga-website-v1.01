"""Notification creation Celery task (SRS 1I.5.1: never inline in a request)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.celery_app import celery_app
from ..core.db import SessionLocal
from ..services import notification_service


@celery_app.task(
    name="backend_fastapi.app.tasks.notification_tasks.create_notification",
    max_retries=3,
    default_retry_delay=30,
)
def create_notification(
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    user_id: Optional[int] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    dedup_key: Optional[str] = None,
) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        note = notification_service.create_notification(
            db,
            type=type,
            title=title,
            body=body,
            user_id=user_id,
            category=category,
            priority=priority,
            target_type=target_type,
            target_id=target_id,
            data=data,
            dedup_key=dedup_key,
        )
        return {"id": note.id if note is not None else None}
    finally:
        db.close()


@celery_app.task(
    name="backend_fastapi.app.tasks.notification_tasks.fan_out_announcement",
    max_retries=3,
    default_retry_delay=30,
)
def fan_out_announcement(announcement_id: int) -> Dict[str, Any]:
    """Put an admin broadcast/popup into every active account's bell.

    One bulk insert per chunk rather than one task per user: a broadcast to
    the whole site must not flood the queue.
    """

    from ..models import Announcement, Notification, User
    from ..models.notifications import CATEGORY_READER, PRIORITY_NORMAL

    db = SessionLocal()
    try:
        item = db.get(Announcement, announcement_id)
        if item is None or not item.enabled:
            return {"sent": 0}
        common = {
            "type": "announcement",
            "category": CATEGORY_READER,
            "priority": PRIORITY_NORMAL,
            "title": (item.title or "Announcement")[:255],
            "body": item.message,
            "target_type": "announcement",
            "target_id": str(item.id),
            "data": {"announcement_id": item.id, "is_popup": bool(item.is_popup)},
            "dedup_key": f"announcement:{item.id}",
            "read": False,
        }
        sent = 0
        last_id = 0
        while True:
            ids = [
                row[0]
                for row in db.query(User.id)
                .filter(User.id > last_id, User.is_active.is_(True))
                .order_by(User.id)
                .limit(1000)
            ]
            if not ids:
                break
            db.bulk_insert_mappings(Notification, [{**common, "user_id": uid} for uid in ids])
            db.commit()
            sent += len(ids)
            last_id = ids[-1]
        return {"sent": sent}
    finally:
        db.close()


__all__ = ["create_notification", "fan_out_announcement"]
