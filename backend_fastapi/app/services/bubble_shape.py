"""Find the speech bubble around a text box, so the reader can draw the
translation inside the bubble's own shape instead of a plain rectangle.

Pillow only (no numpy / OpenCV), on a small downscaled window per region:

1. Crop a window around the text box and mark every pixel whose brightness is
   close to the bubble's fill (sampled by ``region_classifier.sample_background``).
2. Flood-fill those pixels starting from the text itself. A drawn bubble's
   outline stops the fill; if it reaches the window edge there is no closed
   bubble (text on artwork, borderless captions) and nothing is returned, so
   that text keeps its original box and position.
3. Cast rays from the text centre to the far edge of the filled area: that is
   the outline as a polygon. Other lines of text inside the bubble are holes
   in the fill, so the ray keeps the *last* filled pixel, not the first gap.
4. Name the shape: ``ellipse`` when the outline sits on the ellipse of its
   bounding box, ``rectangle`` when it fills that box, otherwise ``freeform``.

It is a heuristic. Anything doubtful returns ``None`` and the overlay falls
back to the plain box it has always drawn.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - Pillow is a hard dependency
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

RAYS = 32
FILL_TOLERANCE = 40  # brightness difference still counted as bubble fill
MAX_WORK_SIDE = 160  # the window is downscaled to at most this many pixels...
MAX_DOWNSCALE = 4  # ...but never by more than this, so thin outlines survive
WINDOW_GROWTH = (1.0, 2.5)  # tried in order: window = box grown by k * its size
MAX_AREA_RATIO = 30.0  # a "bubble" 30x the text's area is a panel, not a bubble
ELLIPSE_MAX_ERROR = 0.07
RECTANGLE_MIN_FILL = 0.88

FILLED = 128


def _luma(hex_color: str) -> Optional[float]:
    value = (hex_color or "").lstrip("#")
    if len(value) != 6:
        return None
    try:
        r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return 0.299 * r + 0.587 * g + 0.114 * b


def _flood(gray: "Image.Image", box: Dict[str, float], fill_luma: float, growth: float):
    """Return (mask, scale, window_origin) or None if the fill leaks out."""

    page_w, page_h = gray.size
    bx, by = float(box["x"]), float(box["y"])
    bw, bh = max(1.0, float(box["width"])), max(1.0, float(box["height"]))
    pad_x = growth * bw + 12
    pad_y = growth * bh + 12
    wx0, wy0 = max(0, int(bx - pad_x)), max(0, int(by - pad_y))
    wx1, wy1 = min(page_w, int(bx + bw + pad_x)), min(page_h, int(by + bh + pad_y))
    if wx1 - wx0 < 8 or wy1 - wy0 < 8:
        return None

    window = gray.crop((wx0, wy0, wx1, wy1))
    longest = max(window.size)
    scale = min(1.0, max(MAX_WORK_SIDE / longest, 1.0 / MAX_DOWNSCALE))
    if scale < 1.0:
        window = window.resize(
            (max(1, round(window.width * scale)), max(1, round(window.height * scale))),
            Image.BILINEAR,
        )

    lo, hi = fill_luma - FILL_TOLERANCE, fill_luma + FILL_TOLERANCE
    mask = window.point(lambda v: 255 if lo <= v <= hi else 0)

    # The lettering itself is "inside": paint the text box as fill (one pixel
    # in from its edge, so a loose OCR box can't bridge the outline).
    tx0 = (bx - wx0) * scale + 1
    ty0 = (by - wy0) * scale + 1
    tx1 = (bx + bw - wx0) * scale - 1
    ty1 = (by + bh - wy0) * scale - 1
    if tx1 <= tx0 or ty1 <= ty0:
        return None
    ImageDraw.Draw(mask).rectangle((tx0, ty0, tx1, ty1), fill=255)
    seed = (int((tx0 + tx1) / 2), int((ty0 + ty1) / 2))
    ImageDraw.floodfill(mask, seed, FILLED, thresh=0)

    w, h = mask.size
    for edge in (
        mask.crop((0, 0, w, 1)),
        mask.crop((0, h - 1, w, h)),
        mask.crop((0, 0, 1, h)),
        mask.crop((w - 1, 0, w, h)),
    ):
        if edge.histogram()[FILLED]:
            return None  # leaked: no closed outline inside this window
    return mask, scale, (wx0, wy0), seed


def _rays(mask: "Image.Image", seed: Tuple[int, int]) -> List[Tuple[float, float]]:
    pixels = mask.load()
    w, h = mask.size
    cx, cy = seed
    points = []
    for i in range(RAYS):
        angle = 2 * math.pi * i / RAYS
        dx, dy = math.cos(angle), math.sin(angle)
        last = (float(cx), float(cy))
        step = 0
        while True:
            step += 1
            x, y = cx + dx * step, cy + dy * step
            ix, iy = int(round(x)), int(round(y))
            if not (0 <= ix < w and 0 <= iy < h):
                break
            if pixels[ix, iy] == FILLED:
                last = (x, y)
        points.append(last)
    return points


def _polygon_area(points: List[Tuple[float, float]]) -> float:
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        total += x0 * y1 - x1 * y0
    return abs(total) / 2


def _inside(points: List[Tuple[float, float]], x: float, y: float) -> bool:
    inside = False
    j = len(points) - 1
    for i, (xi, yi) in enumerate(points):
        xj, yj = points[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def _inner_rect(points, cx, cy, half_w, half_h) -> Tuple[float, float]:
    """Largest scale t so the box (cx +- t*half_w, cy +- t*half_h) stays inside."""

    def fits(t: float) -> bool:
        for k in range(9):
            f = k / 8
            for x, y in (
                (cx - t * half_w + 2 * t * half_w * f, cy - t * half_h),
                (cx - t * half_w + 2 * t * half_w * f, cy + t * half_h),
                (cx - t * half_w, cy - t * half_h + 2 * t * half_h * f),
                (cx + t * half_w, cy - t * half_h + 2 * t * half_h * f),
            ):
                if not _inside(points, x, y):
                    return False
        return True

    lo, hi = 0.0, 1.0
    for _ in range(12):
        mid = (lo + hi) / 2
        if fits(mid):
            lo = mid
        else:
            hi = mid
    return lo * half_w, lo * half_h


def _classify(points, x0, y0, x1, y1) -> str:
    half_w, half_h = (x1 - x0) / 2 or 1e-9, (y1 - y0) / 2 or 1e-9
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    error = sum(
        abs(math.hypot((x - cx) / half_w, (y - cy) / half_h) - 1) for x, y in points
    ) / len(points)
    if error <= ELLIPSE_MAX_ERROR:
        return "ellipse"
    if _polygon_area(points) / ((x1 - x0) * (y1 - y0) or 1e-9) >= RECTANGLE_MIN_FILL:
        return "rectangle"
    return "freeform"


def detect_bubble(
    image: Optional["Image.Image"], box: Dict[str, float], background: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Shape of the bubble holding ``box``, in page pixels, or ``None``.

    ``polygon`` and ``inner`` are fractions of the bubble's bounding box:
    ``polygon`` traces the outline, ``inner`` is the largest centred
    rectangle that fits inside it (where the translated text goes).
    """

    if image is None or Image is None:
        return None
    fill_luma = _luma(background or "")
    if fill_luma is None:
        return None
    try:
        gray = image if image.mode == "L" else image.convert("L")
        found = None
        for growth in WINDOW_GROWTH:
            found = _flood(gray, box, fill_luma, growth)
            if found:
                break
        if not found:
            return None
        mask, scale, (wx0, wy0), seed = found

        points = _rays(mask, seed)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None

        # Back to page pixels.
        page_pts = [(wx0 + x / scale, wy0 + y / scale) for x, y in points]
        px0, py0 = wx0 + x0 / scale, wy0 + y0 / scale
        px1, py1 = wx0 + x1 / scale, wy0 + y1 / scale
        bw, bh = px1 - px0, py1 - py0
        text_area = max(1.0, float(box["width"]) * float(box["height"]))
        if bw * bh > MAX_AREA_RATIO * text_area:
            return None

        shape = _classify(page_pts, px0, py0, px1, py1)
        cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
        half_w, half_h = _inner_rect(page_pts, cx, cy, bw / 2, bh / 2)
        # Never give the translation less room than the original lettering had.
        ix0 = max(px0, min(cx - half_w, float(box["x"])))
        iy0 = max(py0, min(cy - half_h, float(box["y"])))
        ix1 = min(px1, max(cx + half_w, float(box["x"]) + float(box["width"])))
        iy1 = min(py1, max(cy + half_h, float(box["y"]) + float(box["height"])))

        def frac(value: float, origin: float, size: float) -> float:
            return round(min(1.0, max(0.0, (value - origin) / size)), 4)

        return {
            "shape": shape,
            "x": round(px0, 1),
            "y": round(py0, 1),
            "width": round(bw, 1),
            "height": round(bh, 1),
            "polygon": [[frac(x, px0, bw), frac(y, py0, bh)] for x, y in page_pts],
            "inner": {
                "x": frac(ix0, px0, bw),
                "y": frac(iy0, py0, bh),
                "width": round((ix1 - ix0) / bw, 4),
                "height": round((iy1 - iy0) / bh, 4),
            },
        }
    except Exception:  # pragma: no cover - never let shape finding break OCR
        return None


def drop_shared_bubbles(regions: List[Dict[str, Any]]) -> None:
    """Two text regions in one bubble would draw two overlapping shapes:
    keep their plain boxes instead."""

    def key(b: Dict[str, Any]) -> Tuple[int, int, int, int]:
        return (round(b["x"] / 6), round(b["y"] / 6), round(b["width"] / 6), round(b["height"] / 6))

    seen: Dict[Tuple[int, int, int, int], int] = {}
    for region in regions:
        bubble = region.get("bubble")
        if bubble:
            k = key(bubble)
            seen[k] = seen.get(k, 0) + 1
    for region in regions:
        bubble = region.get("bubble")
        if bubble and seen[key(bubble)] > 1:
            region.pop("bubble", None)


__all__ = ["detect_bubble", "drop_shared_bubbles"]
