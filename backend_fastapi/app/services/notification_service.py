"""Notification creation, delivery, and reader APIs (SRS 1I).

Writing a notification always goes through the queue (``notify_async`` ->
a Celery task): 1I.5.1 requires generation to be asynchronous and to never
fail the action that triggered it. ``notify_async`` therefore only ever
logs on failure to enqueue; it never raises back to the caller.
"""

from __future__ import annotations

import structlog
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Notification, NotificationPreference
from ..models.notifications import (
    CATEGORY_ADMINISTRATIVE,
    CATEGORY_READER,
    CATEGORY_SECURITY,
    PRIORITY_NORMAL,
    PRIORITY_SECURITY,
)

logger = structlog.get_logger("backend_fastapi.notifications")

# Machine type -> category (1I.3). Anything not listed here defaults to
# "reader" — the more conservative assumption for an unrecognised type.
TYPE_CATEGORY: Dict[str, str] = {
    # Reader-facing (1I.3.1)
    "chapter.new": CATEGORY_READER,
    "series.completed": CATEGORY_READER,
    "comment.reply": CATEGORY_READER,
    "comment.like": CATEGORY_READER,
    "comment.mention": CATEGORY_READER,
    "rank.advancement": CATEGORY_READER,
    "translation.corrected": CATEGORY_READER,
    "moderation.action": CATEGORY_READER,
    "reputation.pill_earned": CATEGORY_READER,
    "comment.reaction": CATEGORY_READER,
    "quota.exceeded": CATEGORY_READER,
    "provider.failure": CATEGORY_READER,
    "role.changed": CATEGORY_READER,
    # Administrator/moderator-facing (1I.3.2)
    "parser.candidate_ready": CATEGORY_ADMINISTRATIVE,
    "parser.generation_failed": CATEGORY_ADMINISTRATIVE,
    "parser.needed": CATEGORY_ADMINISTRATIVE,
    "parser.repair_candidate_ready": CATEGORY_ADMINISTRATIVE,
    "parser.disabled": CATEGORY_ADMINISTRATIVE,
    "website.structure_changed": CATEGORY_ADMINISTRATIVE,
    "chapter.fix_completed": CATEGORY_ADMINISTRATIVE,
    "chapter.fix_failed": CATEGORY_ADMINISTRATIVE,
    "chapter.repeatedly_broken": CATEGORY_ADMINISTRATIVE,
    "series.rescraped": CATEGORY_ADMINISTRATIVE,
    "series.rescrape_aborted": CATEGORY_ADMINISTRATIVE,
    "series.ingested": CATEGORY_ADMINISTRATIVE,
    "ingestion.failed": CATEGORY_ADMINISTRATIVE,
    "report.queue": CATEGORY_ADMINISTRATIVE,
    "disposable_email.banned": CATEGORY_ADMINISTRATIVE,
    "quota.ceiling_reached": CATEGORY_ADMINISTRATIVE,
    # Security (1I.3.2) — never suppressible.
    "security.permanent_admin_tamper_attempt": CATEGORY_SECURITY,
}

# How long a batchable notification stays "open" for in-place aggregation
# before a new event starts a fresh one (1I.5.3). A user's own digest
# preference for a type extends this window (see notify_async's caller).
DEFAULT_BATCH_WINDOW_MINUTES = 30
DIGEST_WINDOW_MINUTES = 24 * 60


def _category_for(type_: str, category: Optional[str]) -> str:
    if category:
        return category
    return TYPE_CATEGORY.get(type_, CATEGORY_READER)


def _priority_for(category: str, priority: Optional[str]) -> str:
    if priority:
        return priority
    if category == CATEGORY_SECURITY:
        return PRIORITY_SECURITY
    return PRIORITY_NORMAL


def notify_async(
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    user_id: Optional[int] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[Any] = None,
    data: Optional[dict] = None,
    dedup_key: Optional[str] = None,
) -> None:
    """Enqueue notification creation. Never raises — a broker outage must
    never fail the action that triggered the notification (1I.5.1)."""

    try:
        from ..tasks.notification_tasks import create_notification

        create_notification.delay(
            type=type,
            title=title,
            body=body,
            user_id=user_id,
            category=category,
            priority=priority,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            data=data,
            dedup_key=dedup_key,
        )
    except Exception:  # pragma: no cover - broker outage, best-effort only
        logger.error(
            "notification_enqueue_failed", type=type, user_id=user_id, exc_info=True
        )


def create_notification(
    db: Session,
    *,
    type: str,
    title: str,
    body: Optional[str] = None,
    user_id: Optional[int] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    data: Optional[dict] = None,
    dedup_key: Optional[str] = None,
) -> Notification:
    """Persist a notification, applying mute preferences and batching.

    Called by the ``create_notification`` Celery task — the actual DB write
    always happens off the request path. ``user_id=None`` addresses the
    Permanent Administrator's bell (resolved at read time, 1F.2.3).
    """

    resolved_category = _category_for(type, category)
    resolved_priority = _priority_for(resolved_category, priority)
    is_security = resolved_category == CATEGORY_SECURITY

    prefs = None
    if user_id is not None:
        prefs = (
            db.query(NotificationPreference)
            .filter(NotificationPreference.user_id == user_id)
            .one_or_none()
        )

    # Security alerts are never suppressible (1I.3.2) — skip mute checks
    # entirely for that category.
    if prefs is not None and not is_security:
        if prefs.global_mute:
            return _write_notification(
                db,
                type=type,
                title=title,
                body=body,
                user_id=user_id,
                category=resolved_category,
                priority=resolved_priority,
                target_type=target_type,
                target_id=target_id,
                data=data,
                dedup_key=dedup_key,
                suppressed=True,
            )
        if type in (prefs.muted_types or []):
            return _write_notification(
                db,
                type=type,
                title=title,
                body=body,
                user_id=user_id,
                category=resolved_category,
                priority=resolved_priority,
                target_type=target_type,
                target_id=target_id,
                data=data,
                dedup_key=dedup_key,
                suppressed=True,
            )

    window_minutes = DEFAULT_BATCH_WINDOW_MINUTES
    if prefs is not None and type in (prefs.digest_types or []):
        window_minutes = DIGEST_WINDOW_MINUTES

    note = _write_notification(
        db,
        type=type,
        title=title,
        body=body,
        user_id=user_id,
        category=resolved_category,
        priority=resolved_priority,
        target_type=target_type,
        target_id=target_id,
        data=data,
        dedup_key=dedup_key,
        window_minutes=window_minutes,
    )

    should_email = is_security or (
        prefs is not None and type in (prefs.email_types or [])
    )
    if should_email and user_id is not None:
        _dispatch_email(db, user_id=user_id, title=title, body=body)

    return note


def _write_notification(
    db: Session,
    *,
    type: str,
    title: str,
    body: Optional[str],
    user_id: Optional[int],
    category: str,
    priority: str,
    target_type: Optional[str],
    target_id: Optional[str],
    data: Optional[dict],
    dedup_key: Optional[str],
    window_minutes: int = DEFAULT_BATCH_WINDOW_MINUTES,
    suppressed: bool = False,
) -> Notification:
    """Insert, or update-in-place a still-unread batchable match (1I.5.3:
    "ten new chapters across five series becomes a small number of
    notifications, not ten", and "the same event never notifies twice")."""

    if dedup_key and not suppressed:
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        existing = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.type == type,
                Notification.dedup_key == dedup_key,
                Notification.read.is_(False),
                Notification.created_at >= cutoff,
            )
            .order_by(Notification.id.desc())
            .first()
        )
        if existing is not None:
            merged_data = dict(existing.data or {})
            count = int(merged_data.get("count", 1)) + 1
            merged_data["count"] = count
            if data:
                merged_data.update(data)
            existing.data = merged_data
            existing.title = title
            existing.body = body
            existing.created_at = datetime.utcnow()
            db.commit()
            db.refresh(existing)
            return existing

    note = Notification(
        user_id=user_id,
        type=type,
        category=category,
        title=title,
        body=body,
        target_type=target_type,
        target_id=target_id,
        data=data,
        priority=priority,
        dedup_key=dedup_key,
    )
    if suppressed:
        # Muted: still recorded (so it shows in history / "the same event
        # never notifies twice" holds), but pre-marked read so it never
        # shows up in the badge or unread list (1I.5.2 mute).
        note.read = True
        note.read_at = datetime.utcnow()
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def _dispatch_email(
    db: Session, *, user_id: int, title: str, body: Optional[str]
) -> None:
    from ..models import User
    from ..utils.email_crypto import allow_email_decryption

    user = db.get(User, user_id)
    if user is None:
        return
    with allow_email_decryption():
        address = user.email_plaintext
    if not address:
        return

    try:
        from ..tasks.email_tasks import send_notification_email

        send_notification_email.delay(address, title, body or "")
    except Exception:  # pragma: no cover - best-effort, must not block
        logger.error(
            "notification_email_enqueue_failed", user_id=user_id, exc_info=True
        )


# ---------------------------------------------------------------------------
# Reader-facing query/mutation API (1I.6)
# ---------------------------------------------------------------------------


def notifications_for(
    db: Session,
    *,
    user_id: int,
    is_permanent_admin: bool = False,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> List[Notification]:
    query = db.query(Notification)
    if is_permanent_admin:
        query = query.filter(
            (Notification.user_id == user_id) | (Notification.user_id.is_(None))
        )
    else:
        query = query.filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.read.is_(False))
    return query.order_by(Notification.id.desc()).offset(offset).limit(limit).all()


def unread_count(db: Session, *, user_id: int, is_permanent_admin: bool = False) -> int:
    query = db.query(Notification).filter(Notification.read.is_(False))
    if is_permanent_admin:
        query = query.filter(
            (Notification.user_id == user_id) | (Notification.user_id.is_(None))
        )
    else:
        query = query.filter(Notification.user_id == user_id)
    return query.count()


def _visible(
    db: Session, notification_id: int, *, user_id: int, is_permanent_admin: bool
) -> Optional[Notification]:
    note = db.get(Notification, notification_id)
    if note is None:
        return None
    if note.user_id == user_id:
        return note
    if is_permanent_admin and note.user_id is None:
        return note
    return None


def mark_read(
    db: Session, notification_id: int, *, user_id: int, is_permanent_admin: bool = False
) -> Optional[Notification]:
    note = _visible(
        db, notification_id, user_id=user_id, is_permanent_admin=is_permanent_admin
    )
    if note is None:
        return None
    if not note.read:
        note.read = True
        note.read_at = datetime.utcnow()
        db.commit()
        db.refresh(note)
    return note


def mark_all_read(
    db: Session, *, user_id: int, is_permanent_admin: bool = False
) -> int:
    query = db.query(Notification).filter(Notification.read.is_(False))
    if is_permanent_admin:
        query = query.filter(
            (Notification.user_id == user_id) | (Notification.user_id.is_(None))
        )
    else:
        query = query.filter(Notification.user_id == user_id)
    now = datetime.utcnow()
    updated = query.update(
        {Notification.read: True, Notification.read_at: now},
        synchronize_session=False,
    )
    db.commit()
    return updated


def delete_notification(
    db: Session, notification_id: int, *, user_id: int, is_permanent_admin: bool = False
) -> bool:
    note = _visible(
        db, notification_id, user_id=user_id, is_permanent_admin=is_permanent_admin
    )
    if note is None:
        return False
    db.delete(note)
    db.commit()
    return True


def get_preferences(db: Session, *, user_id: int) -> NotificationPreference:
    prefs = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id)
        .one_or_none()
    )
    if prefs is None:
        prefs = NotificationPreference(user_id=user_id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def set_preferences(
    db: Session,
    *,
    user_id: int,
    global_mute: Optional[bool] = None,
    muted_types: Optional[List[str]] = None,
    email_types: Optional[List[str]] = None,
    digest_types: Optional[List[str]] = None,
) -> NotificationPreference:
    prefs = get_preferences(db, user_id=user_id)
    if global_mute is not None:
        prefs.global_mute = global_mute
    if muted_types is not None:
        prefs.muted_types = list(muted_types)
    if email_types is not None:
        prefs.email_types = list(email_types)
    if digest_types is not None:
        prefs.digest_types = list(digest_types)
    db.commit()
    db.refresh(prefs)
    return prefs


__all__ = [
    "notify_async",
    "create_notification",
    "notifications_for",
    "unread_count",
    "mark_read",
    "mark_all_read",
    "delete_notification",
    "get_preferences",
    "set_preferences",
    "TYPE_CATEGORY",
]
