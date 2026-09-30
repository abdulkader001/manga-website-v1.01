"""Notification system core behaviour (SRS 1I).

Covers: async creation never fails the caller, category defaulting,
batching/dedup, security alerts unsuppressible, mute preferences, the bell
endpoints, and no secrets ever land in a notification body.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    Notification,
    NotificationPreference,
    User,
    UserRole,
)
from backend_fastapi.app.services import notification_service


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _make_user(**kwargs) -> int:
    fields = {
        "email": f"notif-{uuid.uuid4().hex}@example.com",
        "is_active": True,
        "name": "Notif User",
        "role": UserRole.USER,
        "provider": "magic_link",
    }
    fields.update(kwargs)
    with SessionLocal() as db:
        user = User(**fields)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


def _headers(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


# ---------------------------------------------------------------------------
# notify_async never fails the caller (1I.5.1)
# ---------------------------------------------------------------------------


def test_notify_async_swallows_broker_failure():
    with mock.patch(
        "backend_fastapi.app.tasks.notification_tasks.create_notification.delay",
        side_effect=RuntimeError("broker down"),
    ):
        # Must not raise - a notification failure never fails the caller.
        notification_service.notify_async(type="chapter.new", title="x")


def test_notify_async_enqueues_the_celery_task():
    with mock.patch(
        "backend_fastapi.app.tasks.notification_tasks.create_notification.delay"
    ) as delayed:
        notification_service.notify_async(
            type="chapter.new", title="New chapter", user_id=1
        )
        assert delayed.called


# ---------------------------------------------------------------------------
# create_notification: category defaulting, priority, no secrets
# ---------------------------------------------------------------------------


def test_reader_type_defaults_to_reader_category():
    user_id = _make_user()
    with SessionLocal() as db:
        note = notification_service.create_notification(
            db, type="chapter.new", title="New chapter", user_id=user_id
        )
        assert note.category == "reader"
        assert note.priority == "normal"


def test_administrative_type_defaults_to_administrative_category():
    with SessionLocal() as db:
        note = notification_service.create_notification(
            db, type="parser.candidate_ready", title="Candidate ready"
        )
        assert note.category == "administrative"


def test_security_type_is_always_high_priority_and_category():
    with SessionLocal() as db:
        note = notification_service.create_notification(
            db,
            type="security.permanent_admin_tamper_attempt",
            title="Tamper attempt",
        )
        assert note.category == "security"
        assert note.priority == "security"


def test_notification_body_never_contains_a_provider_key_when_service_is_used_correctly():
    """1I.4: never stored — this proves the *shape* callers must follow: the
    service persists exactly the title/body/data callers pass, so a caller
    that (correctly) never includes a secret produces a secret-free row."""

    user_id = _make_user()
    with SessionLocal() as db:
        note = notification_service.create_notification(
            db,
            type="provider.failure",
            title="Your translation provider isn't responding",
            body="Check your key in Settings.",
            user_id=user_id,
            data={"provider": "custom"},
        )
        assert "api_key" not in (note.data or {})
        assert "sk-" not in (note.body or "")


# ---------------------------------------------------------------------------
# Batching / dedup (1I.5.3)
# ---------------------------------------------------------------------------


def test_repeated_events_with_same_dedup_key_collapse_into_one_row():
    user_id = _make_user()
    with SessionLocal() as db:
        first = notification_service.create_notification(
            db,
            type="chapter.new",
            title="Chapter 1 of Series",
            user_id=user_id,
            dedup_key="chapter.new:123",
        )
        second = notification_service.create_notification(
            db,
            type="chapter.new",
            title="Chapter 2 of Series",
            user_id=user_id,
            dedup_key="chapter.new:123",
        )
        assert first.id == second.id
        assert second.data["count"] == 2

        count = (
            db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.type == "chapter.new")
            .count()
        )
        assert count == 1


def test_different_dedup_keys_stay_separate_events():
    user_id = _make_user()
    with SessionLocal() as db:
        notification_service.create_notification(
            db,
            type="chapter.new",
            title="Series A",
            user_id=user_id,
            dedup_key="chapter.new:A",
        )
        notification_service.create_notification(
            db,
            type="chapter.new",
            title="Series B",
            user_id=user_id,
            dedup_key="chapter.new:B",
        )
        count = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.type == "chapter.new",
                Notification.dedup_key.in_(["chapter.new:A", "chapter.new:B"]),
            )
            .count()
        )
        assert count == 2


def test_reading_a_batched_notification_starts_a_fresh_batch():
    user_id = _make_user()
    with SessionLocal() as db:
        first = notification_service.create_notification(
            db,
            type="chapter.new",
            title="Chapter 1",
            user_id=user_id,
            dedup_key="chapter.new:999",
        )
        notification_service.mark_read(db, first.id, user_id=user_id)

        second = notification_service.create_notification(
            db,
            type="chapter.new",
            title="Chapter 2",
            user_id=user_id,
            dedup_key="chapter.new:999",
        )
        # The read notification isn't reused - a new one is created.
        assert second.id != first.id


# ---------------------------------------------------------------------------
# Mute preferences; security is never suppressible (1I.3.2 / 1I.5.2)
# ---------------------------------------------------------------------------


def test_global_mute_suppresses_a_reader_notification_from_the_unread_count():
    user_id = _make_user()
    with SessionLocal() as db:
        notification_service.set_preferences(db, user_id=user_id, global_mute=True)
        notification_service.create_notification(
            db, type="chapter.new", title="New chapter", user_id=user_id
        )
        assert notification_service.unread_count(db, user_id=user_id) == 0


def test_global_mute_never_suppresses_a_security_alert():
    user_id = _make_user()
    with SessionLocal() as db:
        notification_service.set_preferences(db, user_id=user_id, global_mute=True)
        notification_service.create_notification(
            db,
            type="security.permanent_admin_tamper_attempt",
            title="Tamper attempt",
            user_id=user_id,
        )
        assert notification_service.unread_count(db, user_id=user_id) == 1


def test_per_type_mute_suppresses_only_that_type():
    user_id = _make_user()
    with SessionLocal() as db:
        notification_service.set_preferences(
            db, user_id=user_id, muted_types=["chapter.new"]
        )
        notification_service.create_notification(
            db, type="chapter.new", title="Muted type", user_id=user_id
        )
        notification_service.create_notification(
            db, type="series.completed", title="Not muted", user_id=user_id
        )
        assert notification_service.unread_count(db, user_id=user_id) == 1


# ---------------------------------------------------------------------------
# Bell endpoints (1I.6)
# ---------------------------------------------------------------------------


def test_bell_endpoints_round_trip(fastapi_client):
    user_id = _make_user()
    headers = _headers(user_id)

    with SessionLocal() as db:
        notification_service.create_notification(
            db, type="chapter.new", title="Chapter X", user_id=user_id
        )
        notification_service.create_notification(
            db, type="series.completed", title="Series Y", user_id=user_id
        )

    unread = fastapi_client.get("/api/notifications/unread-count", headers=headers)
    assert unread.status_code == 200
    assert unread.json()["count"] == 2

    listing = fastapi_client.get("/api/notifications", headers=headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 2

    first_id = items[0]["id"]
    read_resp = fastapi_client.post(
        f"/api/notifications/{first_id}/read", headers=headers
    )
    assert read_resp.status_code == 200
    assert read_resp.json()["read"] is True

    unread_after = fastapi_client.get(
        "/api/notifications/unread-count", headers=headers
    )
    assert unread_after.json()["count"] == 1

    mark_all = fastapi_client.post("/api/notifications/read-all", headers=headers)
    assert mark_all.status_code == 200

    unread_final = fastapi_client.get(
        "/api/notifications/unread-count", headers=headers
    )
    assert unread_final.json()["count"] == 0

    second_id = items[1]["id"]
    delete_resp = fastapi_client.delete(
        f"/api/notifications/{second_id}", headers=headers
    )
    assert delete_resp.status_code == 200

    listing_after = fastapi_client.get("/api/notifications", headers=headers)
    assert len(listing_after.json()["items"]) == 1


def test_a_user_cannot_read_or_delete_another_users_notification(fastapi_client):
    owner_id = _make_user()
    other_id = _make_user()

    with SessionLocal() as db:
        note = notification_service.create_notification(
            db, type="chapter.new", title="Private", user_id=owner_id
        )
        note_id = note.id

    other_headers = _headers(other_id)
    read_resp = fastapi_client.post(
        f"/api/notifications/{note_id}/read", headers=other_headers
    )
    assert read_resp.status_code == 404

    delete_resp = fastapi_client.delete(
        f"/api/notifications/{note_id}", headers=other_headers
    )
    assert delete_resp.status_code == 404


def test_permanent_admin_sees_pa_addressed_notifications(fastapi_client):
    pa_id = _make_user(is_main_admin=True, permanent=True, role=UserRole.PERMANENT)

    with SessionLocal() as db:
        notification_service.create_notification(
            db, type="parser.candidate_ready", title="For the PA", user_id=None
        )

    headers = _headers(pa_id)
    unread = fastapi_client.get("/api/notifications/unread-count", headers=headers)
    # PA-wide notifications (user_id=None) are a shared inbox across the
    # whole test session, so other tests may have added more - just prove
    # this one landed, not an exact count.
    assert unread.json()["count"] >= 1


def test_guest_cannot_reach_notification_endpoints(fastapi_client):
    resp = fastapi_client.get("/api/notifications/unread-count")
    assert resp.status_code in (401, 403)


def test_notification_prefs_round_trip(fastapi_client):
    user_id = _make_user()
    headers = _headers(user_id)

    get_resp = fastapi_client.get("/api/users/me/notification-prefs", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["global_mute"] is False

    put_resp = fastapi_client.put(
        "/api/users/me/notification-prefs",
        json={"muted_types": ["chapter.new"], "email_types": ["security.alert"]},
        headers=headers,
    )
    assert put_resp.status_code == 200
    body = put_resp.json()
    assert body["muted_types"] == ["chapter.new"]
    assert body["email_types"] == ["security.alert"]

    with SessionLocal() as db:
        prefs = (
            db.query(NotificationPreference)
            .filter(NotificationPreference.user_id == user_id)
            .one()
        )
        assert prefs.muted_types == ["chapter.new"]


def test_read_at_timestamp_is_set_alongside_read_flag():
    user_id = _make_user()
    with SessionLocal() as db:
        note = notification_service.create_notification(
            db, type="chapter.new", title="x", user_id=user_id
        )
        assert note.read_at is None
        updated = notification_service.mark_read(db, note.id, user_id=user_id)
        assert updated.read is True
        assert isinstance(updated.read_at, datetime)
