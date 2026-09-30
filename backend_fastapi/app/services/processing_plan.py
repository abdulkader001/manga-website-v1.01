"""Processing methods and provider priority (SRS 2A).

Binding priority chains carried directly from 2A.2. The three "cases" there
describe the common whole-account combinations; the actual mechanism here
is per-service (OCR / translation / AI resolve independently to "user" or
"platform_default"), which reproduces all three cases exactly and also
degrades sensibly for a partially-configured account the spec doesn't
explicitly name (e.g. a user with only OCR configured). ``case`` on the
resulting plan is a descriptive label, not a second code path.

The system must never run everything simultaneously (2A.3) -- with OCR and
translation configured, AI stays idle during normal processing. That's
enforced by ``ai_role``: only "primary" (Case 2, M2) actually always calls
AI; "idle_unless_assist" (Case 1, M1/M3) calls it only for the specific
regions ai_assist.plan_ai_assist flags; "fallback_only" (Case 3) calls it
only if the platform-default OCR+translation chain itself fails outright.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

METHOD_OCR_TRANSLATION = "M1"
METHOD_AI = "M2"
METHOD_HYBRID = "M3"

CASE_USER_OCR_TRANSLATION = 1
CASE_USER_AI_ONLY = 2
CASE_PLATFORM_DEFAULT = 3

Source = Literal["user", "platform_default"]
AiRole = Literal["idle_unless_assist", "primary", "fallback_only"]


@dataclass(frozen=True)
class ProcessingPlan:
    case: int
    method: str
    ocr_source: Source
    translation_source: Source
    ai_source: Source
    ai_role: AiRole


def resolve_plan(
    *, has_user_ocr: bool, has_user_translation: bool, has_user_ai: bool
) -> ProcessingPlan:
    """Resolve the provider-priority chain and processing method for one
    account's current configuration (2A.2)."""

    if has_user_ocr and has_user_translation:
        # Case 1: OCR + Translation (+ AI). AI stays idle unless assisting.
        return ProcessingPlan(
            case=CASE_USER_OCR_TRANSLATION,
            method=METHOD_HYBRID if has_user_ai else METHOD_OCR_TRANSLATION,
            ocr_source="user",
            translation_source="user",
            ai_source="user" if has_user_ai else "platform_default",
            ai_role="idle_unless_assist",
        )

    if has_user_ai:
        # Case 2: AI only. A single AI pass is the primary path; the
        # platform defaults are the fallback if AI itself fails.
        return ProcessingPlan(
            case=CASE_USER_AI_ONLY,
            method=METHOD_AI,
            ocr_source="user" if has_user_ocr else "platform_default",
            translation_source="user" if has_user_translation else "platform_default",
            ai_source="user",
            ai_role="primary",
        )

    # Case 3: nothing configured. Platform defaults for OCR/translation;
    # platform AI is the last-resort fallback if that chain fails.
    return ProcessingPlan(
        case=CASE_PLATFORM_DEFAULT,
        method=METHOD_OCR_TRANSLATION,
        ocr_source="user" if has_user_ocr else "platform_default",
        translation_source="user" if has_user_translation else "platform_default",
        ai_source="platform_default",
        ai_role="fallback_only",
    )


__all__ = [
    "ProcessingPlan",
    "resolve_plan",
    "METHOD_OCR_TRANSLATION",
    "METHOD_AI",
    "METHOD_HYBRID",
    "CASE_USER_OCR_TRANSLATION",
    "CASE_USER_AI_ONLY",
    "CASE_PLATFORM_DEFAULT",
]
