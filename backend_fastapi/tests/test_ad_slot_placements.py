"""Tests for admin-assignable ad slot placements, ordering and sizing.

Placements are what let an admin put an ad on every page (including every
chapter) without a developer editing page code, so the contract the frontend
relies on -- filterable, ordered, size-carrying slot payloads -- is pinned here.
"""

from __future__ import annotations

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import AdSlot, User, UserRole
from backend_fastapi.app.services.ad_placements import (
    PLACEMENT_KEYS,
    is_valid_placement,
)

from _support.db_reset import clear_users


def _admin_headers() -> dict[str, str]:
    session = SessionLocal()
    try:
        session.query(AdSlot).delete()
        clear_users(session)
        admin = User(
            email="placement-admin@example.com",
            is_active=True,
            name="Placement Admin",
            username="placementadmin",
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
    return {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}


def test_global_placements_are_part_of_the_catalogue():
    """The site-wide placements the app shell mounts must exist."""

    assert "global_top" in PLACEMENT_KEYS
    assert "global_bottom" in PLACEMENT_KEYS
    assert is_valid_placement("global_top")
    # Empty means "staged but not placed", which is allowed.
    assert is_valid_placement(None)
    assert is_valid_placement("")
    assert not is_valid_placement("not_a_real_placement")


def test_placement_catalogue_endpoint_lists_choices(fastapi_client):
    resp = fastapi_client.get("/api/ads/placements")
    assert resp.status_code == 200
    payload = resp.json()
    keys = {item["key"] for item in payload}
    assert "global_top" in keys
    assert all("label" in item for item in payload)


def test_create_slot_with_placement_and_size(fastapi_client):
    headers = _admin_headers()

    resp = fastapi_client.post(
        "/api/ad-slots",
        headers=headers,
        json={
            "name": "Site-wide banner",
            "slot_key": "sitewide-banner",
            "placement": "global_top",
            "position": 2,
            "height_px": 120,
            "max_width_px": 970,
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["placement"] == "global_top"
    assert created["position"] == 2
    assert created["height_px"] == 120
    assert created["max_width_px"] == 970


def test_unknown_placement_is_rejected(fastapi_client):
    headers = _admin_headers()

    resp = fastapi_client.post(
        "/api/ad-slots",
        headers=headers,
        json={
            "name": "Typo slot",
            "slot_key": "typo-slot",
            "placement": "gloabl_top",
        },
    )
    assert resp.status_code == 400


def test_public_slots_filter_by_placement_and_sort_by_position(fastapi_client):
    headers = _admin_headers()

    for name, key, placement, position in [
        ("Second", "second-slot", "global_top", 5),
        ("First", "first-slot", "global_top", 1),
        ("Elsewhere", "other-slot", "chapter_bottom", 0),
    ]:
        resp = fastapi_client.post(
            "/api/ad-slots",
            headers=headers,
            json={
                "name": name,
                "slot_key": key,
                "placement": placement,
                "position": position,
            },
        )
        assert resp.status_code == 201

    resp = fastapi_client.get("/api/ads/slots", params={"placement": "global_top"})
    assert resp.status_code == 200
    slots = resp.json()
    assert [slot["name"] for slot in slots] == ["First", "Second"]
    assert all(slot["placement"] == "global_top" for slot in slots)

    # Unfiltered listing still returns everything, and carries placement data
    # so the frontend can group client-side from one cached request.
    everything = fastapi_client.get("/api/ads/slots").json()
    assert len(everything) == 3
    assert {slot["placement"] for slot in everything} == {
        "global_top",
        "chapter_bottom",
    }


def test_update_can_move_and_resize_a_slot(fastapi_client):
    headers = _admin_headers()

    created = fastapi_client.post(
        "/api/ad-slots",
        headers=headers,
        json={"name": "Movable", "slot_key": "movable", "placement": "homepage_top"},
    ).json()

    resp = fastapi_client.patch(
        f"/api/ad-slots/{created['id']}",
        headers=headers,
        json={"placement": "global_bottom", "height_px": 250},
    )
    assert resp.status_code == 200
    assert resp.json()["placement"] == "global_bottom"
    assert resp.json()["height_px"] == 250

    # Clearing the placement stages the slot without deleting it.
    cleared = fastapi_client.patch(
        f"/api/ad-slots/{created['id']}",
        headers=headers,
        json={"placement": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["placement"] is None


def test_non_positive_size_is_stored_as_unset(fastapi_client):
    headers = _admin_headers()

    created = fastapi_client.post(
        "/api/ad-slots",
        headers=headers,
        json={
            "name": "Zero height",
            "slot_key": "zero-height",
            "placement": "global_top",
            "height_px": 0,
        },
    ).json()
    assert created["height_px"] is None
