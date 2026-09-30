"""Chapter/page processing orchestration: cache short-circuit, priority,
AI assist, chapter context, cache admin mechanisms, usage limits (2F.1)."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.api_errors import ApiError
from backend_fastapi.app.models import Chapter, Manga, OcrCache, TranslationCache, User
from backend_fastapi.app.services import (
    cache_admin_service,
    chapter_processing_service as cps,
    processing_settings_service,
)
from backend_fastapi.app.services.processing_plan import resolve_plan


@pytest.fixture(autouse=True)
def _ensure_tables(fastapi_app):
    """db_session-only tests don't otherwise trigger the session-scoped
    schema creation that fastapi_app performs."""

    yield


def _make_chapter(db, *, pages=None) -> Chapter:
    manga = Manga(
        title=f"Processing Test {uuid.uuid4().hex[:8]}",
        source_url=f"https://example.com/manga/{uuid.uuid4().hex}",
    )
    db.add(manga)
    db.commit()
    db.refresh(manga)
    chapter = Chapter(
        manga_id=manga.id,
        chapter_number=1,
        chapter_url=f"https://example.com/chapter/{uuid.uuid4().hex}",
        pages=pages or ["page-0.jpg", "page-1.jpg"],
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    # SQLite reuses rowids after a bulk delete elsewhere in the suite;
    # defensively clear any orphaned cache rows that might otherwise
    # collide with this fresh chapter's (recycled) id.
    db.query(TranslationCache).filter(
        TranslationCache.chapter_id == chapter.id
    ).delete()
    db.query(OcrCache).filter(OcrCache.chapter_id == chapter.id).delete()
    db.commit()
    return chapter


def _make_user(db) -> User:
    user = User(
        email=f"chapterproc-{uuid.uuid4().hex}@example.com",
        is_active=True,
        provider="magic_link",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _normalized(texts_confidences):
    regions = []
    for i, (text, conf) in enumerate(texts_confidences):
        regions.append(
            {
                "index": i,
                "text": text,
                "coordinates": {
                    "x": 10.0 + i * 50,
                    "y": 10.0,
                    "width": 40.0,
                    "height": 20.0,
                },
                "confidence": conf,
                "region_type": "speech_bubble",
                "reading_order": i,
            }
        )
    return {
        "regions": regions,
        "detected_language": "ja",
        "detected_script": "cjk",
        "reading_order_mode": "rtl_vertical",
        "engine_tier": 2,
    }


class PassthroughTranslator:
    def __init__(self):
        self.calls = 0

    def translate(self, text, source_lang, target_lang, provider_config=None, **_):
        self.calls += 1
        # A numbered-line round trip so translate_chapter_texts's fast path
        # (one call for the whole page) succeeds deterministically.
        lines = []
        for line in text.splitlines():
            n, _, rest = line.partition("] ")
            lines.append(f"{n}] EN:{rest}")
        return "\n".join(lines)


class CoherenceTranslator(PassthroughTranslator):
    """Stage A drafts literally; Stage B (2C.1) rewrites the whole page.

    Records what context it was handed so the upstream assembly -- glossary,
    region metadata, previous-page lines, chapter summary -- is assertable.
    """

    def __init__(self):
        super().__init__()
        self.coherence_calls: list[dict] = []

    def coherence_pass(self, regions, *, outcome=None, **context):
        self.coherence_calls.append({"regions": list(regions), **context})
        if outcome is not None:
            outcome["applied"] = True
            outcome["reason"] = "ok"
            outcome["provider"] = "fake_chat"
        return [
            (
                f"COHERENT:{r['literal_translation']}"
                if str(r["source_text"]).strip()
                else ""
            )
            for r in regions
        ]


def _cps_kwargs(db, chapter, user, **overrides):
    plan = resolve_plan(
        has_user_ocr=False, has_user_translation=False, has_user_ai=False
    )
    settings = processing_settings_service.get_or_create(db, user.id)
    kwargs = dict(
        db=db,
        chapter=chapter,
        page_index=0,
        target_lang="en",
        user_id=user.id,
        plan=plan,
        processing_settings=settings,
        fetch_image_bytes=lambda url: b"fake-image-bytes",
        ocr_runner=lambda image_bytes, hint: _normalized(
            [("Hello", 95.0), ("World", 92.0)]
        ),
        translation_service=PassthroughTranslator(),
        translation_provider_config={
            "provider": "custom",
            "api_url": "https://example.com",
        },
        ai_provider_config=None,
    )
    kwargs.update(overrides)
    return kwargs


def test_full_pipeline_ocr_and_translate_and_cache(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    result = cps.process_page(**_cps_kwargs(db_session, chapter, user))

    assert result.cached is False
    assert result.ocr_cached is False
    assert [r["text"] for r in result.regions] == ["EN:Hello", "EN:World"]
    assert result.detected_language == "ja"

    # Platform-default processing always contributes to the shared cache.
    tc = (
        db_session.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter.id, TranslationCache.page_index == 0
        )
        .one()
    )
    assert tc.contributed_by_sharing is False
    assert [r["text"] for r in tc.regions] == ["EN:Hello", "EN:World"]

    oc = (
        db_session.query(OcrCache)
        .filter(OcrCache.chapter_id == chapter.id, OcrCache.page_index == 0)
        .one()
    )
    assert oc.detected_language == "ja"


def test_stage_b_output_is_what_reaches_the_shared_cache(db_session) -> None:
    """2C.1: the coherence pass runs on Stage A's drafts, and its output --
    not the literal draft -- is what the quality gate is asked to store."""

    from backend_fastapi.app.services import glossary_service

    chapter = _make_chapter(db_session)
    user = _make_user(db_session)
    glossary_service.upsert_term(db_session, chapter.manga_id, "en", "シスイ", "Shisui")

    translator = CoherenceTranslator()
    result = cps.process_page(
        **_cps_kwargs(
            db_session,
            chapter,
            user,
            translation_service=translator,
            series_title="Blade of the Ninth",
            genres=["action"],
        )
    )

    assert result.coherence_applied is True
    assert [r["text"] for r in result.regions] == [
        "COHERENT:EN:Hello",
        "COHERENT:EN:World",
    ]

    tc = (
        db_session.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter.id, TranslationCache.page_index == 0
        )
        .one()
    )
    assert [r["text"] for r in tc.regions] == [
        "COHERENT:EN:Hello",
        "COHERENT:EN:World",
    ]

    # The context assembled upstream actually arrived at Stage B.
    assert len(translator.coherence_calls) == 1
    call = translator.coherence_calls[0]
    assert call["glossary"] == {"シスイ": "Shisui"}
    assert call["target_lang"] == "en"
    assert "Blade of the Ninth" in call["chapter_summary"]
    assert "action" in call["chapter_summary"]
    assert [r["region_type"] for r in call["regions"]] == [
        "speech_bubble",
        "speech_bubble",
    ]
    assert [r["literal_translation"] for r in call["regions"]] == [
        "EN:Hello",
        "EN:World",
    ]


def test_previous_page_lines_are_passed_to_the_coherence_pass(db_session) -> None:
    from backend_fastapi.app.services import translation_cache_service

    chapter = _make_chapter(db_session)
    user = _make_user(db_session)
    translation_cache_service.put_translation_cache(
        db_session,
        chapter.id,
        0,
        "en",
        ["EN:Earlier", "EN:Line"],
        regions=[
            {"index": 0, "text": "EN:Earlier"},
            {"index": 1, "text": "EN:Line"},
        ],
    )

    translator = CoherenceTranslator()
    cps.process_page(
        **_cps_kwargs(
            db_session,
            chapter,
            user,
            page_index=1,
            translation_service=translator,
        )
    )

    call = translator.coherence_calls[0]
    assert call["previous_page_last_lines"] == ["EN:Earlier", "EN:Line"]


def test_client_side_drafts_skip_the_server_side_stage_a_call(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    translator = CoherenceTranslator()
    result = cps.process_page(
        **_cps_kwargs(
            db_session,
            chapter,
            user,
            translation_service=translator,
            client_draft_translations=["Client Hello", "Client World"],
        )
    )

    assert translator.calls == 0  # Pipeline 1 already paid for these
    assert [r["text"] for r in result.regions] == [
        "COHERENT:Client Hello",
        "COHERENT:Client World",
    ]


def test_translation_cache_hit_short_circuits_everything(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    calls = {"ocr": 0, "translate": 0}

    def counting_ocr(image_bytes, hint):
        calls["ocr"] += 1
        return _normalized([("Hi", 95.0)])

    class CountingTranslator(PassthroughTranslator):
        def translate(self, *a, **kw):
            calls["translate"] += 1
            return super().translate(*a, **kw)

    kwargs = _cps_kwargs(
        db_session,
        chapter,
        user,
        ocr_runner=counting_ocr,
        translation_service=CountingTranslator(),
    )
    first = cps.process_page(**kwargs)
    assert first.cached is False
    assert calls["ocr"] == 1

    # Second call for the same chapter/page/lang must hit the cache and
    # never touch OCR or translation again.
    kwargs2 = _cps_kwargs(
        db_session,
        chapter,
        user,
        ocr_runner=counting_ocr,
        translation_service=CountingTranslator(),
    )
    second = cps.process_page(**kwargs2)
    assert second.cached is True
    assert calls["ocr"] == 1  # unchanged


def test_ocr_cache_hit_skips_ocr_but_still_translates(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    from backend_fastapi.app.services import translation_cache_service

    translation_cache_service.put_ocr_cache(
        db_session,
        chapter.id,
        0,
        ["Hello"],
        regions=_normalized([("Hello", 95.0)])["regions"],
        detected_language="ja",
        detected_script="cjk",
        reading_order_mode="rtl_vertical",
        engine_tier=2,
    )

    calls = {"ocr": 0}

    def counting_ocr(image_bytes, hint):
        calls["ocr"] += 1
        return _normalized([("Hello", 95.0)])

    result = cps.process_page(
        **_cps_kwargs(db_session, chapter, user, ocr_runner=counting_ocr)
    )
    assert calls["ocr"] == 0
    assert result.ocr_cached is True
    assert result.regions[0]["text"] == "EN:Hello"


def test_cache_priority_off_skips_translation_cache_read_but_ocr_cache_still_used(
    db_session,
) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    cache_admin_service.set_cache_priority(db_session, "off")
    try:
        first = cps.process_page(**_cps_kwargs(db_session, chapter, user))
        assert first.cached is False

        calls = {"ocr": 0}

        def counting_ocr(image_bytes, hint):
            calls["ocr"] += 1
            return _normalized([("Hello", 95.0), ("World", 92.0)])

        # cache_priority=off means the SECOND read does not take the
        # translation-cache shortcut...
        second = cps.process_page(
            **_cps_kwargs(db_session, chapter, user, ocr_runner=counting_ocr)
        )
        assert second.cached is False
        # ...but the OCR cache (a distinct optimisation) is still reused.
        assert calls["ocr"] == 0
    finally:
        cache_admin_service.set_cache_priority(db_session, "on")


def test_reader_can_explicitly_request_cached_even_when_priority_off(
    db_session,
) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    cache_admin_service.set_cache_priority(db_session, "off")
    try:
        cps.process_page(**_cps_kwargs(db_session, chapter, user))
        second = cps.process_page(
            **_cps_kwargs(db_session, chapter, user, reader_requested_cached=True)
        )
        assert second.cached is True
    finally:
        cache_admin_service.set_cache_priority(db_session, "on")


def test_ai_assist_corrects_low_confidence_region_and_consumes_ai_quota(
    db_session,
) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    def flaky_ocr(image_bytes, hint):
        return _normalized([("Hello", 95.0), ("", 0.0)])

    def fake_load_image(image_bytes):
        return object()  # any truthy sentinel; assist_region is mocked below

    from unittest.mock import patch

    with patch(
        "backend_fastapi.app.services.chapter_processing_service.ai_vision_assist.assist_region",
        return_value="Corrected",
    ):
        result = cps.process_page(
            **_cps_kwargs(
                db_session,
                chapter,
                user,
                ocr_runner=flaky_ocr,
                ai_provider_config={
                    "provider": "google_gemini",
                    "api_url": "https://example.com",
                },
                load_image_for_vision=fake_load_image,
            )
        )

    assert result.ai_assisted_regions == [1]
    assert result.regions[1]["source_text"] == "Corrected"

    settings = processing_settings_service.get_or_create(db_session, user.id)
    assert settings.ai_usage_current == 1
    assert settings.usage_current == 1  # OCR step still counted once


def test_widespread_ocr_failure_makes_one_vision_call_not_one_per_region(
    db_session,
) -> None:
    """F-15: with over half the page's OCR failed, ``plan_ai_assist`` picks
    ``whole_page`` and the consumer must dispatch a single combined vision
    call -- not the per-region loop, which would have made four here."""

    import json as _json

    from PIL import Image

    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    def broken_ocr(image_bytes, hint):
        return _normalized([("", 0.0), ("", 0.0), ("", 0.0), ("Fine", 96.0)])

    calls: list[dict] = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            # Deliberately out of index order: the consumer must splice by
            # index, not by the order the provider happened to answer in.
            body = _json.dumps(
                {
                    "regions": [
                        {"index": 2, "text": "third"},
                        {"index": 0, "text": "first"},
                        {"index": 1, "text": "second"},
                    ]
                }
            )
            return {"candidates": [{"content": {"parts": [{"text": body}]}}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "payload": json})
        return _Response()

    from unittest.mock import patch

    with patch(
        "backend_fastapi.app.services.ai_vision_assist.requests.post", fake_post
    ):
        result = cps.process_page(
            **_cps_kwargs(
                db_session,
                chapter,
                user,
                ocr_runner=broken_ocr,
                ai_provider_config={
                    "provider": "google_gemini",
                    "api_url": "https://example.com",
                },
                load_image_for_vision=lambda image_bytes: Image.new(
                    "RGB", (300, 400), "white"
                ),
            )
        )

    assert len(calls) == 1
    assert result.ai_assisted_regions == [0, 1, 2]
    assert [r["source_text"] for r in result.regions] == [
        "first",
        "second",
        "third",
        "Fine",
    ]

    settings = processing_settings_service.get_or_create(db_session, user.id)
    assert settings.ai_usage_current == 1  # one page-level AI operation


def test_user_owned_translation_not_shared_unless_opted_in(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)
    plan = resolve_plan(has_user_ocr=True, has_user_translation=True, has_user_ai=False)

    result = cps.process_page(**_cps_kwargs(db_session, chapter, user, plan=plan))
    assert result.cached is False

    tc = (
        db_session.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter.id, TranslationCache.page_index == 0
        )
        .one_or_none()
    )
    assert tc is None  # not written -- user hasn't opted into Mechanism B


def test_user_owned_translation_shared_when_opted_in(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)
    processing_settings_service.update(
        db_session, user.id, {"share_translations": True}
    )
    plan = resolve_plan(has_user_ocr=True, has_user_translation=True, has_user_ai=False)

    cps.process_page(**_cps_kwargs(db_session, chapter, user, plan=plan))

    tc = (
        db_session.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter.id, TranslationCache.page_index == 0
        )
        .one()
    )
    assert tc.contributed_by_sharing is True


def test_usage_limit_enforced_before_fresh_processing(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)
    processing_settings_service.update(db_session, user.id, {"usage_limit_value": 1})
    settings = processing_settings_service.get_or_create(db_session, user.id)
    settings.usage_current = 1
    db_session.commit()

    with pytest.raises(ApiError):
        cps.process_page(**_cps_kwargs(db_session, chapter, user))


def test_cached_reads_never_consume_quota(db_session) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)

    cps.process_page(**_cps_kwargs(db_session, chapter, user))
    settings = processing_settings_service.get_or_create(db_session, user.id)
    after_first = settings.usage_current
    assert after_first == 1

    cps.process_page(**_cps_kwargs(db_session, chapter, user))  # cache hit
    db_session.refresh(settings)
    assert settings.usage_current == after_first  # unchanged
