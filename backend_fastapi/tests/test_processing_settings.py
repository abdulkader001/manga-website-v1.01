"""Processing settings endpoints (SRS Part 2: 2A.3, 2C.4.4, 2E.1, 2F.2)."""

from __future__ import annotations


def test_defaults_are_created_lazily(fastapi_client, auth_headers) -> None:
    response = fastapi_client.get("/api/user/processing-settings", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["usage_limit_unit"] == "pages"
    assert data["usage_limit_window"] == "week"
    assert data["usage_limit_value"] is None
    assert data["usage_current"] == 0
    assert data["ai_usage_current"] == 0
    # 2C.4.4: off by default.
    assert data["share_translations"] is False
    # 2A.3 / D12.
    assert data["ai_assist_enabled"] is True
    assert 0 <= data["ai_confidence_threshold"] <= 1
    # 2F.2B default scale.
    assert data["overlay_font_size"] == 20
    assert data["overlay_style"] == "white_box"
    assert data["overlay_font"] == "standard_sans"
    # D13 resolution: sound-effect translation on by default, opt-out.
    assert data["translate_sound_effects"] is True


def test_update_usage_limit_and_unit_switch_resets_period(
    fastapi_client, auth_headers
) -> None:
    resp = fastapi_client.patch(
        "/api/user/processing-settings",
        json={
            "usage_limit_unit": "words",
            "usage_limit_window": "day",
            "usage_limit_value": 500,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["usage_limit_unit"] == "words"
    assert data["usage_limit_window"] == "day"
    assert data["usage_limit_value"] == 500
    assert data["usage_current"] == 0


def test_invalid_unit_rejected(fastapi_client, auth_headers) -> None:
    resp = fastapi_client.patch(
        "/api/user/processing-settings",
        json={"usage_limit_unit": "dollars"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_invalid_confidence_threshold_rejected(fastapi_client, auth_headers) -> None:
    resp = fastapi_client.patch(
        "/api/user/processing-settings",
        json={"ai_confidence_threshold": 1.5},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_share_translations_toggle(fastapi_client, auth_headers) -> None:
    resp = fastapi_client.patch(
        "/api/user/processing-settings",
        json={"share_translations": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["share_translations"] is True


def test_overlay_font_must_be_curated(fastapi_client, auth_headers) -> None:
    resp = fastapi_client.patch(
        "/api/user/processing-settings",
        json={"overlay_font": "comic-sans-unlicensed"},
        headers=auth_headers,
    )
    assert resp.status_code == 400

    resp = fastapi_client.patch(
        "/api/user/processing-settings",
        json={"overlay_font": "wild_words"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["overlay_font"] == "wild_words"


def test_overlay_font_size_bounds(fastapi_client, auth_headers) -> None:
    resp = fastapi_client.patch(
        "/api/user/processing-settings",
        json={"overlay_font_size": 999},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_overlay_fonts_curated_list_endpoint(fastapi_client, auth_headers) -> None:
    resp = fastapi_client.get("/api/user/overlay-fonts", headers=auth_headers)
    assert resp.status_code == 200
    fonts = resp.json()["fonts"]
    categories = {f["category"] for f in fonts}
    assert {"standard", "anime_manga", "calligraphy", "handwriting"} <= categories


def test_reader_overlay_settings_round_trip(fastapi_client, auth_headers) -> None:
    url = "/api/user/processing-settings"
    body = fastapi_client.get(url, headers=auth_headers).json()
    assert body["overlay_enabled"] is True
    assert body["target_language"] == "en"
    assert body["context_translation"] is True

    resp = fastapi_client.put(
        url,
        json={
            "overlay_enabled": False,
            "target_language": "es",
            "overlay_text_color": "#FF0000",
            "overlay_box_color": "#101010",
            "overlay_box_opacity": 80,
            "context_translation": False,
            "overlay_font": "bangers",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overlay_enabled"] is False
    assert body["target_language"] == "es"
    assert body["overlay_text_color"] == "#ff0000"
    assert body["overlay_box_opacity"] == 80
    assert body["context_translation"] is False
    assert body["overlay_font"] == "bangers"

    # "" puts a colour back to automatic.
    resp = fastapi_client.put(url, json={"overlay_text_color": ""}, headers=auth_headers)
    assert resp.json()["overlay_text_color"] is None


def test_reader_overlay_settings_validation(fastapi_client, auth_headers) -> None:
    url = "/api/user/processing-settings"
    for payload in (
        {"overlay_text_color": "red"},
        {"overlay_box_opacity": 150},
        {"target_language": "xx"},
    ):
        assert fastapi_client.put(url, json=payload, headers=auth_headers).status_code == 400


def test_usage_limit_can_be_cleared(fastapi_client, auth_headers) -> None:
    url = "/api/user/processing-settings"
    fastapi_client.put(url, json={"usage_limit_value": 30, "usage_limit_window": "day"}, headers=auth_headers)
    resp = fastapi_client.put(url, json={"clear_usage_limit": True}, headers=auth_headers)
    assert resp.json()["usage_limit_value"] is None


def test_context_translation_off_skips_the_coherence_pass() -> None:
    from backend_fastapi.app.services.chapter_translation_service import translate_chapter_texts

    class _Literal:
        def translate(self, text, source_lang, target_lang, provider_config=None, **kw):
            return f"[{text}]"

        def coherence_pass(self, regions, **kw):  # pragma: no cover - must not run
            raise AssertionError("coherence pass ran although the reader turned it off")

    outcome: dict = {}
    out = translate_chapter_texts(
        ["안녕", "잘가"],
        translation_service=_Literal(),
        provider_config={"api_url": "https://example.test"},
        source_lang="ko",
        target_lang="en",
        coherence_provider_config={"api_url": "https://example.test/chat/completions", "model": "m"},
        coherence_outcome=outcome,
        context_aware=False,
    )
    assert out == ["[안녕]", "[잘가]"]
    assert outcome == {"applied": False, "reason": "disabled_by_user"}
