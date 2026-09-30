"""Tests for the translation service fallback logic."""

from __future__ import annotations

from types import SimpleNamespace

import requests

from backend_fastapi.app.services.translation_service import TranslationService


class DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


def test_translation_service_falls_back_to_default_on_error(monkeypatch) -> None:
    attempts: list[str] = []

    def fake_post(url, json=None, headers=None, timeout=None):  # type: ignore[override]
        attempts.append(url)
        if "override" in url:
            raise requests.RequestException("boom")
        return DummyResponse(200, {"translatedText": "hola"})

    monkeypatch.setattr(
        TranslationService, "_should_use_chat_completion", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=fake_post, RequestException=requests.RequestException),
    )

    service = TranslationService(
        default_api_url="https://system.example/translate",
        default_api_key="system-key",
        default_provider_config={
            "api_url": "https://system.example/translate",
            "api_key": "system-key",
            "provider": "system",
        },
    )

    result = service.translate(
        "hello",
        "en",
        "es",
        provider_config={"api_url": "https://override.example/translate"},
    )

    assert result == "hola"
    assert attempts == [
        "https://override.example/translate",
        "https://system.example/translate",
    ]


def test_translation_service_uses_default_on_http_error(monkeypatch) -> None:
    attempts: list[str] = []

    responses = [
        DummyResponse(502, {}),
        DummyResponse(200, {"translatedText": "bonjour"}),
    ]

    def fake_post(url, json=None, headers=None, timeout=None):  # type: ignore[override]
        attempts.append(url)
        response = responses.pop(0)
        return response

    monkeypatch.setattr(
        TranslationService, "_should_use_chat_completion", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=fake_post, RequestException=requests.RequestException),
    )

    service = TranslationService(
        default_api_url="https://system.example/translate",
        default_api_key=None,
        default_provider_config={
            "api_url": "https://system.example/translate",
            "provider": "system",
        },
    )

    result = service.translate(
        "greetings",
        "en",
        "fr",
        provider_config={"api_url": "https://override.example/translate"},
    )

    assert result == "bonjour"
    assert attempts == [
        "https://override.example/translate",
        "https://system.example/translate",
    ]


def test_translation_service_returns_original_text_when_all_fail(monkeypatch) -> None:
    def fake_post(url, json=None, headers=None, timeout=None):  # type: ignore[override]
        raise requests.RequestException("nope")

    monkeypatch.setattr(
        TranslationService, "_should_use_chat_completion", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=fake_post, RequestException=requests.RequestException),
    )

    service = TranslationService(
        default_api_url="https://system.example/translate",
        default_api_key=None,
        default_provider_config={
            "api_url": "https://system.example/translate",
            "provider": "system",
        },
    )

    result = service.translate(
        "stay",
        "en",
        "de",
        provider_config={"api_url": "https://override.example/translate"},
    )

    assert result == "stay"
