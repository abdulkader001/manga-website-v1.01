"""Regression tests for Phase 3 reliability fixes (items 13, 14, 16, 22, 24)."""

from __future__ import annotations

from backend_fastapi.app.bootstrap.timeout import TimeoutMiddleware
from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services import ocr_workflow
from backend_fastapi.app.utils.email_crypto import decrypt_secret
from _support.db_reset import clear_users

# ---- Item 13: long-running routes are exempt from the global timeout ----


def test_timeout_middleware_exempts_long_routes():
    mw = TimeoutMiddleware(app=None, timeout_seconds=5.0, exempt_timeout_seconds=120.0)
    assert mw._timeout_for("/api/manga") == 5.0
    assert mw._timeout_for("/api/translation/text") == 120.0
    assert mw._timeout_for("/api/ocr/translate-overlay") == 120.0


def test_timeout_middleware_can_disable_timeout_for_exempt():
    mw = TimeoutMiddleware(app=None, timeout_seconds=5.0, exempt_timeout_seconds=None)
    assert mw._timeout_for("/api/translation/text") is None
    assert mw._timeout_for("/api/manga") == 5.0


# ---- Item 14: overlay translation runs concurrently, order-preserving ----


class _EchoTranslator:
    def translate(self, text, *, source_lang, target_lang, provider_config=None):
        return f"[{target_lang}]{text}"


class _FlakyTranslator:
    def translate(self, text, *, source_lang, target_lang, provider_config=None):
        if text == "boom":
            raise RuntimeError("provider down")
        return text.upper()


def test_translate_overlay_items_preserves_order_and_skips_empty():
    items = [{"text": "a"}, {"text": "   "}, {"text": "b"}]
    boxes, metadata, errors = ocr_workflow.translate_overlay_items(
        items,
        page={"width": 100, "height": 100},
        metadata={},
        translation_service=_EchoTranslator(),
        provider_config=None,
        target_lang="es",
    )
    assert items[0]["translated"] == "[es]a"
    assert "translated" not in items[1]  # blank stays blank
    assert items[2]["translated"] == "[es]b"
    assert errors == []


def test_translate_overlay_items_records_failures_and_keeps_original():
    items = [{"text": "ok"}, {"text": "boom"}]
    ocr_workflow.translate_overlay_items(
        items,
        page={"width": 10, "height": 10},
        metadata={},
        translation_service=_FlakyTranslator(),
        provider_config=None,
        target_lang="es",
    )
    assert items[0]["translated"] == "OK"
    # Failed box keeps its original text and is not marked translated.
    assert items[1].get("translated") in (None, "boom")


# ---- Item 24: OAuth tokens are encrypted at rest ----


def test_oauth_tokens_encrypted_at_rest(fastapi_app):
    session = SessionLocal()
    try:
        clear_users(session)
        user = User(email="oauth@example.com", role=UserRole.USER, provider="google")
        user.access_token = "ya29.super-secret-access-token"
        user.refresh_token = "1//refresh-secret"
        session.add(user)
        session.commit()
        uid = user.id
    finally:
        session.close()

    session = SessionLocal()
    try:
        refreshed = session.get(User, uid)
        # Ciphertext at rest differs from plaintext...
        assert refreshed.access_token_encrypted != "ya29.super-secret-access-token"
        assert refreshed.refresh_token_encrypted != "1//refresh-secret"
        # ...but the property round-trips to the original value.
        assert refreshed.access_token == "ya29.super-secret-access-token"
        assert refreshed.refresh_token == "1//refresh-secret"
        # And the stored ciphertext really decrypts.
        assert (
            decrypt_secret(refreshed.access_token_encrypted)
            == "ya29.super-secret-access-token"
        )
    finally:
        session.close()
