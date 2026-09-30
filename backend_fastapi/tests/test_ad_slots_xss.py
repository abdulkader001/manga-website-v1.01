"""Regression tests for stored-XSS sanitization of ad slot HTML (C4 / Blind Spot #2)."""

from __future__ import annotations

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import AdSlot, User, UserRole
from backend_fastapi.app.utils.sanitizer import sanitize_ad_html
from _support.db_reset import clear_users

XSS_PAYLOAD = (
    '<div>Buy now</div><script>alert("pwned")</script>'
    "<img src=x onerror=alert(1)>"
    '<a href="javascript:alert(2)">click</a>'
)


def _admin_headers() -> tuple[dict[str, str], int]:
    session = SessionLocal()
    try:
        session.query(AdSlot).delete()
        clear_users(session)
        admin = User(
            email="ad-admin@example.com",
            is_active=True,
            name="Ad Admin",
            username="adadmin",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_id = admin.id
    finally:
        session.close()
    return {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}, admin_id


def _assert_no_active_content(html: str | None) -> None:
    assert html is not None
    lowered = html.lower()
    assert "<script" not in lowered
    assert "onerror" not in lowered
    assert "javascript:" not in lowered


def test_sanitize_ad_html_strips_script_and_handlers():
    cleaned = sanitize_ad_html(XSS_PAYLOAD)
    _assert_no_active_content(cleaned)
    # Legitimate container markup is preserved.
    assert "<div>" in cleaned


def test_create_ad_slot_strips_xss_on_save_and_get(fastapi_client):
    headers, _ = _admin_headers()

    resp = fastapi_client.post(
        "/api/ad-slots",
        headers=headers,
        json={
            "name": "Hero",
            "slot_key": "hero-xss",
            "html_code": XSS_PAYLOAD,
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    _assert_no_active_content(created["html_code"])
    slot_id = created["id"]

    # The stored value (not just the response) must be sanitized.
    session = SessionLocal()
    try:
        stored = session.get(AdSlot, slot_id)
        assert stored is not None
        _assert_no_active_content(stored.html_code)
    finally:
        session.close()

    # And it must remain sanitized when served back on the list endpoint.
    listing = fastapi_client.get("/api/ad-slots")
    assert listing.status_code == 200
    slots = {slot["id"]: slot for slot in listing.json()}
    assert slot_id in slots
    _assert_no_active_content(slots[slot_id]["html_code"])


def test_update_ad_slot_strips_xss(fastapi_client):
    headers, _ = _admin_headers()

    created = fastapi_client.post(
        "/api/ad-slots",
        headers=headers,
        json={"name": "Sidebar", "slot_key": "sidebar-xss", "html_code": "<p>ok</p>"},
    ).json()
    slot_id = created["id"]

    # Update via the "html" alias field.
    resp = fastapi_client.patch(
        f"/api/ad-slots/{slot_id}",
        headers=headers,
        json={"html": XSS_PAYLOAD},
    )
    assert resp.status_code == 200
    _assert_no_active_content(resp.json()["html_code"])

    # Update via the canonical "html_code" field.
    resp2 = fastapi_client.patch(
        f"/api/ad-slots/{slot_id}",
        headers=headers,
        json={"html_code": XSS_PAYLOAD},
    )
    assert resp2.status_code == 200
    _assert_no_active_content(resp2.json()["html_code"])

    session = SessionLocal()
    try:
        stored = session.get(AdSlot, slot_id)
        _assert_no_active_content(stored.html_code)
    finally:
        session.close()
