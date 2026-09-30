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
        return {"id": note.id}
    finally:
        db.close()


__all__ = ["create_notification"]
