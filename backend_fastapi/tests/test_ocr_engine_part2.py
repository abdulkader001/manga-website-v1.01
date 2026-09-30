"""OCR engine: script model, region detection, reading order (SRS 2B)."""

from __future__ import annotations

from unittest.mock import patch

from backend_fastapi.app.services import (
    ocr_normalize,
    reading_order,
    region_classifier,
    script_registry,
)
from backend_fastapi.app.services.ocr_service import OCRService


# --------------------------------------------------------------------------
# 2B.1 script model
# --------------------------------------------------------------------------


def test_every_spec_language_maps_to_a_script() -> None:
    expected = {
        "ja": "cjk",
        "zh-Hans": "cjk",
        "zh-Hant": "cjk",
        "ko": "cjk",
        "en": "latin",
        "fil": "latin",
        "id": "latin",
        "es": "latin",
        "pt": "latin",
        "fr": "latin",
        "hi": "indic",
        "ta": "indic",
        "bn": "indic",
        "te": "indic",
        "mr": "indic",
        "ar": "arabic_hebrew",
        "ur": "arabic_hebrew",
        "he": "arabic_hebrew",
        "fa": "arabic_hebrew",
        "ru": "cyrillic",
        "uk": "cyrillic",
        "th": "thai_khmer_lao",
        "km": "thai_khmer_lao",
        "lo": "thai_khmer_lao",
    }
    for lang, script in expected.items():
        assert script_registry.script_for_language(lang) == script, lang


def test_adding_a_latin_language_is_configuration_only() -> None:
    """2G acceptance: 'adding a Latin-script language requires configuration
    only -- verified by adding one'."""

    assert script_registry.script_for_language("de") is None
    script_registry.SCRIPTS[script_registry.SCRIPT_LATIN]["languages"].append("de")
    try:
        assert script_registry.script_for_language("de") == script_registry.SCRIPT_LATIN
    finally:
        script_registry.SCRIPTS[script_registry.SCRIPT_LATIN]["languages"].remove("de")


def test_language_pack_sizes_are_within_spec_range() -> None:
    for lang, size in script_registry.LANGUAGE_PACK_SIZE_MB.items():
        assert 2.0 <= size <= 15.0, lang


# --------------------------------------------------------------------------
# Script/language detection (feeds 2B.6 detected_language/detected_script)
# --------------------------------------------------------------------------


def test_detect_japanese_from_hiragana_katakana() -> None:
    lang, script = script_registry.detect_language("こんにちは カタカナ")
    assert lang == "ja"
    assert script == script_registry.SCRIPT_CJK


def test_detect_korean_from_hangul() -> None:
    lang, script = script_registry.detect_language("안녕하세요")
    assert lang == "ko"
    assert script == script_registry.SCRIPT_CJK


def test_detect_chinese_prefers_hint_variant() -> None:
    lang, script = script_registry.detect_language("你好世界", hint="zh-Hant")
    assert lang == "zh-Hant"
    assert script == script_registry.SCRIPT_CJK


def test_detect_arabic() -> None:
    lang, script = script_registry.detect_language("مرحبا بالعالم")
    assert lang == "ar"
    assert script == script_registry.SCRIPT_ARABIC_HEBREW


def test_latin_hint_is_never_a_constraint_when_script_disagrees() -> None:
    # 1H.9.1: a website's declared language is a hint, never a constraint.
    # Japanese characters must win over a Spanish hint.
    lang, script = script_registry.detect_language("こんにちは", hint="es")
    assert lang == "ja"
    assert script == script_registry.SCRIPT_CJK


def test_latin_uses_hint_to_disambiguate_within_script() -> None:
    lang, _script = script_registry.detect_language("Hola amigos", hint="es")
    assert lang == "es"


# --------------------------------------------------------------------------
# 2B.4 reading order
# --------------------------------------------------------------------------

PAGE = {"width": 1000, "height": 1500}


def _region(x, y, w=100, h=80):
    return {"coordinates": {"x": x, "y": y, "width": w, "height": h}}


def test_japanese_reading_order_is_right_to_left_top_to_bottom() -> None:
    regions = [_region(50, 50), _region(500, 50), _region(850, 50)]
    order = reading_order.compute_reading_order(
        regions, PAGE, mode=reading_order.MODE_RTL_VERTICAL
    )
    # Rightmost region (x=850) must be read first.
    assert order[2] == 0
    assert order[1] == 1
    assert order[0] == 2


def test_korean_webtoon_is_pure_top_to_bottom() -> None:
    regions = [_region(700, 400), _region(100, 100), _region(300, 900)]
    order = reading_order.compute_reading_order(
        regions, PAGE, mode=reading_order.MODE_TTB_COLUMN
    )
    assert order[1] == 0  # y=100 first
    assert order[0] == 1  # y=400 second
    assert order[2] == 2  # y=900 last


def test_latin_reading_order_is_left_to_right_top_to_bottom() -> None:
    regions = [_region(600, 50), _region(50, 50), _region(300, 900)]
    order = reading_order.compute_reading_order(
        regions, PAGE, mode=reading_order.MODE_LTR_TTB
    )
    assert order[1] == 0  # leftmost, top row
    assert order[0] == 1  # rightmost, same row
    assert order[2] == 2  # bottom row


def test_empty_regions_return_empty_order() -> None:
    assert reading_order.compute_reading_order([], PAGE, mode="ltr_ttb") == []


# --------------------------------------------------------------------------
# 2B.3 region type classification (heuristic, geometry-only branch)
# --------------------------------------------------------------------------


def test_top_wide_box_classified_as_narration() -> None:
    box = {"x": 50, "y": 10, "width": 900, "height": 60}
    region_type = region_classifier.classify_region(box, page=PAGE, confidence=95)
    assert region_type == region_classifier.REGION_NARRATION_BOX


def test_small_square_box_classified_as_circle() -> None:
    box = {"x": 400, "y": 400, "width": 90, "height": 92}
    region_type = region_classifier.classify_region(box, page=PAGE, confidence=95)
    assert region_type == region_classifier.REGION_CIRCLE


def test_wide_short_box_mid_page_classified_as_rectangle() -> None:
    box = {"x": 300, "y": 700, "width": 400, "height": 60}
    region_type = region_classifier.classify_region(box, page=PAGE, confidence=95)
    assert region_type == region_classifier.REGION_RECTANGLE


def test_default_box_classified_as_speech_bubble() -> None:
    box = {"x": 300, "y": 700, "width": 200, "height": 150}
    region_type = region_classifier.classify_region(box, page=PAGE, confidence=95)
    assert region_type == region_classifier.REGION_SPEECH_BUBBLE


# --------------------------------------------------------------------------
# 2B.6 normalized output shape
# --------------------------------------------------------------------------


def test_normalized_output_matches_2b6_shape() -> None:
    raw_regions = [
        {
            "text": "こんにちは",
            "x": 850,
            "y": 50,
            "width": 100,
            "height": 80,
            "confidence": 91.0,
        },
        {
            "text": "世界",
            "x": 50,
            "y": 50,
            "width": 100,
            "height": 80,
            "confidence": 88.0,
        },
    ]
    result = ocr_normalize.build_normalized_output(
        raw_regions, page=PAGE, provider_id="google_cloud_vision"
    )
    assert set(result.keys()) == {
        "regions",
        "detected_language",
        "detected_script",
        "reading_order_mode",
        "engine_tier",
    }
    assert result["detected_language"] == "ja"
    assert result["detected_script"] == "cjk"
    assert result["reading_order_mode"] == "rtl_vertical"
    assert result["engine_tier"] == 4

    regions = result["regions"]
    assert len(regions) == 2
    for region in regions:
        assert set(region.keys()) == {
            "index",
            "text",
            "coordinates",
            "confidence",
            "region_type",
            "reading_order",
        }
        assert set(region["coordinates"].keys()) == {"x", "y", "width", "height"}

    # Right-to-left: the rightmost region (x=850) reads first.
    assert regions[0]["reading_order"] == 0
    assert regions[0]["text"] == "こんにちは"


def test_frontend_cannot_tell_engines_apart() -> None:
    """Same input geometry through two different provider_ids yields the
    same shape -- only engine_tier differs."""

    raw_regions = [
        {
            "text": "Hello",
            "x": 50,
            "y": 50,
            "width": 100,
            "height": 40,
            "confidence": 92.0,
        }
    ]
    local = ocr_normalize.build_normalized_output(
        raw_regions, page=PAGE, provider_id="tesseract_local"
    )
    remote = ocr_normalize.build_normalized_output(
        raw_regions, page=PAGE, provider_id="azure_computer_vision"
    )
    local.pop("engine_tier")
    remote.pop("engine_tier")
    assert local == remote


# --------------------------------------------------------------------------
# OCRService: grouping words into regions + the normalized end-to-end path
# --------------------------------------------------------------------------


def test_run_tesseract_regions_groups_by_block_and_paragraph() -> None:
    service = OCRService()
    fake_rows = [
        {
            "text": "Hello",
            "conf": 90.0,
            "left": 10,
            "top": 10,
            "width": 40,
            "height": 20,
            "block_num": 1,
            "par_num": 1,
            "line_num": 1,
            "word_num": 1,
        },
        {
            "text": "world",
            "conf": 88.0,
            "left": 55,
            "top": 10,
            "width": 40,
            "height": 20,
            "block_num": 1,
            "par_num": 1,
            "line_num": 1,
            "word_num": 2,
        },
        {
            "text": "Bye",
            "conf": 70.0,
            "left": 300,
            "top": 400,
            "width": 30,
            "height": 20,
            "block_num": 2,
            "par_num": 1,
            "line_num": 1,
            "word_num": 1,
        },
    ]
    with patch.object(service, "_tesseract_tsv_raw_rows", return_value=fake_rows):
        regions = service._run_tesseract_regions(object(), None, None)

    assert len(regions) == 2
    assert regions[0]["text"] == "Hello world"
    assert regions[0]["left"] == 10
    assert regions[0]["width"] == (55 + 40) - 10
    assert regions[1]["text"] == "Bye"


def test_extract_normalized_remote_produces_2b6_shape(monkeypatch) -> None:
    service = OCRService()
    service.remote_url = "https://example.com/ocr"

    def fake_extract_remote(image_data, psm, lang, cfg):
        return {
            "items": [
                {
                    "text": "Hello",
                    "left": 10,
                    "top": 10,
                    "width": 40,
                    "height": 20,
                    "confidence": 91.0,
                }
            ],
            "page": {"width": 500, "height": 800},
        }

    monkeypatch.setattr(service, "_extract_remote", fake_extract_remote)

    result = service.extract_normalized(
        b"not-really-an-image",
        provider_config={"provider": "custom", "api_url": "https://example.com/ocr"},
    )

    assert result["engine_tier"] == 2
    assert result["regions"][0]["text"] == "Hello"
    assert result["regions"][0]["coordinates"] == {
        "x": 10.0,
        "y": 10.0,
        "width": 40.0,
        "height": 20.0,
    }
