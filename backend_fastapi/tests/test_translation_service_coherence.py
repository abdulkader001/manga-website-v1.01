"""Stage B, the coherence pass (SRS 2C.1, closing F-12).

The headline regression these cover: whole-chapter context -- above all the
series glossary -- must reach the provider that actually applies it, no
matter what produced the literal draft. Before this, context was attached as
``provider_config["prompt"]`` and only ``_translate_via_chat_completion``
ever looked at it; the plain ``q=``/``translate`` branch had nowhere to put
it and dropped it silently, so the platform's own default translator
(LibreTranslate) ignored the glossary entirely.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import requests

from backend_fastapi.app.services import chapter_translation_service as cts
from backend_fastapi.app.services.translation_service import (
    COHERENCE_SYSTEM_PROMPT,
    TranslationService,
    build_coherence_payload,
)

COHERENCE_URL = "https://coherence.example/v1/chat/completions"
CHAT_DRAFT_URL = "https://draft-chat.example/v1/chat/completions"
REST_DRAFT_URL = "https://libretranslate.example/translate"

GLOSSARY = {"シスイ": "Shisui"}

# Both draft providers render the glossary term inconsistently -- which is
# exactly the failure whole-chapter context is supposed to fix.
DRAFTS = {
    "シスイは戻った": "Shishui returned",
    "シスイ、待って": "Shisu-san, wait",
    "": "",
}
BAD_RENDERINGS = ("Shishui", "Shisu-san")

SOURCES = ["シスイは戻った", "シスイ、待って"]

CHAT_DRAFT_CONFIG = {
    "provider": "openai_gpt_3_5",
    "api_url": CHAT_DRAFT_URL,
    "model": "gpt-4o-mini",
}
REST_DRAFT_CONFIG = {
    "provider": "libretranslate_demo",
    "api_url": REST_DRAFT_URL,
}
COHERENCE_CONFIG = {
    "provider": "openai_gpt_3_5",
    "api_url": COHERENCE_URL,
    "model": "gpt-4o-mini",
}


class DummyResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.RequestException(f"HTTP {self.status_code}")


def _chat_reply(content: str) -> DummyResponse:
    return DummyResponse({"choices": [{"message": {"content": content}}]})


class FakeProviders:
    """One fake HTTP surface standing in for all three provider roles.

    The coherence endpoint enforces the glossary *from the payload it was
    given*: if the glossary never reached it, it has no canonical spelling to
    substitute and leaves the bad draft alone -- so these tests fail loudly if
    the context stops being threaded, rather than passing vacuously.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        if url == COHERENCE_URL:
            return self._coherence(json)
        if url == CHAT_DRAFT_URL:
            return self._chat_draft(json)
        if url == REST_DRAFT_URL:
            return self._rest_draft(json)
        raise AssertionError(f"unexpected provider call to {url}")

    @property
    def coherence_payloads(self) -> list[dict]:
        return [
            json.loads(body["messages"][1]["content"])
            for url, body in self.calls
            if url == COHERENCE_URL
        ]

    def _coherence(self, body):
        graph = json.loads(body["messages"][1]["content"])
        glossary = graph.get("glossary") or {}
        canonical = glossary.get("シスイ")
        regions = []
        for region in graph["regions"]:
            text = region["literal_translation"]
            if canonical:
                for bad in BAD_RENDERINGS:
                    text = text.replace(bad, canonical)
            regions.append({"index": region["index"], "translation": text})
        return _chat_reply(json.dumps({"regions": regions}))

    def _chat_draft(self, body):
        blob = body["messages"][1]["content"]
        lines = []
        for line in blob.splitlines():
            number, _, source = line.partition("] ")
            lines.append(f"{number}] {DRAFTS[source]}")
        return _chat_reply("\n".join(lines))

    def _rest_draft(self, body):
        text = body["q"]
        if text in DRAFTS:  # a per-region call
            return DummyResponse({"translatedText": DRAFTS[text]})
        # A numbered blob: a real LibreTranslate has no concept of the
        # numbered-line contract, so it returns one undifferentiated string
        # and Stage A falls back to per-region calls.
        return DummyResponse({"translatedText": "MT[" + text.replace("\n", " ") + "]"})


@pytest.fixture
def providers(monkeypatch) -> FakeProviders:
    fake = FakeProviders()
    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=fake.post, RequestException=requests.RequestException),
    )
    return fake


def _service() -> TranslationService:
    return TranslationService(default_api_url=None, default_api_key=None)


def _translate(service, draft_config, providers=None, **overrides):
    kwargs = dict(
        translation_service=service,
        provider_config=draft_config,
        source_lang="ja",
        target_lang="en",
        glossary=GLOSSARY,
        regions=[
            {"index": 0, "reading_order": 0, "region_type": "speech_bubble"},
            {"index": 1, "reading_order": 1, "region_type": "thought"},
        ],
        coherence_provider_config=COHERENCE_CONFIG,
        previous_page_last_lines=["Shisui vanished."],
        chapter_summary="Series: Test Series. Genre: action.",
    )
    kwargs.update(overrides)
    return cts.translate_chapter_texts(list(SOURCES), **kwargs)


# --- the headline regression ----------------------------------------------


@pytest.mark.parametrize(
    "draft_config, label",
    [(CHAT_DRAFT_CONFIG, "chat"), (REST_DRAFT_CONFIG, "non-chat")],
)
def test_glossary_is_applied_in_stage_b_for_either_draft_provider(
    providers, draft_config, label
) -> None:
    result = _translate(_service(), draft_config)

    assert result == ["Shisui returned", "Shisui, wait"], label
    assert not any(bad in " ".join(result) for bad in BAD_RENDERINGS), label

    # Stage B ran, once, against the chat provider it was given -- not
    # against whatever produced the draft.
    payloads = providers.coherence_payloads
    assert len(payloads) == 1
    assert payloads[0]["glossary"] == GLOSSARY


def test_stage_b_output_is_identical_across_draft_provider_kinds(providers) -> None:
    via_chat = _translate(_service(), CHAT_DRAFT_CONFIG)
    via_rest = _translate(_service(), REST_DRAFT_CONFIG)
    assert via_chat == via_rest


def test_non_chat_draft_provider_never_receives_the_context(providers) -> None:
    """The plain-MT endpoint has no field for a prompt; F-12 was pretending
    otherwise. It should only ever be asked for a literal string."""

    _translate(_service(), REST_DRAFT_CONFIG)

    rest_bodies = [body for url, body in providers.calls if url == REST_DRAFT_URL]
    assert rest_bodies
    for body in rest_bodies:
        assert set(body) <= {"q", "source", "target", "format", "model"}


# --- the graph prompt ------------------------------------------------------


def test_graph_prompt_carries_region_metadata_and_context(providers) -> None:
    _translate(_service(), REST_DRAFT_CONFIG)
    graph = providers.coherence_payloads[0]

    assert graph["target_language"] == "en"
    assert graph["context"]["previous_page_last_lines"] == ["Shisui vanished."]
    assert graph["context"]["chapter_summary"].startswith("Series: Test Series")
    assert [r["index"] for r in graph["regions"]] == [0, 1]
    assert [r["reading_order"] for r in graph["regions"]] == [0, 1]
    assert [r["region_type"] for r in graph["regions"]] == ["speech_bubble", "thought"]
    assert graph["regions"][0]["source_text"] == SOURCES[0]
    assert graph["regions"][0]["literal_translation"] == DRAFTS[SOURCES[0]]

    system_prompt = [
        body["messages"][0]["content"]
        for url, body in providers.calls
        if url == COHERENCE_URL
    ][0]
    assert system_prompt == COHERENCE_SYSTEM_PROMPT


def test_build_coherence_payload_drops_blank_context_lines() -> None:
    payload = build_coherence_payload(
        target_lang="en",
        regions=[],
        previous_page_last_lines=["a", "   ", ""],
    )
    assert payload["context"]["previous_page_last_lines"] == ["a"]
    assert payload["glossary"] == {}
    assert payload["context"]["chapter_summary"] == ""


# --- Pipeline 1 draft reuse ------------------------------------------------


def test_client_side_drafts_are_reused_instead_of_retranslating(providers) -> None:
    result = _translate(
        _service(),
        REST_DRAFT_CONFIG,
        draft_translations=["Shishui returned", "Shisu-san, wait"],
    )

    # No Stage A call at all -- Pipeline 1 already paid for those.
    assert not [url for url, _ in providers.calls if url == REST_DRAFT_URL]
    # ...and Stage B still gets to fix the glossary in them.
    assert result == ["Shisui returned", "Shisui, wait"]


def test_partial_client_drafts_only_translate_the_gaps(providers) -> None:
    _translate(
        _service(),
        REST_DRAFT_CONFIG,
        draft_translations=["Shishui returned", "   "],
    )

    # Only the gap is sent (once as the numbered blob, then again per-region
    # because this provider ignores the numbering); the region Pipeline 1
    # already covered is never re-translated.
    sent = [body["q"] for url, body in providers.calls if url == REST_DRAFT_URL]
    assert sent == [f"[1] {SOURCES[1]}", SOURCES[1]]


# --- Stage B stays safe when it cannot run ---------------------------------


def test_no_chat_capable_provider_keeps_the_literal_drafts(providers) -> None:
    outcome: dict = {}
    result = cts.translate_chapter_texts(
        list(SOURCES),
        translation_service=_service(),
        provider_config=REST_DRAFT_CONFIG,
        source_lang="ja",
        target_lang="en",
        glossary=GLOSSARY,
        coherence_provider_config=None,
        coherence_outcome=outcome,
    )

    assert result == [DRAFTS[SOURCES[0]], DRAFTS[SOURCES[1]]]
    assert outcome == {"applied": False, "reason": "no_chat_provider", "provider": None}
    assert not [url for url, _ in providers.calls if url == COHERENCE_URL]


@pytest.mark.parametrize(
    "content",
    [
        "sure! here you go",  # not JSON at all
        '{"regions": [{"index": 0, "translation": "only one"}]}',  # dropped a region
        '{"regions": [{"index": 0, "translation": "a"}, {"index": 0, '
        '"translation": "b"}]}',  # answered one region twice
        '{"regions": [{"index": 0, "translation": "a"}, {"index": 1, '
        '"translation": "b"}, {"index": 2, "translation": "c"}]}',  # invented one
        '{"regions": [{"index": 0, "translation": "a b"}]}',  # merged
    ],
)
def test_contract_violations_fall_back_to_the_literal_drafts(
    monkeypatch, content
) -> None:
    def post(url, json=None, headers=None, timeout=None):
        if url == COHERENCE_URL:
            return _chat_reply(content)
        return DummyResponse({"translatedText": DRAFTS.get(json["q"], "MT")})

    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=post, RequestException=requests.RequestException),
    )

    outcome: dict = {}
    result = _translate(_service(), REST_DRAFT_CONFIG, coherence_outcome=outcome)

    assert result == [DRAFTS[SOURCES[0]], DRAFTS[SOURCES[1]]]
    assert outcome["applied"] is False
    assert outcome["reason"] == "contract_violated"


def test_provider_failure_falls_back_to_the_literal_drafts(monkeypatch) -> None:
    def post(url, json=None, headers=None, timeout=None):
        if url == COHERENCE_URL:
            raise requests.RequestException("upstream down")
        return DummyResponse({"translatedText": DRAFTS.get(json["q"], "MT")})

    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=post, RequestException=requests.RequestException),
    )

    outcome: dict = {}
    result = _translate(_service(), REST_DRAFT_CONFIG, coherence_outcome=outcome)
    assert result == [DRAFTS[SOURCES[0]], DRAFTS[SOURCES[1]]]
    assert outcome["reason"] == "provider_error"


def test_blank_stage_b_output_never_erases_a_region(monkeypatch) -> None:
    def post(url, json=None, headers=None, timeout=None):
        if url == COHERENCE_URL:
            return _chat_reply(
                '{"regions": [{"index": 0, "translation": ""}, '
                '{"index": 1, "translation": "Shisui, wait"}]}'
            )
        return DummyResponse({"translatedText": DRAFTS.get(json["q"], "MT")})

    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=post, RequestException=requests.RequestException),
    )

    result = _translate(_service(), REST_DRAFT_CONFIG)
    assert result == [DRAFTS[SOURCES[0]], "Shisui, wait"]


def test_empty_regions_stay_empty_and_are_not_sent_to_stage_b(providers) -> None:
    result = cts.translate_chapter_texts(
        [SOURCES[0], "", SOURCES[1]],
        translation_service=_service(),
        provider_config=REST_DRAFT_CONFIG,
        source_lang="ja",
        target_lang="en",
        glossary=GLOSSARY,
        coherence_provider_config=COHERENCE_CONFIG,
    )

    assert result == ["Shisui returned", "", "Shisui, wait"]
    graph = providers.coherence_payloads[0]
    assert [r["index"] for r in graph["regions"]] == [0, 2]


def test_gemini_coherence_uses_generate_content_shape(monkeypatch) -> None:
    seen: list[dict] = []

    def post(url, json=None, headers=None, timeout=None):
        if "generatecontent" in url.lower():
            seen.append(json)
            return DummyResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": '{"regions": [{"index": 0, '
                                        '"translation": "Shisui returned"}, '
                                        '{"index": 1, "translation": '
                                        '"Shisui, wait"}]}'
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        return DummyResponse({"translatedText": DRAFTS.get(json["q"], "MT")})

    monkeypatch.setattr(
        "backend_fastapi.app.services.translation_service.requests",
        SimpleNamespace(post=post, RequestException=requests.RequestException),
    )

    result = _translate(
        _service(),
        REST_DRAFT_CONFIG,
        coherence_provider_config={
            "provider": "google_gemini",
            "api_url": "https://gemini.example/v1/models/x:generateContent",
        },
    )

    assert result == ["Shisui returned", "Shisui, wait"]
    # Gemini takes no system role and no model in the body; the model lives
    # in the URL. Sending the OpenAI shape here would 400.
    assert list(seen[0]) == ["contents"]
    assert COHERENCE_SYSTEM_PROMPT in seen[0]["contents"][0]["parts"][0]["text"]
