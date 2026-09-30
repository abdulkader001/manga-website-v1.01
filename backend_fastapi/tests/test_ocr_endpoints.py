from __future__ import annotations

from typing import Any, Dict

import pytest


class DummyOCR:
    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        self.calls: list[tuple[bytes, str | None]] = []

    def extract(
        self,
        image_bytes: bytes,
        psm: str | None = None,
        lang: str | None = None,
        provider_config=None,
    ):
        self.calls.append((image_bytes, lang))
        return self.payload


@pytest.fixture
def allow_remote_host(monkeypatch):
    from backend_fastapi.app.services import url_guard

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)


def test_ocr_image_returns_text(fastapi_client, monkeypatch, auth_headers):
    from backend_fastapi.app.api.routers import ocr as ocr_router

    ocr_payload = {"items": [{"text": "hello"}, {"text": "world"}], "page": {}}
    dummy_service = DummyOCR(ocr_payload)
    monkeypatch.setattr(ocr_router, "ocr_service", dummy_service)

    async def fake_read(upload):  # type: ignore[override]
        return b"fake-bytes"

    monkeypatch.setattr(ocr_router, "_read_upload", fake_read)

    response = fastapi_client.post(
        "/api/ocr/image",
        files={"file": ("test.png", b"ignored", "image/png")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "hello world"
    assert dummy_service.calls == [(b"fake-bytes", None)]


def test_overlay_returns_normalized_boxes(
    fastapi_client, monkeypatch, allow_remote_host, auth_headers
):
    from backend_fastapi.app.api.routers import ocr as ocr_router

    ocr_payload = {
        "items": [
            {"text": "hello", "left": 10, "top": 20, "width": 30, "height": 40},
        ],
        "page": {"width": 100, "height": 200},
        "metadata": {"detected_language": {"code": "en"}},
    }
    dummy_service = DummyOCR(ocr_payload)
    monkeypatch.setattr(ocr_router, "ocr_service", dummy_service)

    async def mock_fetch(url, request):
        return b"fake-remote-bytes"

    monkeypatch.setattr(ocr_router, "_fetch_remote_image", mock_fetch)

    response = fastapi_client.get(
        "/api/ocr/overlay",
        params={"imageUrl": "https://example.com/image.png"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["boxes"][0]["x"] == pytest.approx(0.1, rel=1e-3)
    assert "metadata" in data
    assert dummy_service.calls == [(b"fake-remote-bytes", None)]


def test_translate_overlay_runs_translation(
    fastapi_client, monkeypatch, allow_remote_host, auth_headers
):
    from backend_fastapi.app.api.routers import ocr as ocr_router

    ocr_payload = {
        "items": [
            {"text": "こんにちは", "left": 0, "top": 0, "width": 100, "height": 50},
        ],
        "page": {"width": 200, "height": 100},
        "metadata": {"detected_language": {"code": "ja"}},
    }
    dummy_service = DummyOCR(ocr_payload)
    monkeypatch.setattr(ocr_router, "ocr_service", dummy_service)

    async def mock_fetch(url, request):
        return b"remote-image"

    monkeypatch.setattr(ocr_router, "_fetch_remote_image", mock_fetch)

    class DummyTranslation:
        def __init__(self):
            self.calls: list[tuple[str, str, str]] = []

        def translate(self, text, source_lang, target_lang, provider_config=None):
            self.calls.append((text, source_lang, target_lang))
            return "hello"

    translation_service = DummyTranslation()
    monkeypatch.setattr(
        ocr_router,
        "resolve_translation_service",
        lambda request, translation_config, ai_config: (
            translation_service,
            {"provider": "demo"},
            False,
        ),
    )

    response = fastapi_client.post(
        "/api/ocr/translate-overlay",
        json={"imageUrl": "https://example.com/image.png", "target": "en"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["boxes"][0]["translated"] == "hello"
    assert data["metadata"]["translation"]["errors"] == []
    assert translation_service.calls == [("こんにちは", "ja", "en")]


def test_translate_overlay_handles_unavailable_translation(
    fastapi_client, monkeypatch, allow_remote_host, auth_headers
):
    from backend_fastapi.app.api.routers import ocr as ocr_router

    ocr_payload = {
        "items": [
            {"text": "hola", "left": 0, "top": 0, "width": 10, "height": 10},
        ],
        "page": {"width": 10, "height": 10},
        "metadata": {},
    }
    dummy_service = DummyOCR(ocr_payload)
    monkeypatch.setattr(ocr_router, "ocr_service", dummy_service)

    async def mock_fetch(url, request):
        return b"remote-image"

    monkeypatch.setattr(ocr_router, "_fetch_remote_image", mock_fetch)
    monkeypatch.setattr(
        ocr_router,
        "resolve_translation_service",
        lambda request, translation_config, ai_config: (None, None, False),
    )

    response = fastapi_client.post(
        "/api/ocr/translate-overlay",
        json={"imageUrl": "https://example.com/image.png", "target": "en"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["translation"]["errors"] == ["translation_unavailable"]


def test_translate_upload_combines_text(fastapi_client, monkeypatch, auth_headers):
    from backend_fastapi.app.api.routers import ocr as ocr_router

    ocr_payload = {
        "items": [
            {"text": "bonjour", "left": 0, "top": 0, "width": 10, "height": 10},
        ],
        "page": {"width": 10, "height": 10},
        "metadata": {},
    }
    dummy_service = DummyOCR(ocr_payload)
    monkeypatch.setattr(ocr_router, "ocr_service", dummy_service)

    async def fake_read(upload):  # type: ignore[override]
        return b"fake-bytes"

    monkeypatch.setattr(ocr_router, "_read_upload", fake_read)

    class DummyTranslation:
        def translate(self, text, source_lang, target_lang, provider_config=None):
            return text.upper()

    monkeypatch.setattr(
        ocr_router,
        "resolve_translation_service",
        lambda request, translation_config, ai_config: (
            DummyTranslation(),
            {"provider": "demo"},
            False,
        ),
    )

    response = fastapi_client.post(
        "/api/ocr/translate-upload",
        files={"file": ("test.png", b"ignored", "image/png")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "BONJOUR"
    assert data["metadata"]["translation"]["errors"] == []


def test_overlay_rejects_invalid_url(fastapi_client, auth_headers):
    response = fastapi_client.get(
        "/api/ocr/overlay",
        params={"imageUrl": "ftp://example.com/test.png"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert response.json()["error"]["details"]["reason"] == "invalid_image_url"


# ---------------------------------------------------------------------------
# Regression guards for the real ``resolve_translation_service``.
#
# Every other translate-* test above monkeypatches ``resolve_translation_service``
# wholesale, so the real function's body never executes under test. That blind
# spot hid a stale deferred import (``from ..routers import translation`` --
# the package moved to ``app/api/routers/``) which made both translate
# endpoints raise ModuleNotFoundError on *every* call, surfacing as a bare,
# untyped 500. Deferred (function-body) imports are invisible to linters and to
# import-time smoke checks, so the only thing that catches this class of bug is
# actually running the function.
#
# These tests therefore mock the external I/O (OCR engine, image fetch) but
# deliberately leave ``resolve_translation_service`` real.
# ---------------------------------------------------------------------------


def test_resolve_translation_service_is_importable_and_callable():
    """Tightest guard: the deferred import inside the real function resolves.

    Fails with ModuleNotFoundError if the ``app.api.routers`` import path ever
    goes stale again.
    """

    from backend_fastapi.app.services.provider_resolver import (
        resolve_translation_service,
    )

    class _Request:
        class app:
            class state:
                pass

    service, provider_config, used_ai_fallback = resolve_translation_service(
        _Request(), None, None
    )

    # With nothing configured the resolver legitimately resolves to "no service";
    # the point of this test is that it *returns* rather than raising.
    assert service is None
    assert provider_config is None
    assert used_ai_fallback is False


def test_translate_overlay_does_not_500_with_real_provider_resolution(
    fastapi_client, monkeypatch, allow_remote_host, auth_headers
):
    """``/ocr/translate-overlay`` with the real resolver in the loop."""

    from backend_fastapi.app.api.routers import ocr as ocr_router

    ocr_payload = {
        "items": [{"text": "hello", "left": 0, "top": 0, "width": 10, "height": 10}],
        "page": {"width": 100, "height": 100},
        "metadata": {"detected_language": {"code": "en"}},
    }
    monkeypatch.setattr(ocr_router, "ocr_service", DummyOCR(ocr_payload))

    async def mock_fetch(url, request):
        return b"fake-remote-bytes"

    monkeypatch.setattr(ocr_router, "_fetch_remote_image", mock_fetch)
    # NOTE: resolve_translation_service is intentionally NOT mocked here.

    response = fastapi_client.post(
        "/api/ocr/translate-overlay",
        json={"imageUrl": "https://example.com/image.png", "target": "en"},
        headers=auth_headers,
    )

    assert response.status_code != 500, response.text
    assert response.status_code == 200
    # The OCR boxes survive even when no translation provider is configured --
    # translation degrades gracefully rather than taking the endpoint down.
    data = response.json()
    assert data["boxes"][0]["text"] == "hello"


def test_translate_upload_does_not_500_with_real_provider_resolution(
    fastapi_client, monkeypatch, auth_headers
):
    """``/ocr/translate-upload`` with the real resolver in the loop."""

    from backend_fastapi.app.api.routers import ocr as ocr_router

    ocr_payload = {
        "items": [{"text": "bonjour", "left": 0, "top": 0, "width": 10, "height": 10}],
        "page": {"width": 10, "height": 10},
        "metadata": {},
    }
    monkeypatch.setattr(ocr_router, "ocr_service", DummyOCR(ocr_payload))

    async def fake_read(upload):  # type: ignore[override]
        return b"fake-bytes"

    monkeypatch.setattr(ocr_router, "_read_upload", fake_read)
    # NOTE: resolve_translation_service is intentionally NOT mocked here.

    response = fastapi_client.post(
        "/api/ocr/translate-upload",
        files={"file": ("test.png", b"ignored", "image/png")},
        headers=auth_headers,
    )

    assert response.status_code != 500, response.text
    assert response.status_code == 200
    data = response.json()
    assert data["boxes"][0]["text"] == "bonjour"
