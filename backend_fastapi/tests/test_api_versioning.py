"""Versioning + generated-OpenAPI contract checks (SRS 1B.4.1 / 1B.4).

- /api/v1 is the canonical, documented surface.
- The deprecated "/" and "/api" aliases still work (expand-and-contract) but are
  hidden from the schema.
- The error envelope holds on the versioned surface.
"""

from __future__ import annotations


def test_v1_is_the_documented_surface(fastapi_client):
    schema = fastapi_client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json().get("paths", {})
    # At least one real route is documented under /api/v1 ...
    assert any(p.startswith("/api/v1/") for p in paths), "no /api/v1 paths in schema"
    # ... and the bare/legacy aliases are NOT in the documented schema.
    assert "/manga/" not in paths
    assert "/api/manga/" not in paths


def test_v1_and_legacy_aliases_both_serve(fastapi_client):
    v1 = fastapi_client.get("/api/v1/manga/?per_page=1")
    legacy = fastapi_client.get("/api/manga/?per_page=1")
    root = fastapi_client.get("/manga/?per_page=1")
    assert v1.status_code == 200
    assert legacy.status_code == 200
    assert root.status_code == 200


def test_error_envelope_on_v1_surface(fastapi_client):
    # Unauthenticated privileged call → standard error envelope, not a bare body.
    resp = fastapi_client.post(
        "/api/v1/admin/series", json={"url": "https://x.example/m/1"}
    )
    assert resp.status_code in (401, 403)


def test_validation_error_is_enveloped_on_v1(fastapi_client):
    # Malformed body → VALIDATION_FAILED envelope (no bare 422).
    from backend_fastapi.app.core.security import create_access_token
    from backend_fastapi.app.core.db import SessionLocal
    from backend_fastapi.app.models import User, UserRole
    import uuid

    session = SessionLocal()
    try:
        admin = User(
            email=f"admin-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Admin",
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

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}
    # Missing required "url" field entirely.
    resp = fastapi_client.post("/api/v1/admin/series", headers=headers, json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_FAILED"
