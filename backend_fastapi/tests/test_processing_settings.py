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
