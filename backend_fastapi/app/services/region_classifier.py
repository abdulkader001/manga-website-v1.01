"""Heuristic text-region classification (SRS 2B.3).

OCR engines (Tesseract included) return text plus a bounding box -- no
bubble-shape detection. This derives a best-effort ``region_type`` from box
geometry and, when the source image is available, a light read of the
pixels immediately around the box: a region sitting on a near-uniform fill
(the inside of a drawn bubble) reads very differently from one sitting on
a busy illustrated background (typical of sound effects lettered directly
into the art). It is a heuristic, not a CV pipeline, and callers should
treat the result as a best guess, not ground truth.
"""

from __future__ import annotations

from typing import Dict, Optional

try:  # Pillow is already a hard dependency of ocr_service.
    from PIL import Image
except Exception:  # pragma: no cover - Pillow is always installed in practice
    Image = None  # type: ignore[assignment]

REGION_SPEECH_BUBBLE = "speech_bubble"
REGION_RECTANGLE = "rectangle"
REGION_CIRCLE = "circle"
REGION_CAPTION = "caption"
REGION_SOUND_EFFECT = "sound_effect"
REGION_NARRATION_BOX = "narration_box"
REGION_BUSY_BACKGROUND = "text_on_busy_background"

NARRATION_TOP_BAND_RATIO = 0.14
NARRATION_MIN_WIDTH_RATIO = 0.55
CIRCLE_ASPECT_TOLERANCE = 0.2
CIRCLE_MAX_WIDTH_RATIO = 0.25
CAPTION_MAX_WIDTH_RATIO = 0.12
RECTANGLE_MIN_ASPECT = 2.2
BUSY_BACKGROUND_STDDEV_THRESHOLD = 28.0
LOW_CONFIDENCE_SFX_THRESHOLD = 55.0


def _sample_background_stddev(
    image: Optional["Image.Image"], box: Dict[str, float], margin: int = 6
) -> Optional[float]:
    """Grayscale stddev of a small ring around ``box``. High = busy art."""

    if image is None or Image is None:
        return None
    try:
        gray = image.convert("L")
        width, height = gray.size
        left = max(0, int(box["x"]) - margin)
        top = max(0, int(box["y"]) - margin)
        right = min(width, int(box["x"] + box["width"]) + margin)
        bottom = min(height, int(box["y"] + box["height"]) + margin)
        if right <= left or bottom <= top:
            return None
        region = gray.crop((left, top, right, bottom))
        pixel_count = region.width * region.height
        if not pixel_count:
            return None
        histogram = region.histogram()
        mean = sum(i * c for i, c in enumerate(histogram)) / pixel_count
        variance = (
            sum(((i - mean) ** 2) * c for i, c in enumerate(histogram)) / pixel_count
        )
        return variance**0.5
    except (
        Exception
    ):  # pragma: no cover - defensive; classification degrades gracefully
        return None


def classify_region(
    box: Dict[str, float],
    *,
    page: Dict[str, float],
    confidence: float = 100.0,
    image: Optional["Image.Image"] = None,
) -> str:
    """Return a ``region_type`` for one detected text box."""

    page_width = float(page.get("width") or 1) or 1.0
    page_height = float(page.get("height") or 1) or 1.0
    width = max(1.0, float(box.get("width") or 1))
    height = max(1.0, float(box.get("height") or 1))
    aspect = width / height

    top_ratio = float(box.get("y") or 0) / page_height
    width_ratio = width / page_width

    if (
        top_ratio <= NARRATION_TOP_BAND_RATIO
        and width_ratio >= NARRATION_MIN_WIDTH_RATIO
    ):
        return REGION_NARRATION_BOX

    stddev = _sample_background_stddev(image, box)
    busy = stddev is not None and stddev >= BUSY_BACKGROUND_STDDEV_THRESHOLD

    if busy:
        if confidence <= LOW_CONFIDENCE_SFX_THRESHOLD:
            return REGION_SOUND_EFFECT
        return REGION_BUSY_BACKGROUND

    if width_ratio <= CAPTION_MAX_WIDTH_RATIO and aspect >= RECTANGLE_MIN_ASPECT:
        return REGION_CAPTION

    if (
        abs(aspect - 1.0) <= CIRCLE_ASPECT_TOLERANCE
        and width_ratio < CIRCLE_MAX_WIDTH_RATIO
    ):
        return REGION_CIRCLE

    if aspect >= RECTANGLE_MIN_ASPECT:
        return REGION_RECTANGLE

    return REGION_SPEECH_BUBBLE


__all__ = [
    "classify_region",
    "REGION_SPEECH_BUBBLE",
    "REGION_RECTANGLE",
    "REGION_CIRCLE",
    "REGION_CAPTION",
    "REGION_SOUND_EFFECT",
    "REGION_NARRATION_BOX",
    "REGION_BUSY_BACKGROUND",
]
