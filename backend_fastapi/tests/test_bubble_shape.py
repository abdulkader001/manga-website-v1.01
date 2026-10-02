"""Bubble shape recognition on synthetic pages (Pillow only)."""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from backend_fastapi.app.services import ocr_normalize
from backend_fastapi.app.services.bubble_shape import detect_bubble


def _page(bg=(150, 150, 150)):
    return Image.new("RGB", (800, 800), bg)


def _text(draw, box):
    """Fake lettering: dark strokes inside the text box."""
    x, y, w, h = box["x"], box["y"], box["width"], box["height"]
    for row in range(int(y) + 2, int(y + h) - 2, 9):
        for col in range(int(x) + 2, int(x + w) - 4, 8):
            draw.rectangle((col, row, col + 4, row + 5), fill=(10, 10, 10))


BOX = {"x": 340.0, "y": 370.0, "width": 120.0, "height": 60.0}


def test_ellipse_bubble():
    img = _page()
    d = ImageDraw.Draw(img)
    d.ellipse((250, 300, 550, 500), fill="white", outline="black", width=3)
    _text(d, BOX)
    bubble = detect_bubble(img, BOX, "#ffffff")
    assert bubble and bubble["shape"] == "ellipse"
    assert abs(bubble["x"] - 252) < 10 and abs(bubble["width"] - 296) < 16
    assert abs(bubble["y"] - 302) < 10 and abs(bubble["height"] - 196) < 16
    assert len(bubble["polygon"]) == 32
    inner = bubble["inner"]
    # The text area inside an ellipse is about 70% of each axis, centred.
    assert 0.6 <= inner["width"] <= 0.8 and 0.6 <= inner["height"] <= 0.8
    assert abs(inner["x"] + inner["width"] / 2 - 0.5) < 0.05


def test_rectangle_bubble():
    img = _page()
    d = ImageDraw.Draw(img)
    d.rectangle((280, 330, 520, 470), fill="white", outline="black", width=3)
    _text(d, BOX)
    bubble = detect_bubble(img, BOX, "#ffffff")
    assert bubble and bubble["shape"] == "rectangle"
    assert bubble["inner"]["width"] > 0.85


def test_freeform_bubble():
    img = _page()
    d = ImageDraw.Draw(img)
    d.polygon([(260, 320), (560, 300), (520, 500), (400, 460), (280, 520)], fill="white", outline="black", width=3)
    _text(d, BOX)
    bubble = detect_bubble(img, BOX, "#ffffff")
    assert bubble and bubble["shape"] == "freeform"


def test_dark_bubble_with_light_text():
    img = _page((200, 200, 200))
    d = ImageDraw.Draw(img)
    d.ellipse((250, 300, 550, 500), fill=(20, 20, 20), outline="white", width=3)
    x, y, w, h = BOX.values()
    d.rectangle((x + 4, y + 4, x + w - 4, y + 12), fill="white")
    assert detect_bubble(img, BOX, "#141414")["shape"] == "ellipse"


def test_text_with_no_outline_keeps_its_box():
    img = _page((255, 255, 255))  # text lettered on a blank area, no bubble
    _text(ImageDraw.Draw(img), BOX)
    assert detect_bubble(img, BOX, "#ffffff") is None


def test_bubble_cut_open_is_not_a_bubble():
    img = _page((255, 255, 255))
    d = ImageDraw.Draw(img)
    d.arc((250, 300, 550, 500), 20, 340, fill="black", width=3)  # gap on the right
    _text(d, BOX)
    assert detect_bubble(img, BOX, "#ffffff") is None


def test_normalize_adds_bubble_and_skips_shared_ones():
    img = _page()
    d = ImageDraw.Draw(img)
    d.ellipse((250, 300, 550, 500), fill="white", outline="black", width=3)
    d.ellipse((50, 50, 250, 200), fill="white", outline="black", width=3)
    line1 = {"x": 330.0, "y": 360.0, "width": 140.0, "height": 30.0}
    line2 = {"x": 330.0, "y": 405.0, "width": 140.0, "height": 30.0}
    solo = {"x": 110.0, "y": 105.0, "width": 80.0, "height": 40.0}
    for b in (line1, line2, solo):
        _text(d, b)
    raw = [{"text": "a", **line1}, {"text": "b", **line2}, {"text": "c", **solo}]
    out = ocr_normalize.build_normalized_output(raw, image=img, page={"width": 800, "height": 800})
    by_text = {r["text"]: r for r in out["regions"]}
    assert by_text["c"]["bubble"]["shape"] == "ellipse"
    # Two lines OCR'd separately in one bubble: plain boxes, not two shapes.
    assert "bubble" not in by_text["a"] and "bubble" not in by_text["b"]


def test_fast_enough_for_a_full_page():
    img = Image.new("RGB", (1600, 2400), (150, 150, 150))
    d = ImageDraw.Draw(img)
    boxes = []
    for i in range(10):
        top = 40 + i * 230
        d.ellipse((300, top, 1300, top + 210), fill="white", outline="black", width=4)
        box = {"x": 600.0, "y": top + 60.0, "width": 400.0, "height": 90.0}
        _text(d, box)
        boxes.append(box)
    gray = img.convert("L")
    start = time.perf_counter()
    found = [detect_bubble(gray, b, "#ffffff") for b in boxes]
    assert all(found)
    assert time.perf_counter() - start < 3.0
