"""Normalized OCR output (SRS 2B.6).

"Every OCR source returns this shape and nothing else. The frontend must be
unable to determine which engine produced a result." This module is the
single place that assembles the normalized shape from whatever a given
engine returned (Tesseract's TSV grouping, or an external API's own JSON),
so callers -- and the frontend -- only ever see one contract.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import reading_order as reading_order_mod
from . import region_classifier
from . import script_registry

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

# 2B.5 provider types, ranked by expected recognition quality. Purely
# informational (drives cache quality tiering, 1H.14.8), never exposed to
# the frontend as anything but the integer in the normalized shape.
ENGINE_TIER_BY_PROVIDER: Dict[str, int] = {
    "tesseract_local": 1,
    "custom": 2,
    "ocr_space_free": 2,
    "system": 2,
    "azure_computer_vision": 3,
    "ibm_watson_vision": 3,
    "amazon_textract": 3,
    "google_cloud_vision": 4,
}
DEFAULT_ENGINE_TIER = 2


def engine_tier_for(provider_id: Optional[str]) -> int:
    if not provider_id:
        return DEFAULT_ENGINE_TIER
    return ENGINE_TIER_BY_PROVIDER.get(provider_id.strip().lower(), DEFAULT_ENGINE_TIER)


def build_normalized_output(
    raw_regions: List[Dict[str, Any]],
    *,
    page: Dict[str, Any],
    provider_id: Optional[str] = None,
    language_hint: Optional[str] = None,
    image: Optional["Image.Image"] = None,
    reading_order_mode_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the 2B.6 shape from raw ``{text, x, y, width, height, confidence}``
    region dicts. Region ordering in the output follows reading order, not
    detection order.
    """

    combined_text = " ".join(
        str(r.get("text") or "").strip() for r in raw_regions if r.get("text")
    ).strip()
    detected_language, detected_script = script_registry.detect_language(
        combined_text, hint=language_hint
    )

    mode = (
        reading_order_mode_override
        or script_registry.SCRIPT_READING_ORDER_MODE.get(detected_language or "", None)
        or script_registry.SCRIPT_READING_ORDER_MODE.get(
            detected_script or "", "ltr_ttb"
        )
    )

    coordinate_regions: List[Dict[str, Any]] = []
    for raw in raw_regions:
        coordinate_regions.append(
            {
                "coordinates": {
                    "x": float(raw.get("x") or 0.0),
                    "y": float(raw.get("y") or 0.0),
                    "width": float(raw.get("width") or 0.0),
                    "height": float(raw.get("height") or 0.0),
                }
            }
        )

    order_by_index = reading_order_mod.compute_reading_order(
        coordinate_regions, page, mode=mode
    )

    regions: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_regions):
        box = coordinate_regions[idx]["coordinates"]
        confidence = float(
            raw.get("confidence") if raw.get("confidence") is not None else 100.0
        )
        region_type = raw.get("region_type") or region_classifier.classify_region(
            box, page=page, confidence=confidence, image=image
        )
        region = {
            "index": idx,
            "text": str(raw.get("text") or ""),
            "coordinates": box,
            "confidence": confidence,
            "region_type": region_type,
            "reading_order": order_by_index[idx],
        }
        styling = region_classifier.sample_background(image, box)
        if styling:
            region.update(styling)
        regions.append(region)

    # Present regions in reading order -- the natural iteration order for
    # every downstream consumer (translation context, overlap resolution).
    regions.sort(key=lambda r: r["reading_order"])

    return {
        "regions": regions,
        "detected_language": detected_language,
        "detected_script": detected_script,
        "reading_order_mode": mode,
        "engine_tier": engine_tier_for(provider_id),
    }


__all__ = ["build_normalized_output", "engine_tier_for", "ENGINE_TIER_BY_PROVIDER"]
