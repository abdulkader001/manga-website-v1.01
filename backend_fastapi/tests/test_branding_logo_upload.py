"""Branding logo upload rejects decoded-pixel-count bombs (SRS 1H.6)."""

from __future__ import annotations

import io
import uuid

from PIL import Image

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole


def _admin_headers() -> dict:
    with SessionLocal() as session:
        admin = User(
            email=f"branding-admin-{uuid.uuid4().hex}@example.com",
            is_active=True,
            is_main_admin=True,
            role=UserRole.ADMIN,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_id = admin.id
    return {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}


def _png_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(200, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_oversized_dimensions_are_rejected(fastapi_client):
    headers = _admin_headers()
    # 9000x9000 decodes to > _LOGO_MAX_PIXELS (8000x8000) despite a small file.
    payload = _png_bytes(9000, 9000)
    resp = fastapi_client.post(
        "/api/branding/logo",
        files={"file": ("logo.png", payload, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "logo_dimensions_too_large"


def test_normal_logo_is_accepted(fastapi_client):
    headers = _admin_headers()
    payload = _png_bytes(200, 200)
    resp = fastapi_client.post(
        "/api/branding/logo",
        files={"file": ("logo.png", payload, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200
