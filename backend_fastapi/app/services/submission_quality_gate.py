"""Content-based write authority for the shared OCR/translation cache.

``quality_tier`` (free/paid, derived from ``ENGINE_TIER_BY_PROVIDER``) only
ever described *which provider* produced a result, never *what the result
says*. Since every untrusted engine -- ``tesseract_local``, ``custom``,
``ocr_space_free``, ``system`` -- collapses into the same "free" bucket, the
old ">= tier always wins" rule let any free-tier submission overwrite any
other free-tier submission already in the shared cache with zero comparison
of the text itself, and ``pill_service.mint_if_new`` then rewarded whoever
happened to land last. This module is the missing half: it looks at the
submitted text and decides whether the write is actually an improvement.

The ladder is ordered cheapest-first so the overwhelming majority of
submissions are settled without any network call:

  (a) exact hash match         -> no-op (no write, no Pill)
  (b) near-identical text      -> no-op          } no AI call
      rule-based garbage       -> reject         }
  (c) genuinely different and  -> score old vs new with a cheap configured
      not obviously garbage       chat-completion provider; write only if
                                  the new score is strictly better

Step (c) is the only step that costs anything, and it is reached only by
submissions that survived (a) and (b). When no scoring provider is
configured the fallback depends on ``trusted``: a platform-default write
(the site's own pipeline, e.g. regenerating after 2C.4.3 "refresh cache")
is allowed through on the cheap checks alone, while an untrusted write --
a user-supplied provider whose result can earn a Pill, which is exactly
the flood/reward-farming path -- is rejected, because nothing proved it
was better than what is already cached.

``quality_tier``/``engine_tier`` are untouched and still shown for display
and backward compatibility; they remain a pre-filter (a strictly lower tier
still loses outright, a strictly higher tier still skips the scoring step),
but they are no longer the write authority.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

import requests

from . import script_registry

ACCEPT = "accept"
REJECT = "reject"
NOOP = "noop"

# Two submissions this similar say the same thing; rewriting the row (and
# reassigning its Pill ownership) would be churn, not an improvement.
NEAR_DUPLICATE_SIMILARITY = 0.97

# Below this many characters, SequenceMatcher is cheap and exact; above it
# we fall back to token overlap so the check stays O(n) on huge pages.
SEQUENCE_MATCHER_MAX_CHARS = 2000

# "Drastically different length than the source". Deliberately wide: a CJK
# source legitimately expands several-fold when translated into a Latin
# language, so only the truly implausible is rejected here.
MIN_LENGTH_RATIO = 0.15
MAX_LENGTH_RATIO = 8.0

# Length ratios on a handful of characters are noise, not signal.
MIN_LENGTH_CHECK_CHARS = 8

# 0-100 fidelity/coherence score from the scoring provider.
MIN_SCORE = 0.0
MAX_SCORE = 100.0

SCORING_CAPABLE_PROVIDERS = {
    "google_gemini",
    "openai_gpt_3_5",
    "openai",
    "custom",
}

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class GateDecision:
    """Outcome of evaluating one submission against what is already cached.

    ``action`` is one of ``accept``/``reject``/``noop``. ``noop`` means the
    submission carries no new information (identical or near-identical to
    the stored entry) and ``reject`` means it was judged worse; callers
    treat both as "do not write", but they are distinguished so the reason
    is legible in logs and tests.
    """

    action: str
    reason: str
    text_hash: str
    new_score: Optional[float] = None
    existing_score: Optional[float] = None

    @property
    def accepted(self) -> bool:
        return self.action == ACCEPT


# --- text helpers ----------------------------------------------------------


def normalize_text(boxes: Optional[Sequence[str]]) -> str:
    """Collapse a box list into the one canonical string the gate reasons
    about: per-box whitespace runs squashed, empty boxes dropped, joined by
    newline. Two submissions that differ only in whitespace or in how the
    same text was split across empty boxes hash identically."""

    if boxes is None:
        return ""
    if isinstance(boxes, str):  # tolerate a caller passing raw text
        boxes = [boxes]
    parts: List[str] = []
    for box in boxes:
        text = _WHITESPACE.sub(" ", str(box or "")).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def compute_text_hash(boxes: Optional[Sequence[str]]) -> str:
    """Stable content fingerprint stored on the row as ``text_hash``."""

    return hashlib.sha256(normalize_text(boxes).encode("utf-8")).hexdigest()


def _tokens(text: str) -> List[str]:
    return _TOKEN.findall(text.lower())


def similarity(left: str, right: str) -> float:
    """Cheap 0-1 similarity, no AI. Exact character-level ratio for normal
    page-sized text, token overlap (Dice coefficient) for anything large
    enough that quadratic matching would be a real cost."""

    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if max(len(left), len(right)) <= SEQUENCE_MATCHER_MAX_CHARS:
        return difflib.SequenceMatcher(None, left, right).ratio()

    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    shared = set(left_tokens) & set(right_tokens)
    return (2.0 * len(shared)) / (len(set(left_tokens)) + len(set(right_tokens)))


def garbage_reason(
    new_text: str,
    *,
    source_text: str = "",
    incumbent_text: str = "",
    expected_language: Optional[str] = None,
) -> Optional[str]:
    """Rule-based rejection signals, or None if the text looks plausible.

    Purely local: nothing here costs a network call, and each signal is one
    of the three the gate is specified to catch -- empty output, a script
    that cannot be what was asked for, and a length that cannot plausibly
    correspond to the source.
    """

    if not new_text:
        # An empty result is a legitimate cache entry for a page with no
        # text; it is only garbage when it would erase text we already have.
        if source_text or incumbent_text:
            return "empty_text"
        return None

    if expected_language:
        expected_script = script_registry.script_for_language(expected_language)
        actual_script = script_registry.detect_script(new_text)
        if expected_script and actual_script and actual_script != expected_script:
            return "script_mismatch"

    if source_text and len(source_text) >= MIN_LENGTH_CHECK_CHARS:
        ratio = len(new_text) / len(source_text)
        if ratio < MIN_LENGTH_RATIO or ratio > MAX_LENGTH_RATIO:
            return "length_ratio"

    return None


# --- the AI scoring step (only reached by genuinely different submissions) --


def _build_scoring_payload(
    provider_id: str, model: Optional[str], prompt: str
) -> Dict[str, Any]:
    if provider_id == "google_gemini":
        return {"contents": [{"parts": [{"text": prompt}]}]}
    return {
        "model": model or "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }


def _extract_content(provider_id: str, data: Dict[str, Any]) -> Optional[str]:
    if provider_id == "google_gemini":
        candidates = data.get("candidates")
        if isinstance(candidates, list) and candidates:
            parts = candidates[0].get("content", {}).get("parts")
            if isinstance(parts, list) and parts:
                text = parts[0].get("text")
                if isinstance(text, str):
                    return text
        return None
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
    return None


def _parse_score(content: Optional[str]) -> Optional[float]:
    if not content:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", content)
    if match is None:
        return None
    try:
        value = float(match.group(0))
    except ValueError:
        return None
    return max(MIN_SCORE, min(MAX_SCORE, value))


def score_text(
    candidate_text: str,
    *,
    source_text: str = "",
    target_lang: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    timeout: int = 20,
    http_post: Callable[..., Any] = requests.post,
) -> Optional[float]:
    """Fidelity/coherence score in 0-100 for one candidate, or None when no
    usable scoring provider is configured or the call failed.

    Returning None rather than a default score is deliberate: the caller
    must be able to tell "scored badly" apart from "could not be scored".
    """

    if not provider_config:
        return None
    provider_id = (provider_config.get("provider") or "").strip().lower()
    if provider_id not in SCORING_CAPABLE_PROVIDERS:
        return None
    api_url = provider_config.get("api_url")
    if not api_url:
        return None

    prompt = (
        "You are grading one candidate text extracted from a manga page.\n"
        "Rate it from 0 to 100 on fidelity to the source and on internal "
        "coherence as natural, readable prose"
        + (f" in {target_lang}" if target_lang else "")
        + ".\n"
        "Gibberish, repeated filler, truncated output or text unrelated to "
        "the source must score below 20.\n\n"
        f"SOURCE:\n{source_text or '(unavailable)'}\n\n"
        f"CANDIDATE:\n{candidate_text}\n\n"
        "Reply with the number only, nothing else."
    )

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    api_key = provider_config.get("api_key")
    if api_key:
        if provider_id == "google_gemini":
            headers["X-Goog-Api-Key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = http_post(
            api_url,
            json=_build_scoring_payload(
                provider_id, provider_config.get("model"), prompt
            ),
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    return _parse_score(_extract_content(provider_id, data))


# --- the gate itself -------------------------------------------------------


def evaluate(
    *,
    new_boxes: Optional[Sequence[str]],
    existing_boxes: Optional[Sequence[str]] = None,
    existing_hash: Optional[str] = None,
    existing_score: Optional[float] = None,
    source_boxes: Optional[Sequence[str]] = None,
    expected_language: Optional[str] = None,
    has_existing: bool = True,
    skip_scoring: bool = False,
    trusted: bool = True,
    provider_config: Optional[Dict[str, Any]] = None,
    scorer: Optional[Callable[..., Optional[float]]] = None,
    http_post: Callable[..., Any] = requests.post,
) -> GateDecision:
    """Decide whether ``new_boxes`` may overwrite what is already cached.

    ``has_existing`` False means there is nothing to protect: a first write
    is accepted (only outright-garbage rules still apply). ``skip_scoring``
    is set by the caller when the provider tier already settled the question
    in the new submission's favour -- the cheap checks still run, but no AI
    call is made. ``trusted`` marks a platform-default write, which is
    allowed through when no scoring provider is available; an untrusted
    write in that situation is rejected rather than assumed better.
    """

    new_text = normalize_text(new_boxes)
    new_hash = compute_text_hash(new_boxes)
    source_text = normalize_text(source_boxes)
    incumbent_text = normalize_text(existing_boxes)

    if not has_existing:
        reason = garbage_reason(
            new_text, source_text=source_text, expected_language=expected_language
        )
        if reason:
            return GateDecision(REJECT, reason, new_hash)
        return GateDecision(ACCEPT, "new_entry", new_hash)

    # (a) Exact duplicate: nothing changes, so nothing is written and no
    # Pill can be minted off someone else's already-accepted text.
    if existing_hash and existing_hash == new_hash:
        return GateDecision(
            NOOP, "identical_hash", new_hash, existing_score=existing_score
        )
    if incumbent_text and incumbent_text == new_text:
        return GateDecision(
            NOOP, "identical_text", new_hash, existing_score=existing_score
        )

    # (b) Cheap, local signals -- no AI call.
    reason = garbage_reason(
        new_text,
        source_text=source_text,
        incumbent_text=incumbent_text,
        expected_language=expected_language,
    )
    if reason:
        return GateDecision(REJECT, reason, new_hash, existing_score=existing_score)

    if (
        incumbent_text
        and similarity(incumbent_text, new_text) >= NEAR_DUPLICATE_SIMILARITY
    ):
        return GateDecision(
            NOOP, "near_duplicate", new_hash, existing_score=existing_score
        )

    if skip_scoring:
        return GateDecision(
            ACCEPT, "higher_tier", new_hash, existing_score=existing_score
        )

    # (c) Genuinely different and not obviously garbage: the only case that
    # is worth paying a model call for.
    score = scorer or score_text
    new_score = score(
        new_text,
        source_text=source_text,
        target_lang=expected_language,
        provider_config=provider_config,
        http_post=http_post,
    )
    if new_score is None:
        if trusted:
            return GateDecision(ACCEPT, "unscored_trusted_write", new_hash)
        return GateDecision(REJECT, "no_scoring_provider", new_hash)

    resolved_existing = existing_score
    if resolved_existing is None:
        resolved_existing = score(
            incumbent_text,
            source_text=source_text,
            target_lang=expected_language,
            provider_config=provider_config,
            http_post=http_post,
        )

    if resolved_existing is None:
        # The incumbent has never been scored and could not be scored now;
        # without a baseline there is no evidence of improvement.
        return GateDecision(
            REJECT if not trusted else ACCEPT,
            "existing_unscored",
            new_hash,
            new_score=new_score,
        )

    if new_score > resolved_existing:
        return GateDecision(
            ACCEPT, "higher_score", new_hash, new_score, resolved_existing
        )
    return GateDecision(
        REJECT, "not_better_than_existing", new_hash, new_score, resolved_existing
    )


__all__ = [
    "ACCEPT",
    "REJECT",
    "NOOP",
    "GateDecision",
    "compute_text_hash",
    "normalize_text",
    "similarity",
    "garbage_reason",
    "score_text",
    "evaluate",
    "NEAR_DUPLICATE_SIMILARITY",
    "SCORING_CAPABLE_PROVIDERS",
]
