"""Decompression bomb protection for image uploads (SRS 4G.3.1).

Covers the shared ``open_image_safely`` helper directly: a normal image is
accepted, an image whose *declared* dimensions exceed the caller's ceiling is
rejected cleanly (without ever decoding pixel data), and Pillow's own global
bomb detector -- which raises a bare ``Exception`` subclass, not an
``OSError`` -- is caught and translated instead of propagating uncaught.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from backend_fastapi.app.utils.image_safety import (
    ImageTooLargeError,
    InvalidImageError,
    open_image_safely,
)


def _png_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(10, 20, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_normal_image_is_accepted():
    payload = _png_bytes(100, 100)
    image = open_image_safely(payload, max_pixels=1_000_000)
    assert image.size == (100, 100)


def test_declared_dimensions_over_ceiling_are_rejected_before_decode():
    # 2000x2000 = 4,000,000 pixels, comfortably over a 1,000-pixel ceiling.
    # If this were checked after a full decode instead of from the header,
    # it would still pass, but slower -- this asserts it fails fast.
    payload = _png_bytes(2000, 2000)
    with pytest.raises(ImageTooLargeError):
        open_image_safely(payload, max_pixels=1_000)


def test_invalid_bytes_are_rejected():
    with pytest.raises(InvalidImageError):
        open_image_safely(b"not an image", max_pixels=1_000_000)


def test_pillows_own_bomb_detector_is_caught_not_propagated(monkeypatch):
    """Regression test for the bug this module fixes.

    Pillow's own decompression-bomb check can fire inside ``Image.open()``
    itself (before our own max_pixels check even runs) and raises
    ``Image.DecompressionBombError`` -- a bare ``Exception`` subclass, not an
    ``OSError``. Previously this propagated uncaught (a 500 to the caller);
    it must now surface as a clean ``ImageTooLargeError``.
    """
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1_000)
    # 100x100 = 10,000 pixels > 2 * 1,000 -> Pillow's hard error threshold.
    payload = _png_bytes(100, 100)
    with pytest.raises(ImageTooLargeError):
        # A huge max_pixels here isolates Pillow's own detector: our own
        # header check would not fire on its own.
        open_image_safely(payload, max_pixels=999_999_999)
