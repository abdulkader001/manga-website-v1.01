"""User-facing translation failure/notice messages (SRS 1H.8.2).

Covers: no provider configured; credential rejected with no usable
fallback; a fallback silently used is now surfaced to the caller.
"""

from __future__ import annotations

from unittest import mock

from backend_fastapi.app.services.translation_service import (
    TranslationProviderError,
    TranslationService,
)


def test_no_provider_configured_message(fastapi_client, auth_headers, monkeypatch):
    # Isolation: a system provider configured by another test (e.g.
    # test_system_providers.py) both sets the module-level singleton and
    # leaves a "translation" entry in the shared provider registry for the
    # rest of the session, so force both back to unconfigured here
    # regardless of test order.
    from backend_fastapi.app.api.routers import translation as translation_router

    monkeypatch.setattr(translation_router, "translation_service", None)
    registry = getattr(fastapi_client.app.state, "provider_registry", None)
    if registry is not None:
        monkeypatch.delitem(registry.runtime, "translation", raising=False)

    resp = fastapi_client.post(
        "/api/translation/text",
        json={"text": "hello", "target": "en"},
        headers=auth_headers,
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["message"] == (
        "No translation provider is configured. Add your own in Settings, "
        "or contact an administrator."
    )


def test_credential_rejected_with_no_fallback(fastapi_client, auth_headers):
    payload = {
        "text": "hello",
        "target": "en",
        "provider_config": {"api_url": "https://provider.example/translate"},
    }
    with mock.patch.object(
        TranslationService,
        "_perform_translation",
        side_effect=TranslationProviderError("unauthorized", status_code=401),
    ):
        resp = fastapi_client.post(
            "/api/translation/text", json=payload, headers=auth_headers
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == (
        "Your provider rejected the request. Check your API key in Settings."
    )


def test_fallback_used_is_surfaced_not_silent(fastapi_client, auth_headers):
    payload = {
        "text": "hello",
        "target": "en",
        "provider_config": {"api_url": "https://provider.example/translate"},
    }

    calls = {"n": 0}

    def _fake_perform(self, *, text, source_lang, target_lang, provider_config):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TranslationProviderError("timeout")
        return "hola"

    # Build a real service with a genuinely different default provider
    # config baked in, so the natural primary->default fallback path in
    # TranslationService.translate() triggers organically (rather than
    # trying to patch `default_provider_config`, which only ever exists
    # per-instance, set in __init__ - there is no class attribute to patch).
    service = TranslationService(
        default_api_url="https://default.example",
        default_provider_config={"api_url": "https://default.example"},
    )

    with mock.patch(
        "backend_fastapi.app.api.routers.translation.translation_service", service
    ), mock.patch.object(TranslationService, "_perform_translation", _fake_perform):
        resp = fastapi_client.post(
            "/api/translation/text", json=payload, headers=auth_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["translated"] == "hola"
    assert body["used_fallback"] is True
    assert body["notice"] == (
        "Your translation provider didn't respond, so the platform default " "was used."
    )
