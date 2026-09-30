"""Disposable-email rule (SRS 1D.2 / 1D.1A.5)."""

from __future__ import annotations

import uuid

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import LoginToken
from backend_fastapi.app.services.disposable_email import (
    is_disposable_domain,
    reload_blocklist,
)


def test_seed_domains_detected():
    assert is_disposable_domain("someone@mailinator.com") is True
    assert is_disposable_domain("x@sub.mailinator.com") is True  # subdomain
    assert is_disposable_domain("real@gmail.com") is False
    assert is_disposable_domain("") is False


def test_env_blocklist_is_updatable_without_deploy(monkeypatch):
    monkeypatch.setenv("DISPOSABLE_EMAIL_DOMAINS", "burner.example, junk.example")
    reload_blocklist()
    try:
        assert is_disposable_domain("a@burner.example") is True
        assert is_disposable_domain("a@junk.example") is True
    finally:
        monkeypatch.delenv("DISPOSABLE_EMAIL_DOMAINS", raising=False)
        reload_blocklist()


def _count_tokens_for_domain(domain: str) -> int:
    session = SessionLocal()
    try:
        return session.query(LoginToken).count()
    finally:
        session.close()


def test_magic_link_request_blocks_disposable_silently(fastapi_client):
    """Blocked domain: identical non-enumerating screen, no link, no account."""
    before = _count_tokens_for_domain("mailinator.com")
    resp = fastapi_client.post(
        "/api/auth/request-magic-link",
        json={"email": f"user-{uuid.uuid4().hex}@mailinator.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Same screen as a legitimate request — no disclosure.
    assert body["message"] == "magic_link_sent"
    # ...but no link was actually issued.
    assert body.get("debug_token") is None
    after = _count_tokens_for_domain("mailinator.com")
    assert after == before  # no LoginToken created


def test_magic_link_request_allows_normal_domain(fastapi_client):
    resp = fastapi_client.post(
        "/api/auth/request-magic-link",
        json={"email": f"user-{uuid.uuid4().hex}@gmail.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "magic_link_sent"
    assert body.get("debug_token")  # a real link was issued
