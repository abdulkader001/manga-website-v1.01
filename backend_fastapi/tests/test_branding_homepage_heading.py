"""The homepage heading is saved with the site's branding (same for everyone).

It used to live in the editing admin's own browser, so visitors never saw a
change. Only the branding power may change it.
"""

from __future__ import annotations

import uuid

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole


def _headers(**fields) -> dict:
    with SessionLocal() as session:
        user = User(
            email=f"bh-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Someone",
            provider="magic_link",
            **fields,
        )
        session.add(user)
        session.commit()
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_the_owner_sets_the_heading_and_every_visitor_sees_it(fastapi_client):
    owner = _headers(role=UserRole.ADMIN, is_main_admin=True, is_secondary_admin=True)
    resp = fastapi_client.post(
        "/api/v1/branding",
        headers=owner,
        json={"homepage_title": "  New this week <b>!</b> ", "homepage_subtitle": "Fresh chapters daily"},
    )
    assert resp.status_code == 200, resp.text
    public = fastapi_client.get("/api/v1/branding").json()
    assert public["homepage_title"] == "New this week !"  # markup stripped
    assert public["homepage_subtitle"] == "Fresh chapters daily"


def test_saving_the_name_keeps_the_heading(fastapi_client):
    owner = _headers(role=UserRole.ADMIN, is_main_admin=True, is_secondary_admin=True)
    fastapi_client.post("/api/v1/branding", headers=owner, json={"homepage_title": "Kept"})
    fastapi_client.post("/api/v1/branding", headers=owner, json={"name": "Site"})
    assert fastapi_client.get("/api/v1/branding").json()["homepage_title"] == "Kept"


def test_guests_and_readers_cannot_change_it(fastapi_client):
    for headers in ({}, _headers(role=UserRole.USER)):
        resp = fastapi_client.post("/api/v1/branding", headers=headers, json={"homepage_title": "Hacked"})
        assert resp.status_code in (401, 403), resp.status_code
    assert fastapi_client.get("/api/v1/branding").json()["homepage_title"] != "Hacked"
