"""Tests for managing system-level provider credentials via the admin API."""

from __future__ import annotations

from typing import Dict

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import ProviderCredentials, User, UserRole


def _login(client, email: str) -> str:
    request = client.post("/api/auth/request-magic-link", json={"email": email})
    assert request.status_code == 200, request.text
    # Tokens are hash-only in the DB (SRS 1D.1A.3); TESTING returns the plaintext.
    token_value = request.json()["debug_token"]

    consume = client.get(f"/api/auth/magic-link/{token_value}")
    assert consume.status_code == 200, consume.text
    payload = consume.json()
    return payload["access_token"]


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_admin(email: str = "admin-providers@example.com") -> str:
    with SessionLocal() as session:
        admin = session.query(User).filter_by(email=email).one_or_none()
        if admin is None:
            admin = User(
                email=email,
                is_active=True,
                is_main_admin=True,
                role=UserRole.ADMIN,
                provider="magic_link",
            )
            session.add(admin)
            session.commit()
        return admin.email or admin.email_plaintext or email


def _create_secondary_admin(email: str) -> str:
    with SessionLocal() as session:
        admin = session.query(User).filter_by(email=email).one_or_none()
        if admin is None:
            admin = User(
                email=email,
                is_active=True,
                is_main_admin=False,
                is_secondary_admin=True,
                role=UserRole.SECONDARY,
                provider="magic_link",
            )
            session.add(admin)
            session.commit()
        return admin.email or admin.email_plaintext or email


def _provider_record(service: str) -> ProviderCredentials | None:
    with SessionLocal() as session:
        record = (
            session.query(ProviderCredentials)
            .filter_by(provider_name=service, is_system=True)
            .one_or_none()
        )
        if record is None:
            return None
        session.expunge(record)
        return record


@pytest.mark.parametrize("service", ["translation", "ocr"])
def test_system_provider_toggle_preserves_configuration(
    fastapi_client, service: str
) -> None:
    admin_email = _create_admin(email=f"{service}-admin@example.com")
    token = _login(fastapi_client, admin_email)
    headers = _auth_headers(token)

    with SessionLocal() as session:
        session.query(ProviderCredentials).filter_by(
            provider_name=service, is_system=True
        ).delete()
        session.commit()

    payload: Dict[str, object] = {
        "service": service,
        "config": {
            "provider": "custom",
            "apiKey": "secret-key-123",
            "apiUrl": "https://example.com/api",
        },
    }

    enable = fastapi_client.put(
        "/api/admin/system-providers", json=payload, headers=headers
    )
    assert enable.status_code == 200, enable.text
    enabled_providers = enable.json()["providers"]
    assert service in enabled_providers

    stored = _provider_record(service)
    assert stored is not None
    assert stored.enabled is True
    assert stored.provider == "custom"
    assert stored.config.get("api_url") == "https://example.com/api"
    saved_api_key = stored.api_key

    disable = fastapi_client.put(
        "/api/admin/system-providers",
        json={"service": service, "enabled": False},
        headers=headers,
    )
    assert disable.status_code == 200, disable.text
    disabled_payload = disable.json()["providers"]
    assert service not in disabled_payload

    stored_disabled = _provider_record(service)
    assert stored_disabled is not None
    assert stored_disabled.enabled is False
    assert stored_disabled.config.get("api_url") == "https://example.com/api"
    assert stored_disabled.api_key == saved_api_key

    reenable = fastapi_client.put(
        "/api/admin/system-providers",
        json={"service": service, "enabled": True},
        headers=headers,
    )
    assert reenable.status_code == 200, reenable.text
    reenabed_payload = reenable.json()["providers"]
    assert service in reenabed_payload

    stored_enabled = _provider_record(service)
    assert stored_enabled is not None
    assert stored_enabled.enabled is True
    assert stored_enabled.api_key == saved_api_key


def test_enabling_system_provider_requires_configuration(fastapi_client) -> None:
    admin_email = _create_admin(email="missing-config-admin@example.com")
    token = _login(fastapi_client, admin_email)
    headers = _auth_headers(token)

    with SessionLocal() as session:
        session.query(ProviderCredentials).filter_by(
            provider_name="ai", is_system=True
        ).delete()
        session.commit()

    response = fastapi_client.put(
        "/api/admin/system-providers",
        json={"service": "ai", "enabled": True},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "config_required"

    assert _provider_record("ai") is None


def test_secondary_admin_cannot_view_or_edit_system_providers(fastapi_client) -> None:
    """D7 (SRS 1H.11): system provider credentials are Main-Admin-only.

    A Secondary Admin can use translation/OCR under their own quota, but
    must not be able to view or change the system-wide provider API keys.
    """

    secondary_email = _create_secondary_admin("secondary-providers@example.com")
    token = _login(fastapi_client, secondary_email)
    headers = _auth_headers(token)

    listing = fastapi_client.get("/api/admin/system-providers", headers=headers)
    assert listing.status_code == 403

    secret = fastapi_client.get(
        "/api/admin/system-providers/translation/secret", headers=headers
    )
    assert secret.status_code == 403

    update = fastapi_client.put(
        "/api/admin/system-providers",
        json={
            "service": "translation",
            "config": {"apiKey": "secret-key", "apiUrl": "https://example.com/api"},
        },
        headers=headers,
    )
    assert update.status_code == 403
