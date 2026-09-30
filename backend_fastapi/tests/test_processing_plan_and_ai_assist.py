"""Processing methods, provider priority, AI conflict handling (SRS 2A)."""

from __future__ import annotations

import json as _json

from PIL import Image

from backend_fastapi.app.services import ai_assist, ai_vision_assist, processing_plan


# --------------------------------------------------------------------------
# 2A.2 provider priority -- Case 1, 2, 3
# --------------------------------------------------------------------------


def test_case_1_user_ocr_and_translation_ai_idle_unless_assist() -> None:
    plan = processing_plan.resolve_plan(
        has_user_ocr=True, has_user_translation=True, has_user_ai=False
    )
    assert plan.case == processing_plan.CASE_USER_OCR_TRANSLATION
    assert plan.method == processing_plan.METHOD_OCR_TRANSLATION
    assert plan.ocr_source == "user"
    assert plan.translation_source == "user"
    assert plan.ai_role == "idle_unless_assist"


def test_case_1_with_ai_configured_is_hybrid_method() -> None:
    plan = processing_plan.resolve_plan(
        has_user_ocr=True, has_user_translation=True, has_user_ai=True
    )
    assert plan.method == processing_plan.METHOD_HYBRID
    assert plan.ai_source == "user"
    # AI must not unnecessarily consume resources: still idle unless assisting.
    assert plan.ai_role == "idle_unless_assist"


def test_case_2_ai_only() -> None:
    plan = processing_plan.resolve_plan(
        has_user_ocr=False, has_user_translation=False, has_user_ai=True
    )
    assert plan.case == processing_plan.CASE_USER_AI_ONLY
    assert plan.method == processing_plan.METHOD_AI
    assert plan.ai_source == "user"
    assert plan.ai_role == "primary"
    assert plan.ocr_source == "platform_default"
    assert plan.translation_source == "platform_default"


def test_case_3_nothing_configured() -> None:
    plan = processing_plan.resolve_plan(
        has_user_ocr=False, has_user_translation=False, has_user_ai=False
    )
    assert plan.case == processing_plan.CASE_PLATFORM_DEFAULT
    assert plan.method == processing_plan.METHOD_OCR_TRANSLATION
    assert plan.ocr_source == "platform_default"
    assert plan.translation_source == "platform_default"
    assert plan.ai_source == "platform_default"
    assert plan.ai_role == "fallback_only"


def test_partial_configuration_respects_whats_actually_configured() -> None:
    """Not one of the three named cases, but must not silently discard a
    user's own OCR key just because translation isn't configured too."""

    plan = processing_plan.resolve_plan(
        has_user_ocr=True, has_user_translation=False, has_user_ai=True
    )
    assert plan.ocr_source == "user"
    assert plan.translation_source == "platform_default"
    assert plan.ai_source == "user"
    assert plan.ai_role == "primary"


# --------------------------------------------------------------------------
# 2A.3 AI/OCR conflict handling
# --------------------------------------------------------------------------


def _region(index, text, confidence):
    return {"index": index, "text": text, "confidence": confidence}


def test_ai_idle_when_ocr_succeeded_on_everything() -> None:
    regions = [_region(0, "hello", 95.0), _region(1, "world", 92.0)]
    plan = ai_assist.plan_ai_assist(
        regions, ai_assist_enabled=True, confidence_threshold=0.6, ai_available=True
    )
    assert plan.mode == "none"
    assert plan.region_indices == []


def test_ai_assists_only_the_failed_or_low_confidence_regions() -> None:
    regions = [
        _region(0, "hello", 95.0),
        _region(1, "", 0.0),  # OCR failed entirely
        _region(2, "wxrld", 30.0),  # below threshold
        _region(3, "sure thing", 98.0),
    ]
    plan = ai_assist.plan_ai_assist(
        regions, ai_assist_enabled=True, confidence_threshold=0.6, ai_available=True
    )
    assert plan.mode == "per_region"
    assert plan.region_indices == [1, 2]


def test_ai_disabled_entirely_never_assists() -> None:
    regions = [_region(0, "", 0.0)]
    plan = ai_assist.plan_ai_assist(
        regions, ai_assist_enabled=False, confidence_threshold=0.6, ai_available=True
    )
    assert plan.mode == "none"


def test_ai_unavailable_never_assists_even_if_enabled() -> None:
    regions = [_region(0, "", 0.0)]
    plan = ai_assist.plan_ai_assist(
        regions, ai_assist_enabled=True, confidence_threshold=0.6, ai_available=False
    )
    assert plan.mode == "none"


def test_confidence_threshold_is_configurable() -> None:
    regions = [
        _region(0, "text", 70.0),
        _region(1, "clean", 99.0),
        _region(2, "clear", 97.0),
    ]
    lenient = ai_assist.plan_ai_assist(
        regions, ai_assist_enabled=True, confidence_threshold=0.5, ai_available=True
    )
    strict = ai_assist.plan_ai_assist(
        regions, ai_assist_enabled=True, confidence_threshold=0.8, ai_available=True
    )
    assert lenient.mode == "none"
    assert strict.mode == "per_region"
    assert strict.region_indices == [0]


def test_widespread_ocr_failure_triggers_whole_page_not_many_per_region_calls() -> None:
    """The planning half of the claim: which mode is chosen, and for which
    regions. That the mode then costs one call rather than N is asserted by
    the ``assist_page`` tests below and end-to-end in
    ``test_chapter_processing_service.py``."""

    regions = [_region(i, "" if i < 6 else "ok", 90.0) for i in range(10)]
    plan = ai_assist.plan_ai_assist(
        regions, ai_assist_enabled=True, confidence_threshold=0.6, ai_available=True
    )
    assert plan.mode == "whole_page"
    assert plan.region_indices == list(range(10))


# --------------------------------------------------------------------------
# 2A.3 whole-page batching (F-15)
# --------------------------------------------------------------------------

_PROVIDER = {"provider": "google_gemini", "api_url": "https://example.com/vision"}


def _boxed_region(index):
    return {
        "index": index,
        "coordinates": {
            "x": 10.0 + index * 50,
            "y": 20.0,
            "width": 40.0,
            "height": 25.0,
        },
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingProvider:
    """A vision provider that answers the batched contract and counts calls."""

    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "payload": json, "timeout": timeout})
        body = _json.dumps({"regions": self.entries})
        return _FakeResponse({"candidates": [{"content": {"parts": [{"text": body}]}}]})


def _prompt_of(call):
    return call["payload"]["contents"][0]["parts"][0]["text"]


def _graph_prompt_of(call):
    """The structured region list appended after the prompt's rules."""

    prompt = _prompt_of(call)
    return _json.loads(prompt[prompt.rindex("\n\n") + 2 :])


def test_whole_page_assist_sends_one_provider_call_for_all_flagged_regions() -> None:
    """F-15: the batched path is one HTTP call covering every flagged region,
    not one call per region as the old per-region loop made."""

    regions = [_boxed_region(i) for i in range(6)]
    provider = _RecordingProvider(
        [{"index": i, "text": f"text-{i}"} for i in range(6)]
    )

    corrections = ai_vision_assist.assist_page(
        Image.new("RGB", (400, 600), "white"),
        regions,
        provider_config=_PROVIDER,
        language_hint="ja",
        http_post=provider,
    )

    assert len(provider.calls) == 1
    assert corrections == {i: f"text-{i}" for i in range(6)}

    # The one call describes every flagged region, and carries the full page
    # image rather than six separate crops.
    parts = provider.calls[0]["payload"]["contents"][0]["parts"]
    assert "inline_data" in parts[1]
    listed = _graph_prompt_of(provider.calls[0])
    assert [entry["index"] for entry in listed["regions"]] == list(range(6))


def test_batched_page_response_maps_onto_regions_out_of_order() -> None:
    """Regions are spliced back by index, not by position, so neither the
    request order nor the reply order can misalign text against bubbles."""

    regions = [_boxed_region(4), _boxed_region(1), _boxed_region(7)]
    provider = _RecordingProvider(
        [
            {"index": 7, "text": "seven"},
            {"index": 4, "text": "four"},
            {"index": 1, "text": "one"},
        ]
    )

    corrections = ai_vision_assist.assist_page(
        Image.new("RGB", (400, 600), "white"),
        regions,
        provider_config=_PROVIDER,
        http_post=provider,
    )

    assert corrections == {4: "four", 1: "one", 7: "seven"}


def test_batched_page_response_drops_regions_it_was_never_asked_about() -> None:
    provider = _RecordingProvider(
        [
            {"index": 1, "text": "kept"},
            {"index": 99, "text": "never requested"},
            {"index": 1, "text": "answered twice"},
            {"index": 4, "text": "   "},
        ]
    )

    corrections = ai_vision_assist.assist_page(
        Image.new("RGB", (400, 600), "white"),
        [_boxed_region(1), _boxed_region(4)],
        provider_config=_PROVIDER,
        http_post=provider,
    )

    # Unknown index dropped, duplicate ignored, blank transcription is not a
    # "correction" -- region 4 keeps whatever OCR gave it.
    assert corrections == {1: "kept"}


def test_page_assist_boxes_are_scaled_to_the_image_the_model_receives() -> None:
    """A page longer than MAX_PAGE_IMAGE_DIM is downscaled before sending, so
    the coordinates in the prompt must be downscaled by the same factor."""

    provider = _RecordingProvider([{"index": 0, "text": "ok"}])
    big = Image.new("RGB", (1600, 3200), "white")

    ai_vision_assist.assist_page(
        big,
        [{"index": 0, "coordinates": {"x": 800, "y": 1600, "width": 400, "height": 200}}],
        provider_config=_PROVIDER,
        http_post=provider,
    )

    listed = _graph_prompt_of(provider.calls[0])
    assert listed["image_size"] == {"width": 800, "height": 1600}
    assert listed["regions"][0]["box"] == {
        "x": 400,
        "y": 800,
        "width": 200,
        "height": 100,
    }


def test_page_assist_returns_nothing_without_a_vision_capable_provider() -> None:
    provider = _RecordingProvider([{"index": 0, "text": "unused"}])

    assert (
        ai_vision_assist.assist_page(
            Image.new("RGB", (100, 100), "white"),
            [_boxed_region(0)],
            provider_config={"provider": "libretranslate", "api_url": "https://x"},
            http_post=provider,
        )
        == {}
    )
    assert provider.calls == []


def test_page_assist_survives_a_provider_error_without_correcting_anything() -> None:
    def _explode(*_args, **_kwargs):
        raise RuntimeError("provider down")

    assert (
        ai_vision_assist.assist_page(
            Image.new("RGB", (100, 100), "white"),
            [_boxed_region(0)],
            provider_config=_PROVIDER,
            http_post=_explode,
        )
        == {}
    )
