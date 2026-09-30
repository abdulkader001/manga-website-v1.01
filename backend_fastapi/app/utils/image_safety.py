"""Shared image-decode safety helper (SRS 4G.3.1 -- decompression bomb protection).

Pillow's ``Image.open()`` only reads a file's declared width/height from its
header; ``.load()`` is the expensive step that actually decodes every pixel
into memory. A small, well-compressed upload can still declare an enormous
canvas (a "decompression bomb"), so the pixel-count check that matters must
run on the *declared* size before ``.load()`` is ever called -- checking
after ``.load()`` has already paid the cost the check exists to avoid.

This also lowers Pillow's own global bomb-detection ceiling as a process-wide
safety net, and turns a trip of that detector into a clean, catchable
rejection instead of an uncaught ``DecompressionBombError`` (which previously
surfaced as a 500 to the caller).
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

# Pillow's default (~89.5 MP warn / ~179 MP error) is a coarse global safety
# net covering every image decode in the process, including ones that don't
# go through `open_image_safely` below. Each call site still enforces its
# own tighter, feature-specific ceiling via `max_pixels`.
Image.MAX_IMAGE_PIXELS = 64_000_000


class InvalidImageError(Exception):
    """The payload is not a decodable image."""


class ImageTooLargeError(Exception):
    """The image's pixel dimensions exceed the caller's declared ceiling."""


def open_image_safely(raw: bytes, *, max_pixels: int) -> Image.Image:
    """Open and fully decode ``raw`` as an image, rejecting decompression bombs.

    Checks the header-declared width/height against ``max_pixels`` *before*
    decoding any pixel data, then decodes. Raises ``InvalidImageError`` for
    anything that isn't a valid image, or ``ImageTooLargeError`` for anything
    over ``max_pixels`` -- checked both from the header (the common case) and
    from Pillow's own bomb detector during decode (defense in depth, in case
    a format needs partial decode before its true size is known).
    """
    try:
        # Image.open() itself calls Pillow's bomb check against the
        # header-declared size (before any pixel data is touched), so it can
        # already raise DecompressionBombError for extreme cases -- and that
        # error is a bare Exception subclass, not an OSError.
        image = Image.open(io.BytesIO(raw))
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(str(exc)) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError(str(exc)) from exc

    width, height = image.size
    if not width or not height:
        raise InvalidImageError("image has invalid dimensions")
    if width * height > max_pixels:
        raise ImageTooLargeError(f"{width}x{height} exceeds {max_pixels} pixels")

    try:
        image.load()
    except Image.DecompressionBombError as exc:
        raise ImageTooLargeError(str(exc)) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError(str(exc)) from exc

    return image
