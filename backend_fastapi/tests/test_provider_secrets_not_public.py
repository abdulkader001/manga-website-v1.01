"""F-89: provider secrets never leave the server.

The audit reproduced it: a translation provider saved with the header
``api-key: <secret>`` was readable by anyone at ``GET /config/providers``,
along with its endpoint and the key's last four characters.
"""

from __future__ import annotations

import json
import uuid

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import ProviderCredentials, User, UserRole

SECRET = "AZURE-SECRET-VALUE-123"
KEY = "sk-test-abcdef7890"
URL = "https://gateway.internal.example/openai"


def _main_admin() -> dict:
    with SessionLocal() as session:
        admin = User(
            email=f"f89-{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        return {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}


def _save_provider(client, headers: dict) -> dict:
    with SessionLocal() as session:
        session.query(ProviderCredentials).filter_by(provider_name="translation", is_system=True).delete()
        session.commit()
    response = client.put(
        "/api/v1/admin/system-providers",
        json={
            "service": "translation",
            "config": {"provider": "custom", "apiKey": KEY, "apiUrl": URL, "headers": {"api-key": SECRET}},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_anonymous_sees_no_provider_details(fastapi_client):
    Base.metadata.create_all(bind=engine)
    _save_provider(fastapi_client, _main_admin())

    for path in ("/api/v1/config/providers", "/api/config/providers", "/config/providers"):
        response = fastapi_client.get(path)
        if response.status_code == 404:
            continue
        assert response.status_code == 200, (path, response.text)
        body = response.json()
        text = json.dumps(body)
        assert SECRET not in text and URL not in text and "7890" not in text and "api-key" not in text, path
        assert set(body) == {"availableServices", "local"}
        assert "translation" in body["availableServices"]


def test_admin_responses_show_header_names_not_values(fastapi_client):
    Base.metadata.create_all(bind=engine)
    headers = _main_admin()
    saved = _save_provider(fastapi_client, headers)
    listed = fastapi_client.get("/api/v1/admin/system-providers", headers=headers).json()
    for body in (saved, listed):
        assert SECRET not in json.dumps(body)
        assert body["providers"]["translation"]["headers"] == ["api-key"]
