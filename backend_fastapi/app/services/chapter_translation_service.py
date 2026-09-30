"""Whole-chapter translation context (SRS 2C.1), in two stages.

"Translating each speech bubble in isolation produces noticeably worse
output than translating a chapter as a unit. This is the single largest
quality lever available that costs nothing."

Stage A produces a literal draft for every region. Whichever provider the
caller resolved does it -- chat-completion or a plain single-string MT REST
endpoint, the system default or the user's own key -- and when Pipeline 1
already translated the page client-side, its output is reused as the draft
instead of paying for a second server-side translation. Stage A still sends
the page as one numbered-line request when it can, because that costs
nothing and helps providers that do honour it, and still falls back to
per-region calls when a provider ignores the numbering, so no text is ever
lost.

Stage B is the coherence pass, and it is where the context actually lands.
It hands the glossary, region types, the previous page's closing lines and
a chapter summary to a **chat-completion-capable provider chosen
independently of Stage A** (``TranslationService.coherence_pass``). That
independence is the point: F-12 was whole-chapter context being built and
then silently discarded by ``_perform_translation``'s plain-MT branch,
which has no field to put a prompt in. With Stage B routed by capability
rather than by whatever produced the draft, a non-chat provider can still
do the literal work but is never the thing asked to apply context.

Stage B's output -- not Stage A's -- is what the caller writes to the
shared cache.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

logger_name = "backend_fastapi.chapter_translation"

_LINE_PATTERN = re.compile(r"^\s*\[(\d+)\]\s?(.*)$")


def _build_context_prompt(
    *,
    source_lang: str,
    target_lang: str,
    series_title: Optional[str],
    genres: Optional[List[str]],
    glossary: Optional[Dict[str, str]],
    context_lines: Optional[List[str]] = None,
) -> str:
    parts = [
        f"You are translating a manga chapter from {source_lang} to {target_lang}."
    ]
    if series_title:
        parts.append(f"Series: {series_title}.")
    if genres:
        parts.append(f"Genre: {', '.join(genres)}.")
    if glossary:
        pairs = "; ".join(f"{src} -> {dst}" for src, dst in glossary.items())
        parts.append(f"Use these established name translations consistently: {pairs}.")
    if context_lines:
        joined = " / ".join(line for line in context_lines if line.strip())
        if joined:
            parts.append(
                f"For context only (already covered, do not re-translate this "
                f"part): earlier dialogue in this chapter reads: {joined}"
            )
    parts.append(
        "The lines below are numbered text regions from the chapter, given in "
        "reading order so pronouns, honorifics and gendered forms can be "
        "resolved from the surrounding dialogue. Translate every line. "
        "Return exactly one output line per input line, in the same order, "
        "each prefixed with its original [N] number, and nothing else -- no "
        "commentary, no extra lines."
    )
    return " ".join(parts)


def _join_regions(texts: List[str]) -> str:
    return "\n".join(f"[{i + 1}] {text}" for i, text in enumerate(texts))


def _split_translated(blob: str, expected_count: int) -> Optional[List[str]]:
    if not isinstance(blob, str):
        return None
    parsed: Dict[int, str] = {}
    for line in blob.splitlines():
        match = _LINE_PATTERN.match(line)
        if not match:
            continue
        parsed[int(match.group(1))] = match.group(2).strip()
    if len(parsed) != expected_count:
        return None
    try:
        return [parsed[i + 1] for i in range(expected_count)]
    except KeyError:
        return None


def _usable_draft(draft_translations: Optional[Sequence[Any]], index: int) -> str:
    """Pipeline 1's client-side output for one region, or "" if unusable."""

    if not draft_translations or index >= len(draft_translations):
        return ""
    value = draft_translations[index]
    if isinstance(value, str) and value.strip():
        return value
    return ""


def _stage_a_literal_drafts(
    texts: List[str],
    *,
    translation_service: Any,
    provider_config: Optional[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
    prompt: str,
    draft_translations: Optional[Sequence[Any]],
) -> List[str]:
    """A literal translation for every non-empty region, by any provider."""

    results: List[str] = ["" for _ in texts]
    pending: List[int] = []
    for index, text in enumerate(texts):
        if not (text or "").strip():
            continue
        reused = _usable_draft(draft_translations, index)
        if reused:
            # Pipeline 1 already paid for this region client-side; Stage B
            # still gets to rewrite it, so reusing costs no quality.
            results[index] = reused
        else:
            pending.append(index)

    if not pending:
        return results

    blob = _join_regions([texts[i] for i in pending])
    cfg: Dict[str, Any] = dict(provider_config or {})
    cfg.setdefault("prompt", prompt)

    translated_blob = translation_service.translate(
        blob, source_lang=source_lang, target_lang=target_lang, provider_config=cfg
    )
    split = _split_translated(translated_blob, len(pending))

    if split is not None:
        for position, region_index in enumerate(pending):
            results[region_index] = split[position]
        return results

    # The provider didn't honour the numbered-line contract (typical of a
    # plain q=/translate REST endpoint). Fall back to per-region calls so no
    # text is lost -- Stage B, not this blob, is what carries the context.
    for region_index in pending:
        results[region_index] = translation_service.translate(
            texts[region_index],
            source_lang=source_lang,
            target_lang=target_lang,
            provider_config=provider_config,
        )
    return results


def _stage_b_coherence_pass(
    texts: List[str],
    drafts: List[str],
    *,
    translation_service: Any,
    regions: Optional[Sequence[Dict[str, Any]]],
    target_lang: str,
    glossary: Optional[Dict[str, str]],
    previous_page_last_lines: Optional[Sequence[str]],
    chapter_summary: Optional[str],
    provider_config: Optional[Dict[str, Any]],
    coherence_provider_config: Optional[Dict[str, Any]],
    outcome: Optional[Dict[str, Any]],
) -> List[str]:
    """Rewrite ``drafts`` as one coherent page, or return them unchanged."""

    coherence = getattr(translation_service, "coherence_pass", None)
    if not callable(coherence):
        # A caller passing a bare translate()-only adapter still works; it
        # just gets Stage A's output.
        if outcome is not None:
            outcome.setdefault("applied", False)
            outcome.setdefault("reason", "no_coherence_capable_service")
        return drafts

    region_by_index = {}
    for region in regions or []:
        if isinstance(region, dict) and isinstance(region.get("index"), int):
            region_by_index[region["index"]] = region

    payload_regions: List[Dict[str, Any]] = []
    for index, source in enumerate(texts):
        meta = region_by_index.get(index, {})
        payload_regions.append(
            {
                "index": index,
                "reading_order": meta.get("reading_order", index),
                "region_type": meta.get("region_type"),
                "source_text": source or "",
                "literal_translation": drafts[index],
            }
        )

    refined = coherence(
        payload_regions,
        target_lang=target_lang,
        glossary=glossary,
        previous_page_last_lines=previous_page_last_lines,
        chapter_summary=chapter_summary,
        provider_config=provider_config,
        coherence_provider_config=coherence_provider_config,
        outcome=outcome,
    )
    if refined is None or len(refined) != len(drafts):
        return drafts
    return list(refined)


def translate_chapter_texts(
    texts: List[str],
    *,
    translation_service: Any,
    provider_config: Optional[Dict[str, Any]],
    source_lang: str,
    target_lang: str,
    series_title: Optional[str] = None,
    genres: Optional[List[str]] = None,
    glossary: Optional[Dict[str, str]] = None,
    context_lines: Optional[List[str]] = None,
    regions: Optional[Sequence[Dict[str, Any]]] = None,
    draft_translations: Optional[Sequence[Any]] = None,
    coherence_provider_config: Optional[Dict[str, Any]] = None,
    previous_page_last_lines: Optional[Sequence[str]] = None,
    chapter_summary: Optional[str] = None,
    coherence_outcome: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Translate every entry in ``texts`` (already in reading order) as one
    page-sized unit, in two stages. Returns a list the same length as
    ``texts``.

    ``regions`` are the normalized OCR regions the texts came from, used for
    ``region_type``/``reading_order`` in Stage B's graph prompt.
    ``draft_translations`` is Pipeline 1's client-side output, reused as the
    literal draft where present. ``coherence_provider_config`` is a
    chat-completion-capable provider offered to Stage B; it does not have to
    be -- and usually isn't -- the provider Stage A used.

    ``context_lines`` are already-known chapter text (e.g. from sibling
    pages already OCR'd/translated) supplied purely for pronoun/honorific
    resolution -- they are not translated or echoed back.
    """

    if not texts:
        return []
    if translation_service is None:
        return list(texts)

    if not any((t or "").strip() for t in texts):
        return ["" for _ in texts]

    prompt = _build_context_prompt(
        source_lang=source_lang,
        target_lang=target_lang,
        series_title=series_title,
        genres=genres,
        glossary=glossary,
        context_lines=context_lines,
    )

    drafts = _stage_a_literal_drafts(
        texts,
        translation_service=translation_service,
        provider_config=provider_config,
        source_lang=source_lang,
        target_lang=target_lang,
        prompt=prompt,
        draft_translations=draft_translations,
    )

    return _stage_b_coherence_pass(
        texts,
        drafts,
        translation_service=translation_service,
        regions=regions,
        target_lang=target_lang,
        glossary=glossary,
        previous_page_last_lines=previous_page_last_lines,
        chapter_summary=chapter_summary,
        provider_config=provider_config,
        coherence_provider_config=coherence_provider_config,
        outcome=coherence_outcome,
    )


__all__ = ["translate_chapter_texts"]
