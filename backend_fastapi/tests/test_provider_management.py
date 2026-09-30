"""Multi-provider admin management: priority, fallback, verification (SRS 2D)."""

from __future__ import annotations

import uuid

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import SystemProviderInstance, User, UserRole
from backend_fastapi.app.services import provider_management_service as pms


def _clear_providers(db_session, service: str) -> None:
    """Tests share one SQLite DB for the whole run; isolate by service so an
    earlier test's leftover provider can't skew this test's selection math."""

    db_session.query(SystemProviderInstance).filter(
        SystemProviderInstance.service == service
    ).delete(synchronize_session=False)
    db_session.commit()


def _create_user(
    role: UserRole, *, is_main_admin: bool = False, is_secondary: bool = False
) -> str:
    email = f"provmgmt-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        user = User(
            email=email,
            is_active=True,
            role=role,
            is_main_admin=is_main_admin,
            is_secondary_admin=is_secondary,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
    return email


def _login(client, email: str) -> str:
    request = client.post("/api/auth/request-magic-link", json={"email": email})
    assert request.status_code == 200, request.text
    token_value = request.json()["debug_token"]
    consume = client.get(f"/api/auth/magic-link/{token_value}")
    assert consume.status_code == 200, consume.text
    return consume.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# D7: main-admin-only, same boundary as the single-slot system
# --------------------------------------------------------------------------


def test_secondary_admin_cannot_access_provider_management(fastapi_client) -> None:
    email = _create_user(UserRole.SECONDARY, is_secondary=True)
    token = _login(fastapi_client, email)
    headers = _headers(token)

    assert (
        fastapi_client.get("/api/admin/providers", headers=headers).status_code == 403
    )
    assert (
        fastapi_client.post(
            "/api/admin/providers",
            json={
                "provider_name": "Test",
                "service": "ocr",
                "provider_id": "custom",
                "api_url": "https://example.com",
            },
            headers=headers,
        ).status_code
        == 403
    )


def test_main_admin_can_crud_providers(fastapi_client) -> None:
    email = _create_user(UserRole.ADMIN, is_main_admin=True)
    token = _login(fastapi_client, email)
    headers = _headers(token)

    create = fastapi_client.post(
        "/api/admin/providers",
        json={
            "provider_name": "Vision Primary",
            "service": "ocr",
            "provider_id": "custom",
            "api_url": "https://example.com/ocr",
            "priority": 1,
        },
        headers=headers,
    )
    assert create.status_code == 200
    body = create.json()
    assert body["status"] == "inactive"  # not active until verified (2D.5)
    provider_id = body["id"]

    listing = fastapi_client.get("/api/admin/providers?service=ocr", headers=headers)
    assert listing.status_code == 200
    assert any(p["id"] == provider_id for p in listing.json()["providers"])

    update = fastapi_client.patch(
        f"/api/admin/providers/{provider_id}",
        json={"priority": 2},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.json()["priority"] == 2

    # 2D.5: cannot set status to active directly.
    reject = fastapi_client.patch(
        f"/api/admin/providers/{provider_id}",
        json={"status": "active"},
        headers=headers,
    )
    assert reject.status_code == 400

    delete = fastapi_client.delete(
        f"/api/admin/providers/{provider_id}", headers=headers
    )
    assert delete.status_code == 200


# --------------------------------------------------------------------------
# 2D.5 live verification gate
# --------------------------------------------------------------------------


def test_provider_becomes_active_only_after_passing_live_test(db_session) -> None:
    provider = pms.create_provider(
        db_session,
        provider_name="Test Translator",
        service="translation",
        provider_id="custom",
        api_url="https://example.com/translate",
    )
    assert provider.status == "inactive"

    def failing_test(record, decrypt):
        return False, "connection_refused"

    result = pms.verify_provider(db_session, provider.id, live_test=failing_test)
    assert result["ok"] is False
    db_session.refresh(provider)
    assert provider.status == "inactive"

    def passing_test(record, decrypt):
        return True, None

    result = pms.verify_provider(db_session, provider.id, live_test=passing_test)
    assert result["ok"] is True
    db_session.refresh(provider)
    assert provider.status == "active"
    assert provider.last_verified_at is not None


# --------------------------------------------------------------------------
# 2D.3 equal load distribution across providers sharing a priority level
# --------------------------------------------------------------------------


def test_equal_distribution_across_same_priority_level(db_session) -> None:
    _clear_providers(db_session, "translation")
    providers = []
    for i in range(3):
        p = pms.create_provider(
            db_session,
            provider_name=f"Provider {i}",
            service="translation",
            provider_id="custom",
            api_url=f"https://example.com/{i}",
            priority=1,
        )
        pms.verify_provider(db_session, p.id, live_test=lambda r, d: (True, None))
        providers.append(p)

    counts = {p.id: 0 for p in providers}
    for _ in range(30):
        chosen = pms.select_provider(db_session, "translation")
        counts[chosen.id] += 1

    assert sum(counts.values()) == 30
    # Perfectly even: 30 requests / 3 providers = 10 each.
    assert set(counts.values()) == {10}


def test_lower_priority_level_only_used_when_higher_level_unavailable(
    db_session,
) -> None:
    _clear_providers(db_session, "ai")
    primary = pms.create_provider(
        db_session,
        provider_name="Primary",
        service="ai",
        provider_id="custom",
        api_url="https://example.com/primary",
        priority=1,
    )
    backup = pms.create_provider(
        db_session,
        provider_name="Backup",
        service="ai",
        provider_id="custom",
        api_url="https://example.com/backup",
        priority=2,
    )
    pms.verify_provider(db_session, backup.id, live_test=lambda r, d: (True, None))

    # Primary (priority 1) never verified -> stays inactive; backup used.
    chosen = pms.select_provider(db_session, "ai")
    assert chosen.id == backup.id

    pms.verify_provider(db_session, primary.id, live_test=lambda r, d: (True, None))
    chosen = pms.select_provider(db_session, "ai")
    assert chosen.id == primary.id


# --------------------------------------------------------------------------
# 2D.3 failing providers removed from rotation; 2D.4 fallback recorded
# --------------------------------------------------------------------------


def test_provider_marked_failing_after_consecutive_failures_and_recovers(
    db_session,
) -> None:
    _clear_providers(db_session, "ocr")
    provider = pms.create_provider(
        db_session,
        provider_name="Flaky",
        service="ocr",
        provider_id="custom",
        api_url="https://example.com/flaky",
    )
    pms.verify_provider(db_session, provider.id, live_test=lambda r, d: (True, None))
    db_session.refresh(provider)
    assert provider.status == "active"

    for _ in range(pms.CONSECUTIVE_FAILURE_THRESHOLD):
        pms.record_failure(db_session, provider.id, "timeout")
    db_session.refresh(provider)
    assert provider.status == "failing"

    # A failing provider is removed from rotation.
    assert pms.select_provider(db_session, "ocr") is None

    pms.record_success(db_session, provider.id)
    db_session.refresh(provider)
    assert provider.status == "active"
