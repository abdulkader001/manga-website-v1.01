"""Whole-chapter translation context (SRS 2C.1)."""

from __future__ import annotations

from backend_fastapi.app.services import chapter_translation_service as cts


class WholeChapterTranslator:
    """Simulates a chat-completion-style provider that honours the
    numbered-line contract and receives exactly one call per chapter."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def translate(self, text, source_lang, target_lang, provider_config=None, **_):
        self.calls.append({"text": text, "provider_config": provider_config})
        translated_lines = []
        for line in text.splitlines():
            n, _, rest = line.partition("] ")
            n = n.lstrip("[")
            translated_lines.append(f"[{n}] TRANSLATED:{rest}")
        return "\n".join(translated_lines)


class PerCallOnlyTranslator:
    """Simulates a plain single-string MT endpoint that has no concept of
    the numbered-line contract and just translates whatever blob it gets."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def translate(self, text, source_lang, target_lang, provider_config=None, **_):
        self.calls.append(text)
        return f"garbled::{text}"


def test_whole_chapter_sent_as_a_single_request() -> None:
    service = WholeChapterTranslator()
    texts = ["Hello", "How are you?", "I'm fine"]

    result = cts.translate_chapter_texts(
        texts,
        translation_service=service,
        provider_config={"provider": "openai_gpt_3_5"},
        source_lang="ja",
        target_lang="en",
        series_title="Test Series",
        genres=["action", "drama"],
        glossary={"Naruto": "Naruto-kun"},
    )

    assert len(service.calls) == 1  # one request for the whole chapter
    assert result == [
        "TRANSLATED:Hello",
        "TRANSLATED:How are you?",
        "TRANSLATED:I'm fine",
    ]
    prompt = service.calls[0]["provider_config"]["prompt"]
    assert "Test Series" in prompt
    assert "action, drama" in prompt
    assert "Naruto -> Naruto-kun" in prompt


def test_reading_order_is_preserved_through_the_round_trip() -> None:
    service = WholeChapterTranslator()
    texts = [f"line-{i}" for i in range(12)]
    result = cts.translate_chapter_texts(
        texts,
        translation_service=service,
        provider_config={},
        source_lang="ja",
        target_lang="en",
    )
    for i, translated in enumerate(result):
        assert translated == f"TRANSLATED:line-{i}"


def test_empty_regions_are_skipped_but_positions_preserved() -> None:
    service = WholeChapterTranslator()
    texts = ["Hello", "", "World"]
    result = cts.translate_chapter_texts(
        texts,
        translation_service=service,
        provider_config={},
        source_lang="ja",
        target_lang="en",
    )
    assert result[1] == ""
    assert result[0] == "TRANSLATED:Hello"
    assert result[2] == "TRANSLATED:World"


def test_falls_back_to_per_region_when_provider_ignores_numbering() -> None:
    service = PerCallOnlyTranslator()
    texts = ["Hello", "World"]
    result = cts.translate_chapter_texts(
        texts,
        translation_service=service,
        provider_config={},
        source_lang="ja",
        target_lang="en",
    )
    # First call was the whole-chapter attempt; then one call per region.
    assert len(service.calls) == 3
    assert result == ["garbled::Hello", "garbled::World"]


def test_context_lines_included_but_not_translated() -> None:
    service = WholeChapterTranslator()
    texts = ["New line"]
    cts.translate_chapter_texts(
        texts,
        translation_service=service,
        provider_config={},
        source_lang="ja",
        target_lang="en",
        context_lines=["Earlier dialogue", "More context"],
    )
    prompt = service.calls[0]["provider_config"]["prompt"]
    assert "Earlier dialogue" in prompt
    assert "More context" in prompt
    assert "do not re-translate" in prompt


def test_no_translation_service_returns_originals() -> None:
    texts = ["Hello", "World"]
    result = cts.translate_chapter_texts(
        texts,
        translation_service=None,
        provider_config={},
        source_lang="ja",
        target_lang="en",
    )
    assert result == texts
