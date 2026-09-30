from __future__ import annotations
import io
import json
import os
from uuid import uuid4

from PIL import Image

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import (
    FooterSettings,
    Manga,
    ProviderCredentials,
    UserAPIKey,
    ScrapingJob,
    Setting,
    SystemSettings,
    User,
    UserRole,
)
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.services.integration_key_vault import IntegrationKeyVault


def _create_admin_headers(
    *,
    is_main_admin: bool = True,
    is_secondary_admin: bool = True,
    role: UserRole = UserRole.ADMIN,
) -> dict[str, str]:
    session = SessionLocal()
    try:
        email = f"admin-{uuid4().hex}@example.com"
        session.query(User).filter(User.email == email).delete()
        admin = User(
            email=email,
            is_active=True,
            name="Config Admin",
            role=role,
            is_main_admin=is_main_admin,
            is_secondary_admin=is_secondary_admin,
            provider="magic_link",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        token = create_access_token(str(admin.id))
        return {"Authorization": f"Bearer {token}"}
    finally:
        session.close()


def _create_secondary_admin_headers() -> dict[str, str]:
    return _create_admin_headers(
        is_main_admin=False,
        is_secondary_admin=True,
        role=UserRole.SECONDARY,
    )


def _create_user_headers(email: str | None = None) -> tuple[dict[str, str], int]:
    session = SessionLocal()
    try:
        if email is None:
            email = f"integration-{uuid4().hex}@example.com"
        session.query(User).filter(User.email == email).delete()
        user = User(
            email=email,
            is_active=True,
            name="Integration User",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        token = create_access_token(str(user.id))
        return {"Authorization": f"Bearer {token}"}, user.id
    finally:
        session.close()


def test_admin_settings_reflect_env(fastapi_client, monkeypatch):
    headers = _create_admin_headers()

    monkeypatch.setenv("ALLOW_USER_OCR_API", "true")
    monkeypatch.setenv("ALLOW_USER_TRANSLATION_API", "0")

    resp = fastapi_client.get("/api/admin/settings", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {
        "ALLOW_USER_OCR_API": True,
        "ALLOW_USER_TRANSLATION_API": False,
    }


def test_branding_post_supports_react_client(fastapi_client):
    session = SessionLocal()
    try:
        session.query(Setting).filter(Setting.key == "branding").delete()
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers()
    payload = {
        "logo": "https://cdn.example.com/logo.png",
        "socialLinks": {"twitter": "https://x.com/site"},
    }
    resp = fastapi_client.post("/api/branding", headers=headers, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["branding"]["logo"] == "https://cdn.example.com/logo.png"
    assert body["branding"]["socialLinks"]["twitter"] == "https://x.com/site"

    fetched = fastapi_client.get("/api/branding")
    assert fetched.status_code == 200
    assert fetched.json()["logo"] == "https://cdn.example.com/logo.png"


def _generate_logo(color: str = "red") -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (32, 32), color=color)
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_branding_logo_upload_supports_cleanup_tokens(fastapi_client):
    headers = _create_admin_headers()

    first_buffer = _generate_logo("red")
    resp = fastapi_client.post(
        "/api/branding/logo",
        headers=headers,
        files=[("file", ("logo.png", first_buffer, "image/png"))],
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["logo"].startswith("/branding/assets/")
    assert body["logoUrl"] == body["logo"]
    assert any(token.startswith("branding:") for token in body.get("cleanupTokens", []))

    asset = fastapi_client.get(body["logo"])
    assert asset.status_code == 200

    cleanup_payload = json.dumps(body["cleanupTokens"])
    second_bytes = _generate_logo("blue")
    boundary = "----pytestbrandingboundary"
    body_prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="cleanup"\r\n\r\n'
        f"{cleanup_payload}\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="logo2.png"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode("utf-8")
    body_suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    payload = body_prefix + second_bytes + body_suffix
    combined_headers = {
        **headers,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    second = fastapi_client.request(
        "POST",
        "/api/branding/logo",
        headers=combined_headers,
        content=payload,
    )

    assert second.status_code == 200, second.json()
    second_body = second.json()
    assert second_body["logo"].startswith("/branding/assets/")
    assert second_body["logo"] != body["logo"]

    removed = fastapi_client.get(body["logo"])
    assert removed.status_code == 404


def test_branding_logo_upload_rejects_invalid_payloads(fastapi_client):
    headers = _create_admin_headers()

    bad_resp = fastapi_client.post(
        "/api/branding/logo",
        headers=headers,
        files={"file": ("logo.txt", io.BytesIO(b"not an image"), "text/plain")},
    )

    assert bad_resp.status_code == 400
    detail = bad_resp.json().get("error", {}).get("message")
    assert detail in {"invalid_logo_type", "invalid_logo"}


def test_footer_post_supports_react_client(fastapi_client):
    session = SessionLocal()
    try:
        session.query(FooterSettings).delete()
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers()
    resp = fastapi_client.post(
        "/api/footer",
        headers=headers,
        json={
            "contact": "Contact us",
            "terms": "https://example.com/terms",
            "privacy": "https://example.com/privacy",
            "socials": [{"label": "GitHub", "url": "https://github.com/org"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["footer"]["contact"] == "Contact us"
    assert body["footer"]["socials"][0]["label"] == "GitHub"

    fetched = fastapi_client.get("/api/footer")
    assert fetched.status_code == 200
    assert fetched.json()["contact"] == "Contact us"


def test_admin_ads_routes_allow_update(fastapi_client):
    session = SessionLocal()
    try:
        session.query(Setting).filter(Setting.key == "ads_config").delete()
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers()
    config = fastapi_client.get("/api/admin/ads", headers=headers)
    assert config.status_code == 200
    assert "global" in config.json()

    payload = {"global": {"network": "adnet", "api_url": "https://ads.example.com"}}
    updated = fastapi_client.post("/api/admin/ads", headers=headers, json=payload)
    assert updated.status_code == 200
    assert updated.json()["global"]["network"] == "adnet"

    roundtrip = fastapi_client.get("/api/admin/ads", headers=headers)
    assert roundtrip.status_code == 200
    assert roundtrip.json()["global"]["network"] == "adnet"


def test_main_admin_can_view_plaintext_provider_secret(fastapi_client):
    secret = "super-secret"
    vault = IntegrationKeyVault.from_secret(os.environ["INTEGRATIONS_SECRET"])

    session = SessionLocal()
    try:
        session.query(ProviderCredentials).filter(
            ProviderCredentials.provider_name == "ocr",
            ProviderCredentials.is_system.is_(True),
        ).delete()
        record = ProviderCredentials(
            provider_name="ocr",
            provider="custom",
            api_key=vault.encrypt(secret),
            config={"provider_id": "custom", "api_url": "https://ocr.example.com"},
            is_system=True,
            enabled=True,
        )
        session.add(record)
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers()
    resp = fastapi_client.get("/api/admin/system-providers/ocr/secret", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["apiKeyPlaintext"] == secret
    assert body["apiKeyMasked"].endswith(secret[-4:])
    assert all(char == "*" for char in body["apiKeyMasked"][:-4])
    assert body["service"] == "ocr"


def test_users_only_receive_masked_integration_keys(fastapi_client):
    secret = "user-secret"
    vault = IntegrationKeyVault.from_secret(os.environ["INTEGRATIONS_SECRET"])

    headers, user_id = _create_user_headers()

    session = SessionLocal()
    try:
        session.query(UserAPIKey).filter(UserAPIKey.user_id == user_id).delete()
        record = UserAPIKey(
            user_id=user_id,
            provider="ocr",
            api_key=vault.encrypt(secret),
            config={"provider_id": "custom", "api_url": "https://ocr.example.com"},
        )
        session.add(record)
        session.commit()
    finally:
        session.close()

    resp = fastapi_client.get("/api/integrations/list", headers=headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()["integrations"]["ocr"]
    assert payload["apiKey"] != secret
    assert payload["apiKey"].endswith(secret[-4:])
    assert all(char == "*" for char in payload["apiKey"][:-4])


def test_main_admin_can_update_system_provider(fastapi_client):
    session = SessionLocal()
    try:
        session.query(ProviderCredentials).filter(
            ProviderCredentials.is_system.is_(True)
        ).delete()
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers()
    payload = {
        "service": "ocr",
        "enabled": True,
        "config": {
            "provider": "custom",
            "apiKey": "secret-key",
            "apiUrl": "https://api.example.com/ocr",
        },
    }

    response = fastapi_client.put(
        "/api/admin/system-providers",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "providers" in body


def test_main_admin_can_update_system_settings(fastapi_client):
    session = SessionLocal()
    try:
        session.query(SystemSettings).delete()
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers()
    response = fastapi_client.patch(
        "/api/admin/system-settings",
        headers=headers,
        json={"local_ocr_enabled": True, "local_ocr_engine": "tesseract"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["system"]["localOcrEnabled"] is True
    assert body["system"]["localOcrEngine"] == "tesseract"


def test_secondary_admin_cannot_update_system_provider(fastapi_client):
    headers = _create_secondary_admin_headers()
    payload = {
        "service": "ocr",
        "enabled": True,
        "config": {
            "provider": "custom",
            "apiKey": "secondary-key",
            "apiUrl": "https://api.example.com/ocr",
        },
    }

    response = fastapi_client.put(
        "/api/admin/system-providers",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Main admin privileges required"


def test_secondary_admin_cannot_update_system_settings(fastapi_client):
    headers = _create_secondary_admin_headers()
    response = fastapi_client.patch(
        "/api/admin/system-settings",
        headers=headers,
        json={"local_ocr_enabled": False},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Main admin privileges required"


def test_secondary_admin_cannot_update_ads_config(fastapi_client):
    headers = _create_secondary_admin_headers()
    response = fastapi_client.post(
        "/api/admin/ads",
        headers=headers,
        json={"global": {"network": "adnet", "api_url": "https://ads.example.com"}},
    )

    assert response.status_code == 403
    assert response.json()["error"]["message"] == "Main admin privileges required"


def test_admin_series_preview_and_creation(fastapi_client):
    session = SessionLocal()
    try:
        session.query(ScrapingJob).delete()
        session.query(Manga).filter(
            Manga.source_url == "https://example.com/series/new"
        ).delete()
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers()
    preview = fastapi_client.post(
        "/api/admin/series/scrape",
        headers=headers,
        json={"url": "https://example.com/series/new"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["series"]["source_url"] == "https://example.com/series/new"

    # Add example.com to ApprovedSourceDomains to avoid URL validation failure
    session = SessionLocal()
    try:
        from backend_fastapi.app.models import ApprovedSourceDomain

        domain_entry = (
            session.query(ApprovedSourceDomain).filter_by(domain="example.com").first()
        )
        if not domain_entry:
            domain_entry = ApprovedSourceDomain(
                base_url="https://example.com",
                domain="example.com",
                label="Test Domain",
            )
            session.add(domain_entry)
            session.commit()
    finally:
        session.close()

    from unittest import mock

    with mock.patch(
        "backend_fastapi.app.services.universal_scraper.scrape_series_by_url"
    ) as mock_delay:
        # Mock what the legacy function returned, since we bypassed the celery mock
        mock_delay.return_value = {
            "job_id": 999,
            "source_url": "https://example.com/series/new",
            "status": "queued",
            "job": {"id": 999, "source_url": "https://example.com/series/new"},
        }

        created = fastapi_client.post(
            "/api/admin/series",
            headers=headers,
            json={"url": "https://example.com/series/new"},
        )

        assert created.status_code == 201
        job_body = created.json()
        assert job_body["job"]["source_url"] == "https://example.com/series/new"
        assert mock_delay.called

        mock_delay.reset_mock()

        # Insert a job manually to trigger deduplication check
        session = SessionLocal()
        try:
            job = ScrapingJob(
                source_url="https://example.com/series/new", status="queued"
            )
            session.add(job)
            session.commit()
            session.refresh(job)
        finally:
            session.close()

        # Deduplicate
        duplicate = fastapi_client.post(
            "/api/admin/series",
            headers=headers,
            json={"url": "https://example.com/series/new"},
        )

        # Deduplication now returns the standard error envelope (SRS 1B.4.3):
        # DUPLICATE_MANGA_URL maps to HTTP 409.
        assert duplicate.status_code == 409
        body = duplicate.json()
        assert body["success"] is False
        assert body["error"]["code"] == "DUPLICATE_MANGA_URL"


def test_secondary_admin_can_create_series(fastapi_client):
    session = SessionLocal()
    try:
        session.query(ScrapingJob).delete()
        session.query(Manga).filter(
            Manga.source_url == "https://example.com/series/secondary"
        ).delete()
        session.commit()
    finally:
        session.close()

    headers = _create_admin_headers(
        is_main_admin=False,
        is_secondary_admin=True,
        role=UserRole.SECONDARY,
    )

    from unittest import mock

    with mock.patch(
        "backend_fastapi.app.services.universal_scraper.scrape_series_by_url"
    ) as mock_delay:
        mock_delay.return_value = {
            "job_id": 999,
            "source_url": "https://example.com/series/secondary",
            "status": "queued",
            "job": {"id": 999, "source_url": "https://example.com/series/secondary"},
        }
        response = fastapi_client.post(
            "/api/admin/series",
            headers=headers,
            json={"url": "https://example.com/series/secondary"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["job"]["source_url"] == "https://example.com/series/secondary"
        assert mock_delay.called


def test_secondary_admin_cannot_promote_secondary_admin(fastapi_client):
    session = SessionLocal()
    try:
        session.query(User).filter(
            User.email == "target-secondary@example.com"
        ).delete()
        target = User(
            email="target-secondary@example.com",
            is_active=True,
            name="Target User",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(target)
        session.commit()
        session.refresh(target)
        target_id = target.id
    finally:
        session.close()

    headers = _create_admin_headers(
        is_main_admin=False,
        is_secondary_admin=True,
        role=UserRole.SECONDARY,
    )

    response = fastapi_client.post(
        "/api/admin/promote-secondary",
        headers=headers,
        json={"user_id": target_id},
    )

    # Denied by the permission engine (promote_secondary defaults to the
    # Permanent Administrator alone) via the standard error envelope (1B.4.2).
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
