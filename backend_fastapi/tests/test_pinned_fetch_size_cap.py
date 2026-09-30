"""Response-size-cap regression tests for the SSRF-pinned fetcher (F-SSS-04).

Every fetch used to buffer the *entire* response body before anything checked
its size -- e.g. ``OCRService``'s ``MAX_FILE_BYTES`` only ever ran against a
``bytes`` object that had already finished downloading. These tests prove the
cap is now enforced while the body streams in, so an oversized response never
gets fully buffered in the first place.
"""

from __future__ import annotations

import pytest
import requests

from backend_fastapi.app.services import pinned_fetch, url_guard

PUBLIC_IP = "93.184.216.34"


class _DummyRaw:
    """Stand-in for the urllib3 raw object; only ``close`` is ever touched."""

    def close(self) -> None:
        pass


def _fake_send_yielding(chunks_factory):
    """Build an ``HTTPAdapter.send`` replacement streaming ``chunks_factory()``."""

    def _send(self, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.raw = _DummyRaw()
        response.iter_content = lambda chunk_size=1: chunks_factory()
        return response

    return _send


@pytest.fixture(autouse=True)
def _resolve_publicly(monkeypatch):
    monkeypatch.setattr(url_guard, "_host_addresses", lambda host: [PUBLIC_IP])


def test_body_within_the_limit_is_returned_normally(monkeypatch):
    body = b"a" * 1024

    monkeypatch.setattr(
        requests.adapters.HTTPAdapter,
        "send",
        _fake_send_yielding(lambda: iter([body[:512], body[512:]])),
    )

    response = pinned_fetch.get_pinned(
        "https://images.example.com/small.bin",
        url_guard.validate_remote_image_url_resolved,
        max_bytes=len(body) + 1,
    )

    assert response.content == body


def test_oversized_response_is_rejected_before_being_fully_buffered(monkeypatch):
    """The cap must abort mid-stream, not after ``requests`` already buffered it."""

    consumed_chunks: list[int] = []
    chunk = b"a" * 1024  # 1 KiB per chunk
    total_chunks = 200  # 200 KiB if the generator were ever fully drained

    def _chunks():
        for i in range(total_chunks):
            consumed_chunks.append(i)
            yield chunk

    monkeypatch.setattr(
        requests.adapters.HTTPAdapter, "send", _fake_send_yielding(_chunks)
    )

    max_bytes = 10 * 1024  # 10 KiB -- far below the 200 KiB the body would be

    with pytest.raises(pinned_fetch.ResponseTooLarge):
        pinned_fetch.get_pinned(
            "https://images.example.com/huge.bin",
            url_guard.validate_remote_image_url_resolved,
            max_bytes=max_bytes,
        )

    # Proof the abort happened while streaming: the generator was never
    # drained anywhere close to its full length.
    assert 0 < len(consumed_chunks) < total_chunks


def test_response_too_large_is_not_retried_against_other_addresses(monkeypatch):
    """An oversized body is a property of the resource, not the address.

    Unlike a ``ConnectionError`` (where failing over to another validated
    address makes sense), retrying a too-large response elsewhere would just
    waste another connection on the same oversized resource.
    """

    attempts = {"count": 0}
    chunk = b"a" * 1024

    def _chunks():
        attempts["count"] += 1
        for _ in range(10):
            yield chunk

    monkeypatch.setattr(
        requests.adapters.HTTPAdapter, "send", _fake_send_yielding(_chunks)
    )
    monkeypatch.setattr(
        url_guard, "_host_addresses", lambda host: [PUBLIC_IP, "93.184.216.35"]
    )

    with pytest.raises(pinned_fetch.ResponseTooLarge):
        pinned_fetch.get_pinned(
            "https://images.example.com/huge.bin",
            url_guard.validate_remote_image_url_resolved,
            max_bytes=1024,
        )

    assert attempts["count"] == 1


def test_default_limit_applies_when_caller_passes_none(monkeypatch):
    """No ``max_bytes`` given -> ``DEFAULT_MAX_FETCH_BYTES`` is the ceiling."""

    oversized = pinned_fetch.DEFAULT_MAX_FETCH_BYTES + 1024
    chunk = b"a" * 1024

    def _chunks():
        sent = 0
        while sent < oversized:
            sent += len(chunk)
            yield chunk

    monkeypatch.setattr(
        requests.adapters.HTTPAdapter, "send", _fake_send_yielding(_chunks)
    )

    with pytest.raises(pinned_fetch.ResponseTooLarge):
        pinned_fetch.get_pinned(
            "https://images.example.com/default-limit.bin",
            url_guard.validate_remote_image_url_resolved,
        )


def test_get_pinned_following_redirects_forwards_max_bytes_per_hop(monkeypatch):
    """Each redirect hop is refetched through ``get_pinned`` -- the byte
    ceiling must travel with it, not just apply to the first hop."""

    seen_max_bytes: list[int | None] = []
    real_get_pinned = pinned_fetch.get_pinned

    def _spy(url, validator, **kwargs):
        seen_max_bytes.append(kwargs.get("max_bytes"))
        return real_get_pinned(url, validator, **kwargs)

    monkeypatch.setattr(pinned_fetch, "get_pinned", _spy)
    monkeypatch.setattr(
        requests.adapters.HTTPAdapter,
        "send",
        _fake_send_yielding(lambda: iter([b"ok"])),
    )

    pinned_fetch.get_pinned_following_redirects(
        "https://images.example.com/a.bin",
        url_guard.validate_remote_image_url_resolved,
        max_bytes=4096,
    )

    assert seen_max_bytes == [4096]
