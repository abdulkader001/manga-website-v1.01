"""Script-dependent reading order (SRS 2B.4).

"Wrong reading order produces dialogue that is individually correct and
collectively nonsense" -- so this is computed, never assumed. Regions are
grouped into horizontal row bands (tolerant of the natural misalignment
between neighbouring bubbles) and ordered right-to-left or left-to-right
within each band depending on the script/format's ``reading_order_mode``.
"""

from __future__ import annotations

from typing import Any, Dict, List

MODE_RTL_VERTICAL = "rtl_vertical"  # Japanese manga: right-to-left, top-to-bottom
MODE_TTB_COLUMN = "ttb_column"  # Korean webtoon: top-to-bottom, single column
MODE_LTR_TTB = "ltr_ttb"  # Latin comics / Chinese manhua default
MODE_RTL_TTB = "rtl_ttb"  # Arabic / Hebrew

VALID_MODES = (MODE_RTL_VERTICAL, MODE_TTB_COLUMN, MODE_LTR_TTB, MODE_RTL_TTB)

# Fraction of page height within which two regions are considered to be on
# the "same row" even if their top coordinates aren't pixel-identical.
ROW_BAND_TOLERANCE_RATIO = 0.06


def _center_y(region: Dict[str, Any]) -> float:
    coords = region["coordinates"]
    return float(coords["y"]) + float(coords["height"]) / 2.0


def _left(region: Dict[str, Any]) -> float:
    return float(region["coordinates"]["x"])


def _row_band(region: Dict[str, Any], tolerance: float) -> int:
    return int(round(_center_y(region) / tolerance))


def compute_reading_order(
    regions: List[Dict[str, Any]], page: Dict[str, Any], *, mode: str
) -> List[int]:
    """Return, for each region in ``regions`` (by index), its 0-based
    reading position under ``mode``."""

    if not regions:
        return []
    if mode not in VALID_MODES:
        mode = MODE_LTR_TTB

    page_height = float(page.get("height") or 1) or 1.0
    tolerance = max(1.0, page_height * ROW_BAND_TOLERANCE_RATIO)

    indices = list(range(len(regions)))

    if mode == MODE_TTB_COLUMN:
        # Single column: pure top-to-bottom, left as a tiebreak only.
        indices.sort(key=lambda i: (_center_y(regions[i]), _left(regions[i])))
    elif mode in (MODE_RTL_VERTICAL, MODE_RTL_TTB):
        indices.sort(
            key=lambda i: (_row_band(regions[i], tolerance), -_left(regions[i]))
        )
    else:  # MODE_LTR_TTB
        indices.sort(
            key=lambda i: (_row_band(regions[i], tolerance), _left(regions[i]))
        )

    order_by_index = [0] * len(regions)
    for order, region_index in enumerate(indices):
        order_by_index[region_index] = order
    return order_by_index


__all__ = [
    "compute_reading_order",
    "MODE_RTL_VERTICAL",
    "MODE_TTB_COLUMN",
    "MODE_LTR_TTB",
    "MODE_RTL_TTB",
    "VALID_MODES",
]
