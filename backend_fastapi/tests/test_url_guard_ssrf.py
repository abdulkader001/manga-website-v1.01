"""Regression tests for SSRF hardening of allowlisted hosts (Blind Spot #11)."""

from __future__ import annotations

from backend_fastapi.app.services import url_guard


def test_allowlisted_host_resolving_to_private_ip_is_blocked(monkeypatch):
    """An allowlisted hostname must still be IP-checked (DNS rebinding)."""

    monkeypatch.setattr(url_guard, "_url_allowlist", lambda: ("ocr.example.com",))
    # The allowlisted host resolves to a private address at fetch time.
    monkeypatch.setattr(url_guard, "_host_addresses", lambda host: ["10.0.0.5"])

    error = url_guard.validate_remote_image_url("https://ocr.example.com/x.png")
    assert error == "IP address is not permitted"


def test_allowlisted_host_resolving_to_public_ip_is_allowed(monkeypatch):
    monkeypatch.setattr(url_guard, "_url_allowlist", lambda: ("ocr.example.com",))
    monkeypatch.setattr(url_guard, "_host_addresses", lambda host: ["93.184.216.34"])

    assert url_guard.validate_remote_image_url("https://ocr.example.com/x.png") is None


def test_non_allowlisted_host_rejected_when_allowlist_set(monkeypatch):
    monkeypatch.setattr(url_guard, "_url_allowlist", lambda: ("ocr.example.com",))
    monkeypatch.setattr(url_guard, "_host_addresses", lambda host: ["93.184.216.34"])

    error = url_guard.validate_remote_image_url("https://other.example.com/x.png")
    assert error == "Host is not in the OCR allowlist"


def test_metadata_endpoint_ip_blocked_even_if_allowlisted(monkeypatch):
    """Cloud metadata (link-local 169.254.169.254) must never be reachable."""

    monkeypatch.setattr(url_guard, "_url_allowlist", lambda: ("metadata.internal",))
    monkeypatch.setattr(url_guard, "_host_addresses", lambda host: ["169.254.169.254"])

    error = url_guard.validate_remote_image_url("http://metadata.internal/latest")
    assert error == "IP address is not permitted"
