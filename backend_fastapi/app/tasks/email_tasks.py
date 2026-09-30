"""Email related Celery tasks."""

from __future__ import annotations

from typing import Dict, Optional

from ..core.celery_app import celery_app
from ..services import email_service


@celery_app.task(name="backend_fastapi.app.tasks.email_tasks.send_magic_link")
def send_magic_link_email(
    email: str,
    magic_link: str,
    locale: Optional[str] = None,
) -> Dict[str, str]:
    """Send a magic-link email via the email service."""

    email_service.send_magic_link_email(email, magic_link, locale=locale)
    return {"status": "queued", "email": email}


@celery_app.task(name="backend_fastapi.app.tasks.email_tasks.send_notification_email")
def send_notification_email(email: str, subject: str, body: str) -> Dict[str, str]:
    """Send a bell-notification email via the email service (SRS 1I.5.1)."""

    email_service.send_notification_email(email, subject, body)
    return {"status": "queued", "email": email}


__all__ = ["send_magic_link_email", "send_notification_email"]
