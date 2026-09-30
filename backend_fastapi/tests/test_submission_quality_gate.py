"""Content-based write authority for the shared cache.

Provider tier put every untrusted engine (tesseract_local, custom,
ocr_space_free, system) into the same "free" bucket and then let any write
at >= the stored tier through untouched, so one free-tier submission could
overwrite another with no comparison of the text at all -- and
``pill_service`` rewarded whoever landed last. These tests pin the
replacement behaviour: equal tier is decided by the submitted text.
"""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.models import Chapter, Manga, OcrCache, TranslationCache, User
from backend_fastapi.app.models.community import Pill
from backend_fastapi.app.services import (
    chapter_processing_service as cps,
    processing_settings_service,
    submission_quality_gate as gate,
    translation_cache_service as cache_service,
)
from backend_fastapi.app.services.ocr_normalize import engine_tier_for
from backend_fastapi.app.services.processing_plan import resolve_plan

GOOD = ["Are you really going to fight him alone?", "I have no other choice."]
BETTER = ["Are you really planning to fight him by yourself?", "There's no other way."]
# Plausible enough to survive the cheap rules (right script, right rough
# length) but a worse rendering -- the case that has to reach the scorer.
WORSE = ["you fight him alone question yes or no", "not any choice have I got"]
# Fails the cheap rules outright: far too short to render this source page.
GARBAGE = ["zzzz", "zzzz"]
SOURCE = ["Kimi wa hontou ni hitori de tatakau no ka?", "Hoka ni michi wa nai."]


@pytest.fixture(autouse=True)
def _ensure_tables(fastapi_app):
    """db_session-only tests don't otherwise trigger the session-scoped
    schema creation that fastapi_app performs."""

    yield


def _make_chapter(db) -> Chapter:
    manga = Manga(
        title=f"Gate Test {uuid.uuid4().hex[:8]}",
        source_url=f"https://example.com/manga/{uuid.uuid4().hex}",
    )
    db.add(manga)
    db.commit()
    db.refresh(manga)
    chapter = Chapter(
        manga_id=manga.id,
        chapter_number=1,
        chapter_url=f"https://example.com/chapter/{uuid.uuid4().hex}",
        pages=["page-0.jpg"],
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    # SQLite reuses rowids after bulk deletes elsewhere in the suite; clear
    # any orphaned cache rows that would otherwise look like an incumbent.
    db.query(TranslationCache).filter(
        TranslationCache.chapter_id == chapter.id
    ).delete()
    db.query(OcrCache).filter(OcrCache.chapter_id == chapter.id).delete()
    db.commit()
    return chapter


def _make_user(db) -> User:
    user = User(
        email=f"gate-{uuid.uuid4().hex}@example.com",
        is_active=True,
        provider="magic_link",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _scorer(scores: dict):
    """Stand-in for the configured chat-completion provider: maps the exact
    candidate text to a score so a test can state "this one is better"."""

    calls = []

    def score(candidate_text, *, source_text="", target_lang=None, **_):
        calls.append(candidate_text)
        return scores.get(candidate_text)

    score.calls = calls
    return score


def _contribute(db, chapter, user, boxes, *, scorer=None, provider="custom"):
    return cache_service.put_translation_cache(
        db,
        chapter.id,
        0,
        "en",
        boxes,
        quality_tier="free",
        provider=provider,
        source_boxes=SOURCE,
        contributed_by_sharing=True,
        contributed_by_user_id=user.id,
        quality_scorer=scorer,
    )


# --- the vulnerability being closed ---------------------------------------


def test_every_untrusted_engine_still_collapses_into_the_free_tier() -> None:
    """The premise of the flood: provider tier cannot tell these apart, so
    it cannot be what authorises a write."""

    for provider in ("tesseract_local", "custom", "ocr_space_free", "system"):
        assert cps._quality_tier_for(engine_tier_for(provider)) == "free", provider


def test_equal_tier_submission_with_worse_content_is_rejected(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, flooder = _make_user(db_session), _make_user(db_session)
    scorer = _scorer(
        {gate.normalize_text(GOOD): 82.0, gate.normalize_text(WORSE): 31.0}
    )

    _contribute(db_session, chapter, incumbent, GOOD, scorer=scorer)
    written = _contribute(db_session, chapter, flooder, WORSE, scorer=scorer)

    assert written.translated_boxes == GOOD
    assert written.contributed_by_user_id == incumbent.id
    # The incumbent's score was computed to judge the challenger and is
    # kept, so the next flood attempt is compared without rescoring it.
    assert written.quality_score == 82.0


def test_equal_tier_submission_with_better_content_is_accepted(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, improver = _make_user(db_session), _make_user(db_session)
    scorer = _scorer(
        {gate.normalize_text(GOOD): 62.0, gate.normalize_text(BETTER): 91.0}
    )

    _contribute(db_session, chapter, incumbent, GOOD, scorer=scorer)
    written = _contribute(db_session, chapter, improver, BETTER, scorer=scorer)

    assert written.translated_boxes == BETTER
    assert written.contributed_by_user_id == improver.id
    assert written.quality_score == 91.0


def test_equal_score_is_not_better_and_does_not_win(db_session) -> None:
    """ "Strictly better" -- a tie leaves the incumbent in place, so
    resubmitting equivalent work can't churn ownership of the entry."""

    chapter = _make_chapter(db_session)
    incumbent, challenger = _make_user(db_session), _make_user(db_session)
    scorer = _scorer(
        {gate.normalize_text(GOOD): 70.0, gate.normalize_text(BETTER): 70.0}
    )

    _contribute(db_session, chapter, incumbent, GOOD, scorer=scorer)
    written = _contribute(db_session, chapter, challenger, BETTER, scorer=scorer)

    assert written.translated_boxes == GOOD
    assert written.contributed_by_user_id == incumbent.id


def test_untrusted_submission_is_rejected_when_no_scorer_is_configured(
    db_session,
) -> None:
    """Without a scoring provider there is no evidence the challenger is
    better, and "no evidence" must not mean "overwrite"."""

    chapter = _make_chapter(db_session)
    incumbent, flooder = _make_user(db_session), _make_user(db_session)

    _contribute(db_session, chapter, incumbent, GOOD)
    written = _contribute(db_session, chapter, flooder, WORSE)

    assert written.translated_boxes == GOOD
    assert written.contributed_by_user_id == incumbent.id


# --- the cheap layers: nothing above should have paid for a model call ----


def test_exact_duplicate_resubmission_never_reaches_the_scorer(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, copycat = _make_user(db_session), _make_user(db_session)
    scorer = _scorer({gate.normalize_text(GOOD): 82.0})

    _contribute(db_session, chapter, incumbent, GOOD, scorer=scorer)
    scorer.calls.clear()
    written = _contribute(db_session, chapter, copycat, list(GOOD), scorer=scorer)

    assert scorer.calls == []  # settled by the hash alone
    assert written.contributed_by_user_id == incumbent.id
    assert written.text_hash == gate.compute_text_hash(GOOD)


def test_near_identical_submission_is_a_no_op_without_scoring(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, challenger = _make_user(db_session), _make_user(db_session)
    scorer = _scorer({})
    # One character of difference across a whole page: not new information.
    nearly = [GOOD[0], GOOD[1].replace("choice.", "choice!")]

    _contribute(db_session, chapter, incumbent, GOOD, scorer=scorer)
    scorer.calls.clear()
    written = _contribute(db_session, chapter, challenger, nearly, scorer=scorer)

    assert scorer.calls == []
    assert written.translated_boxes == GOOD
    assert written.contributed_by_user_id == incumbent.id


def test_rule_based_garbage_is_rejected_without_scoring(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, flooder = _make_user(db_session), _make_user(db_session)
    scorer = _scorer({})

    _contribute(db_session, chapter, incumbent, GOOD, scorer=scorer)
    scorer.calls.clear()
    # Empty output would erase text we already have; Cyrillic cannot be an
    # English translation; two characters cannot render this source page.
    for boxes in ([""], ["Привет как дела мой друг сегодня"], ["ok"]):
        written = _contribute(db_session, chapter, flooder, boxes, scorer=scorer)
        assert written.translated_boxes == GOOD, boxes

    assert scorer.calls == []


@pytest.mark.parametrize(
    "new_text, expected",
    [
        ("", "empty_text"),
        ("Привет как дела мой друг сегодня вечером", "script_mismatch"),
        ("hi", "length_ratio"),
        ("x" * 5000, "length_ratio"),
        ("A perfectly ordinary English rendering of the line.", None),
    ],
)
def test_garbage_rules(new_text, expected) -> None:
    assert (
        gate.garbage_reason(
            new_text,
            source_text=gate.normalize_text(SOURCE),
            incumbent_text=gate.normalize_text(GOOD),
            expected_language="en",
        )
        == expected
    )


def test_empty_first_entry_is_not_garbage() -> None:
    """A page with no text is a legitimate cache entry; only erasing text
    we already have counts as garbage."""

    assert gate.garbage_reason("", source_text="", incumbent_text="") is None


def test_hash_ignores_whitespace_and_empty_boxes() -> None:
    assert gate.compute_text_hash(
        ["Hello  world", "", "Bye"]
    ) == gate.compute_text_hash(["Hello world ", "Bye"])
    assert gate.compute_text_hash(["Hello"]) != gate.compute_text_hash(["Hallo"])


# --- tier stays a pre-filter ----------------------------------------------


def test_higher_tier_skips_scoring_but_still_fails_the_garbage_rules(
    db_session,
) -> None:
    chapter = _make_chapter(db_session)
    user = _make_user(db_session)
    scorer = _scorer({})

    cache_service.put_translation_cache(
        db_session,
        chapter.id,
        0,
        "en",
        GOOD,
        quality_tier="free",
        source_boxes=SOURCE,
        quality_scorer=scorer,
    )
    paid_garbage = cache_service.put_translation_cache(
        db_session,
        chapter.id,
        0,
        "en",
        [""],
        quality_tier="paid",
        source_boxes=SOURCE,
        quality_scorer=scorer,
    )
    assert paid_garbage.translated_boxes == GOOD
    assert scorer.calls == []

    paid_good = cache_service.put_translation_cache(
        db_session,
        chapter.id,
        0,
        "en",
        BETTER,
        quality_tier="paid",
        source_boxes=SOURCE,
        quality_scorer=scorer,
    )
    assert paid_good.translated_boxes == BETTER
    assert scorer.calls == []  # a strictly higher tier never pays for a call
    assert user.id  # (user fixture kept for symmetry with the other cases)


def test_platform_default_refresh_still_replaces_a_stale_entry(db_session) -> None:
    """2C.4.3 "refresh cache" demotes everything to free so fresh output can
    replace it. A trusted platform write must still get through when no
    scoring provider is configured -- only untrusted writes are held back.
    """

    chapter = _make_chapter(db_session)

    cache_service.put_translation_cache(
        db_session, chapter.id, 0, "en", GOOD, quality_tier="free", source_boxes=SOURCE
    )
    refreshed = cache_service.put_translation_cache(
        db_session,
        chapter.id,
        0,
        "en",
        BETTER,
        quality_tier="free",
        source_boxes=SOURCE,
        contributed_by_sharing=False,
    )
    assert refreshed.translated_boxes == BETTER


# --- Pill minting is downstream of the gate -------------------------------


def _process(db, chapter, user, texts, *, priority_off=True):
    from backend_fastapi.app.services import cache_admin_service

    class Translator:
        def translate(self, text, source_lang, target_lang, provider_config=None, **_):
            out = []
            for i, line in enumerate(text.splitlines()):
                number, _, _rest = line.partition("] ")
                out.append(f"{number}] {texts[i]}")
            return "\n".join(out)

    def ocr(_image_bytes, _hint):
        return {
            "regions": [
                {
                    "index": i,
                    "text": source,
                    "coordinates": {
                        "x": 10.0 + i * 50,
                        "y": 10.0,
                        "width": 40.0,
                        "height": 20.0,
                    },
                    "confidence": 95.0,
                    "region_type": "speech_bubble",
                    "reading_order": i,
                }
                for i, source in enumerate(SOURCE)
            ],
            "detected_language": "ja",
            "detected_script": "cjk",
            "reading_order_mode": "rtl_vertical",
            "engine_tier": 2,
        }

    processing_settings_service.update(db, user.id, {"share_translations": True})
    if priority_off:
        # Otherwise the reader is served the cached entry and never
        # produces a competing submission at all.
        cache_admin_service.set_cache_priority(db, "off")
    try:
        return cps.process_page(
            db=db,
            chapter=chapter,
            page_index=0,
            target_lang="en",
            user_id=user.id,
            plan=resolve_plan(
                has_user_ocr=True, has_user_translation=True, has_user_ai=False
            ),
            processing_settings=processing_settings_service.get_or_create(db, user.id),
            fetch_image_bytes=lambda _url: b"fake-image-bytes",
            ocr_runner=ocr,
            translation_service=Translator(),
            translation_provider_config={
                "provider": "custom",
                "api_url": "https://example.com",
            },
            ai_provider_config=None,
        )
    finally:
        cache_admin_service.set_cache_priority(db, "on")


def _pill(db, user, chapter):
    return (
        db.query(Pill)
        .filter(Pill.user_id == user.id, Pill.chapter_id == chapter.id)
        .one_or_none()
    )


def test_flooder_gets_no_pill_when_the_gate_rejects_the_write(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, flooder = _make_user(db_session), _make_user(db_session)

    _process(db_session, chapter, incumbent, GOOD)
    assert _pill(db_session, incumbent, chapter) is not None

    _process(db_session, chapter, flooder, GARBAGE)

    row = (
        db_session.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter.id, TranslationCache.page_index == 0
        )
        .one()
    )
    assert row.translated_boxes == GOOD
    assert row.contributed_by_user_id == incumbent.id
    assert _pill(db_session, flooder, chapter) is None


def test_exact_duplicate_contribution_mints_no_pill_for_the_copier(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, copycat = _make_user(db_session), _make_user(db_session)

    _process(db_session, chapter, incumbent, GOOD)
    _process(db_session, chapter, copycat, GOOD)

    assert _pill(db_session, copycat, chapter) is None
    assert _pill(db_session, incumbent, chapter) is not None


def test_better_contribution_takes_over_the_entry_and_mints_a_pill(db_session) -> None:
    chapter = _make_chapter(db_session)
    incumbent, improver = _make_user(db_session), _make_user(db_session)

    scores = {gate.normalize_text(GOOD): 55.0, gate.normalize_text(BETTER): 93.0}

    def fake_score(candidate_text, **_):
        return scores.get(candidate_text)

    _process(db_session, chapter, incumbent, GOOD)

    from unittest.mock import patch

    with patch(
        "backend_fastapi.app.services.submission_quality_gate.score_text",
        side_effect=fake_score,
    ):
        _process(db_session, chapter, improver, BETTER)

    row = (
        db_session.query(TranslationCache)
        .filter(
            TranslationCache.chapter_id == chapter.id, TranslationCache.page_index == 0
        )
        .one()
    )
    assert row.translated_boxes == BETTER
    assert row.contributed_by_user_id == improver.id
    assert row.quality_score == 93.0
    assert _pill(db_session, improver, chapter) is not None


# --- the scoring provider call itself --------------------------------------


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_score_text_parses_an_openai_style_completion() -> None:
    posted = {}

    def http_post(url, json=None, headers=None, timeout=None):
        posted["url"] = url
        posted["json"] = json
        return _Response({"choices": [{"message": {"content": "  87 "}}]})

    score = gate.score_text(
        "candidate",
        source_text="source",
        provider_config={"provider": "openai", "api_url": "https://api.example/v1"},
        http_post=http_post,
    )
    assert score == 87.0
    assert posted["url"] == "https://api.example/v1"
    assert "candidate" in posted["json"]["messages"][0]["content"]


def test_score_text_parses_a_gemini_style_completion() -> None:
    def http_post(url, json=None, headers=None, timeout=None):
        return _Response({"candidates": [{"content": {"parts": [{"text": "12"}]}}]})

    assert (
        gate.score_text(
            "candidate",
            provider_config={
                "provider": "google_gemini",
                "api_url": "https://gemini.example",
            },
            http_post=http_post,
        )
        == 12.0
    )


def test_score_text_returns_none_rather_than_guessing() -> None:
    def exploding_post(*_a, **_kw):
        raise RuntimeError("provider down")

    assert gate.score_text("candidate", provider_config=None) is None
    assert (
        gate.score_text("candidate", provider_config={"provider": "unsupported_thing"})
        is None
    )
    assert (
        gate.score_text(
            "candidate",
            provider_config={"provider": "openai", "api_url": "https://x.example"},
            http_post=exploding_post,
        )
        is None
    )
