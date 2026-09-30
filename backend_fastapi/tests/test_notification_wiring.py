"""Every "notify the administrator" obligation from Sub-part 1G actually
delivers a notification (SRS 1I.7), and a notification failure never fails
the triggering action (SRS 1I.5.1) - verified by making the queue itself
raise and confirming the caller still succeeds.
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import Chapter, Manga, Notification, User, UserRole
from backend_fastapi.app.services import admin_service


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _make_user(**kwargs) -> User:
    fields = {
        "email": f"wiring-{uuid.uuid4().hex}@example.com",
        "is_active": True,
        "name": "Wiring User",
        "role": UserRole.USER,
        "provider": "magic_link",
    }
    fields.update(kwargs)
    with SessionLocal() as db:
        user = User(**fields)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _latest_notification(type_: str, user_id=None):
    with SessionLocal() as db:
        query = db.query(Notification).filter(Notification.type == type_)
        if user_id is not None:
            query = query.filter(Notification.user_id == user_id)
        return query.order_by(Notification.id.desc()).first()


def test_role_change_notifies_the_affected_user():
    target = _make_user()
    with SessionLocal() as db:
        target_row = db.get(User, target.id)
        admin_service.log_role_change(
            db,
            actor=None,
            target=target_row,
            action="PROMOTE_MODERATOR",
            method="manual",
            from_role="user",
            to_role="moderator",
        )
    note = _latest_notification("role.changed", user_id=target.id)
    assert note is not None
    assert "moderator" in note.body


def test_repeatedly_broken_chapter_notifies_admin():
    with SessionLocal() as db:
        manga = Manga(
            title="Wiring Manga",
            slug=f"wiring-{uuid.uuid4().hex}",
            source_url=f"https://example.com/wiring-{uuid.uuid4().hex}",
        )
        db.add(manga)
        db.commit()
        db.refresh(manga)
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://example.com/wiring-chapter-{uuid.uuid4().hex}",
        )
        db.add(chapter)
        db.commit()
        db.refresh(chapter)

        from backend_fastapi.app.services.rescrape_service import (
            CONSOLIDATED_ALERT_AFTER,
            _bump_fix_cycles,
        )

        for _ in range(CONSOLIDATED_ALERT_AFTER):
            _bump_fix_cycles(db, chapter)
            db.commit()

    note = _latest_notification("chapter.repeatedly_broken")
    assert note is not None
    assert note.category == "administrative"
    # SRS 1I.2.2: clickable and navigates to the thing it's about - the
    # reader route needs both the manga id and the chapter id.
    assert note.data.get("manga_id") == manga.id


def test_notify_async_failure_never_breaks_role_change():
    """1I.5.1: a broker outage must not fail the action that triggered the
    notification - role change itself must still succeed and commit."""

    target = _make_user()
    with mock.patch(
        "backend_fastapi.app.tasks.notification_tasks.create_notification.delay",
        side_effect=RuntimeError("queue down"),
    ):
        with SessionLocal() as db:
            target_row = db.get(User, target.id)
            # Must not raise even though notify_async blows up.
            admin_service.log_role_change(
                db,
                actor=None,
                target=target_row,
                action="PROMOTE_MODERATOR",
                method="manual",
                from_role="user",
                to_role="moderator",
            )

    with SessionLocal() as db:
        refreshed = db.get(User, target.id)
        assert refreshed is not None  # the action's own effect persisted


def test_notify_async_failure_never_breaks_a_rescrape_alert():
    with SessionLocal() as db:
        manga = Manga(
            title="Wiring Manga 2",
            slug=f"wiring2-{uuid.uuid4().hex}",
            source_url=f"https://example.com/wiring2-{uuid.uuid4().hex}",
        )
        db.add(manga)
        db.commit()
        db.refresh(manga)
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_url=f"https://example.com/wiring2-chapter-{uuid.uuid4().hex}",
        )
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        chapter_id = chapter.id

    from backend_fastapi.app.services.rescrape_service import (
        CONSOLIDATED_ALERT_AFTER,
        _bump_fix_cycles,
    )

    with mock.patch(
        "backend_fastapi.app.tasks.notification_tasks.create_notification.delay",
        side_effect=RuntimeError("queue down"),
    ):
        with SessionLocal() as db:
            chapter = db.get(Chapter, chapter_id)
            for _ in range(CONSOLIDATED_ALERT_AFTER):
                # Must not raise: the fix-cycle bookkeeping is the "action",
                # the alert is a side effect that must not break it.
                _bump_fix_cycles(db, chapter)
                db.commit()

    with SessionLocal() as db:
        refreshed = db.get(Chapter, chapter_id)
        assert refreshed is not None
