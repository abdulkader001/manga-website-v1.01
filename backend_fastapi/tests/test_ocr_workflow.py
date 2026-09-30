import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.services.ocr_workflow import normalize_overlay_boxes  # noqa: E402


def test_normalize_overlay_boxes_happy_path():
    page = {"width": 1000, "height": 2000}
    items = [
        {"text": "Hello", "left": 100, "top": 200, "width": 50, "height": 20},
        {
            "text": "World",
            "left": 500,
            "top": 1000,
            "width": 100,
            "height": 40,
            "translated": "Mundo",
        },
    ]

    result = normalize_overlay_boxes(items, page)

    assert len(result) == 2

    assert result[0] == {
        "x": 0.1,  # 100 / 1000
        "y": 0.1,  # 200 / 2000
        "w": 0.05,  # 50 / 1000
        "h": 0.01,  # 20 / 2000
        "text": "Hello",
    }

    assert result[1] == {
        "x": 0.5,
        "y": 0.5,
        "w": 0.1,
        "h": 0.02,
        "text": "World",
        "translated": "Mundo",
    }


def test_normalize_overlay_boxes_invalid_page_dimensions():
    items = [{"text": "Hello", "left": 100, "top": 200, "width": 50, "height": 20}]

    # Missing width/height
    assert normalize_overlay_boxes(items, {}) == []

    # Zero width
    assert normalize_overlay_boxes(items, {"width": 0, "height": 1000}) == []

    # Negative height
    assert normalize_overlay_boxes(items, {"width": 1000, "height": -500}) == []

    # Non-numeric width/height
    assert normalize_overlay_boxes(items, {"width": "invalid", "height": 1000}) == []


def test_normalize_overlay_boxes_invalid_items():
    page = {"width": 1000, "height": 1000}
    items = [
        None,  # Not a dict
        [],  # Not a dict
        {"left": 100, "top": 100},  # Missing text
        {"text": "", "left": 100, "top": 100},  # Empty text
        {"text": "   ", "left": 100, "top": 100},  # Whitespace text
        {"text": "Valid", "left": 100, "top": 100, "width": 50, "height": 50},
    ]

    result = normalize_overlay_boxes(items, page)

    # Only the valid item should be returned
    assert len(result) == 1
    assert result[0]["text"] == "Valid"


def test_normalize_overlay_boxes_coordinate_clamping():
    page = {"width": 1000, "height": 1000}
    items = [
        {
            "text": "Out of bounds",
            "left": -100,  # < 0
            "top": 1500,  # > height
            "width": -50,  # < 0
            "height": 2000,  # > height
        }
    ]

    result = normalize_overlay_boxes(items, page)

    assert len(result) == 1
    assert result[0] == {
        "x": 0.0,
        "y": 1.0,
        "w": 0.0,
        "h": 1.0,
        "text": "Out of bounds",
    }


def test_normalize_overlay_boxes_translation_fields():
    page = {"width": 100, "height": 100}
    items = [
        {
            "text": "Text 1",
            "translated": " Trans 1 ",
            "left": 10,
            "top": 10,
            "width": 10,
            "height": 10,
        },
        {
            "text": "Text 2",
            "translation": " Trans 2 ",
            "left": 10,
            "top": 10,
            "width": 10,
            "height": 10,
        },
        {
            "text": "Text 3",
            "translated": 123,
            "left": 10,
            "top": 10,
            "width": 10,
            "height": 10,
        },  # Invalid type, shouldn't be included
    ]

    result = normalize_overlay_boxes(items, page)

    assert len(result) == 3
    assert result[0]["translated"] == "Trans 1"
    assert result[1]["translated"] == "Trans 2"
    assert "translated" not in result[2]


def test_normalize_overlay_boxes_string_values():
    page = {"width": "1000", "height": "1000"}
    items = [
        {
            "text": "Numeric strings",
            "left": "100",
            "top": "200.5",
            "width": "50",
            "height": "25.25",
        }
    ]

    result = normalize_overlay_boxes(items, page)

    assert len(result) == 1
    assert result[0]["x"] == 0.1
    assert result[0]["y"] == 0.2005
    assert result[0]["w"] == 0.05
    assert result[0]["h"] == 0.02525


def test_normalize_overlay_boxes_invalid_numeric_values():
    page = {"width": 1000, "height": 1000}
    items = [
        {
            "text": "Invalid numbers",
            "left": "invalid",
            "top": None,
            "width": [],
            "height": {},
        }
    ]

    result = normalize_overlay_boxes(items, page)

    assert len(result) == 1
    assert result[0] == {
        "x": 0.0,
        "y": 0.0,
        "w": 0.0,
        "h": 0.0,
        "text": "Invalid numbers",
    }
