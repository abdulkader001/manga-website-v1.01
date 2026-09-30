"""AI/OCR conflict handling (SRS 2A.3).

When OCR and AI are both available, AI is invoked only for regions OCR
struggled with -- never wholesale -- so it "does not unnecessarily consume
resources." This module decides, from the already-normalized OCR regions
(2B.6), which ones need AI help and whether the page is broken badly enough
that a single whole-page AI pass (closer to M2) makes more sense than many
per-region calls.

Two of 2A.3's five listed triggers are directly detectable from the
normalized shape and are implemented here:

  - "Text OCR did not detect at all" / "OCR failed" -> empty region text
  - "Regions below the confidence threshold"        -> region confidence

The other three ("difficult or low-contrast images", "complex or
unconventional layouts") require real image/layout analysis this module
doesn't have inputs for, so they're not claimed here; low OCR confidence is
already a reasonable proxy for "the image was hard to read," which is the
one that can be judged from OCR output alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal

# 2A.3: "AI invocation is per-region, never per-page, when OCR succeeded on
# most regions." When OCR failed broadly, a single whole-page AI pass is
# more sensible than many per-region calls -- this is the crossover point.
WHOLE_PAGE_FAILURE_RATIO = 0.5

Mode = Literal["none", "per_region", "whole_page"]


@dataclass(frozen=True)
class AiAssistPlan:
    mode: Mode
    region_indices: List[int] = field(default_factory=list)


def plan_ai_assist(
    regions: List[Dict[str, Any]],
    *,
    ai_assist_enabled: bool,
    confidence_threshold: float,
    ai_available: bool,
) -> AiAssistPlan:
    """Decide which regions (if any) need AI assistance.

    ``confidence_threshold`` is a 0-1 fraction (UserProcessingSettings.
    ai_confidence_threshold, D12); region confidence in the normalized
    shape is 0-100, so the two are compared on the same 0-1 scale here.
    """

    if not ai_assist_enabled or not ai_available or not regions:
        return AiAssistPlan(mode="none")

    flagged: List[int] = []
    for region in regions:
        text = str(region.get("text") or "").strip()
        confidence = region.get("confidence")
        index = int(region.get("index", len(flagged)))
        if not text:
            flagged.append(index)
            continue
        if (
            confidence is not None
            and (float(confidence) / 100.0) < confidence_threshold
        ):
            flagged.append(index)

    if not flagged:
        return AiAssistPlan(mode="none")

    failure_ratio = len(flagged) / len(regions)
    if failure_ratio > WHOLE_PAGE_FAILURE_RATIO:
        return AiAssistPlan(
            mode="whole_page", region_indices=[r["index"] for r in regions]
        )

    return AiAssistPlan(mode="per_region", region_indices=flagged)


__all__ = ["AiAssistPlan", "plan_ai_assist", "WHOLE_PAGE_FAILURE_RATIO"]
