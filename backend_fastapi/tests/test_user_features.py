"""Integration tests for user-facing and admin features."""

from __future__ import annotations

from typing import Iterable

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import AdminAuditLog, User, UserRole


def _login(client, email: str) -> str:
    request = client.post("/api/auth/request-magic-link", json={"email": email})
    assert request.status_code == 200, request.text
    # Tokens are hash-only in the DB (SRS 1D.1A.3); TESTING returns the plaintext.
    token_value = request.json()["debug_token"]

    consume = client.get(f"/api/auth/magic-link/{token_value}")
    assert consume.status_code == 200, consume.text
    payload = consume.json()
    return payload["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _first(iterable: Iterable[dict], key: str, value) -> dict:
    for item in iterable:
        if item.get(key) == value:
            return item
    raise AssertionError(f"Item with {key}={value!r} not found in {iterable!r}")


def _user_email(user: User) -> str:
    email = getattr(user, "email_plaintext", None) or getattr(user, "email", None)
    if not email:
        raise AssertionError("User email not available for login")
    return email


def test_bookmarks_flow(fastapi_client, sample_data):
    user = sample_data["user"]
    manga = sample_data["manga"]

    token = _login(fastapi_client, _user_email(user))

    headers = _auth_headers(token)
    response = fastapi_client.get("/api/bookmarks", headers=headers)
    assert response.status_code == 200
    assert response.json() == []

    create = fastapi_client.post(
        "/api/bookmarks",
        json={"mangaId": manga.id},
        headers=headers,
    )
    assert create.status_code == 201
    bookmark_id = create.json()["id"]

    listing = fastapi_client.get("/api/bookmarks", headers=headers)
    assert listing.status_code == 200
    items = listing.json()
    assert len(items) == 1
    entry = items[0]
    assert entry["manga_id"] == manga.id
    assert entry["chapter_id"] is None

    delete = fastapi_client.delete(f"/api/bookmarks/{manga.id}", headers=headers)
    assert delete.status_code == 200

    empty = fastapi_client.get("/api/bookmarks", headers=headers)
    assert empty.json() == []

    # Ensure deleting by id of a non-existent bookmark returns 404
    missing = fastapi_client.delete(
        f"/api/bookmarks/by-id/{bookmark_id}", headers=headers
    )
    assert missing.status_code == 404


def test_comments_flow(fastapi_client, sample_data):
    user = sample_data["user"]
    manga = sample_data["manga"]

    token = _login(fastapi_client, _user_email(user))
    headers = _auth_headers(token)

    initial = fastapi_client.get(f"/api/comments/manga/{manga.id}")
    assert initial.status_code == 200
    assert initial.json()["items"] == []
    assert initial.json()["total"] == 0

    create = fastapi_client.post(
        "/api/comments/",
        json={"target_type": "manga", "target_id": manga.id, "content": "Great read!"},
        headers=headers,
    )
    assert create.status_code == 200
    comment = create.json()
    assert comment["content"] == "Great read!"
    assert comment["target_id"] == manga.id

    listing = fastapi_client.get(f"/api/comments/manga/{manga.id}")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    results = body["items"]
    assert len(results) == 1
    assert results[0]["content"] == "Great read!"


def test_manga_read_history_sync(fastapi_client, sample_data):
    user = sample_data["user"]
    manga = sample_data["manga"]
    chapter = sample_data["chapter"]

    token = _login(fastapi_client, _user_email(user))
    headers = _auth_headers(token)

    initial = fastapi_client.get(f"/api/manga/{manga.id}/chapters", headers=headers)
    assert initial.status_code == 200
    chapters = initial.json()
    first = _first(chapters, "id", chapter.id)
    assert first["read"] is False

    detail = fastapi_client.get(
        f"/api/manga/{manga.id}/chapters/{chapter.id}",
        headers=headers,
    )
    assert detail.status_code == 200

    # Reading history lives in the reader's browser (src/utils/library.js);
    # opening a chapter must not create a server-side history row.
    updated = fastapi_client.get(f"/api/manga/{manga.id}/chapters", headers=headers)
    after = _first(updated.json(), "id", chapter.id)
    assert after["read"] is False


def test_admin_user_management_and_audit(fastapi_client, sample_data):
    session = SessionLocal()
    try:
        admin = User(
            email="admin@example.com",
            is_active=True,
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        target = User(
            email="target@example.com",
            is_active=True,
            provider="magic_link",
        )
        session.add_all([admin, target])
        session.commit()
        session.refresh(admin)
        session.refresh(target)
    finally:
        session.close()

    admin_token = _login(fastapi_client, "admin@example.com")
    headers = _auth_headers(admin_token)

    status = fastapi_client.get("/api/admin/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["authenticated"] is True

    users = fastapi_client.get("/api/admin/users", headers=headers)
    assert users.status_code == 200
    user_payloads = users.json()["items"]
    assert any(u["id"] == target.id for u in user_payloads)

    promote = fastapi_client.post(
        f"/api/admin/promote/{target.id}",
        json={"role": "secondary_admin"},
        headers=headers,
    )
    assert promote.status_code == 200
    assert promote.json()["user"]["is_secondary_admin"] is True

    demote = fastapi_client.post(
        f"/api/admin/demote/{target.id}",
        headers=headers,
    )
    assert demote.status_code == 200
    assert demote.json()["user"]["role"] == UserRole.USER.value

    promote_email = fastapi_client.post(
        "/api/admin/promote-by-email",
        json={"email": _user_email(target), "role": "secondary_admin"},
        headers=headers,
    )
    assert promote_email.status_code == 200

    # 1F.2.4: there is no API route that assigns the Permanent Administrator
    # role — the old POST /admin/permanent/{id} escalation path is gone.
    permanent = fastapi_client.post(
        f"/api/admin/permanent/{target.id}",
        headers=headers,
    )
    assert permanent.status_code == 404

    # A non-permanent secondary admin demotes cleanly by email.
    demote_email = fastapi_client.post(
        "/api/admin/demote-by-email",
        json={"email": _user_email(target)},
        headers=headers,
    )
    assert demote_email.status_code == 200

    audit = fastapi_client.get("/api/admin/audit/logs", headers=headers)
    assert audit.status_code == 200
    entries = audit.json()
    assert len(entries) >= 4
    assert any(entry.get("operator") == "admin_router" for entry in entries)
    assert all("timestamp" in entry for entry in entries)

    # F-7: POST /admin/promote/{id} used to write no admin_audit_logs row at
    # all while its demote sibling did -- an auditor filtering by
    # action="PROMOTE" found nothing even though a promotion had just
    # happened. Both the by-id and by-email variants must now appear under
    # their own action name, not just under log_role_change's separate
    # "admin.promote" taxonomy.
    actions = [entry.get("action") for entry in entries]
    assert actions.count("PROMOTE") >= 2  # promote/{id} + promote-by-email
    assert actions.count("DEMOTE") >= 2  # demote/{id} + demote-by-email

    # Ensure audit entries persisted
    with SessionLocal() as verify:
        count = verify.query(AdminAuditLog).count()
        assert count >= len(entries)


def test_user_settings_sync_across_sessions(fastapi_client, sample_data):
    """Provider preferences and language persist on the account so they follow
    the user to another device/session (spec items #2 and #12)."""

    user = sample_data["user"]
    email = _user_email(user)

    # Device A: configure OCR + AI providers and a preferred output language.
    token_a = _login(fastapi_client, email)
    headers_a = _auth_headers(token_a)

    update = fastapi_client.post(
        "/api/user/settings",
        json={
            "language": "ja",
            "apiProviders": {
                "ocr": {
                    "provider": "custom",
                    "apiKey": "ocr-secret",
                    "apiUrl": "https://ocr.example/api",
                },
                "ai": {
                    "provider": "custom",
                    "apiKey": "ai-secret",
                    "apiUrl": "https://ai.example/api",
                    "model": "vision-1",
                },
            },
        },
        headers=headers_a,
    )
    assert update.status_code == 200, update.text
    body = update.json()
    assert body["language"] == "ja"
    assert body["api_keys"]["ocr"]["provider"] == "custom"
    assert body["api_keys"]["ocr"]["apiUrl"] == "https://ocr.example/api"
    # Secrets are never returned in clear text.
    assert body["api_keys"]["ocr"]["apiKey"] != "ocr-secret"
    assert body["api_keys"]["ai"]["model"] == "vision-1"

    # Device B: a fresh session for the same account sees the saved settings.
    token_b = _login(fastapi_client, email)
    headers_b = _auth_headers(token_b)

    fetched = fastapi_client.get("/api/user/settings", headers=headers_b)
    assert fetched.status_code == 200, fetched.text
    data = fetched.json()
    assert data["language"] == "ja"
    assert data["api_keys"]["ocr"]["provider"] == "custom"
    assert data["api_keys"]["ocr"]["apiUrl"] == "https://ocr.example/api"
    assert data["api_keys"]["ai"]["provider"] == "custom"
    assert data["api_keys"]["ai"]["apiUrl"] == "https://ai.example/api"
    assert data["api_keys"]["ai"]["model"] == "vision-1"
