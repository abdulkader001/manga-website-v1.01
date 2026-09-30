"""Canonical catalogue of ad slot placements.

A *placement* is a named region of the site that ad slots can be assigned to
from the admin panel. Pages mount a placement by key once; admins then decide
which creatives land there without anyone touching page code again.

The ``global_*`` placements are the important ones operationally: they are
mounted in the application shell, so a slot assigned to them renders on every
page (including every chapter) automatically.
"""

from __future__ import annotations

from typing import Any, Dict, List

GLOBAL_SCOPE = "global"

AD_PLACEMENTS: List[Dict[str, str]] = [
    {
        "key": "global_top",
        "label": "Site-wide — Top (below the navbar)",
        "scope": GLOBAL_SCOPE,
        "description": "Renders on every page, directly under the navigation bar.",
    },
    {
        "key": "global_bottom",
        "label": "Site-wide — Bottom (above the footer)",
        "scope": GLOBAL_SCOPE,
        "description": "Renders on every page, directly above the footer.",
    },
    {
        "key": "homepage_top",
        "label": "Homepage — Top",
        "scope": "homepage",
        "description": "Above the first homepage section.",
    },
    {
        "key": "homepage_mid",
        "label": "Homepage — Middle",
        "scope": "homepage",
        "description": "Between the homepage content sections.",
    },
    {
        "key": "homepage_bottom",
        "label": "Homepage — Bottom",
        "scope": "homepage",
        "description": "Below the homepage listings.",
    },
    {
        "key": "chapter_top",
        "label": "Chapter reader — Top",
        "scope": "chapter",
        "description": "Above the chapter pages in the reader.",
    },
    {
        "key": "chapter_bottom",
        "label": "Chapter reader — Bottom",
        "scope": "chapter",
        "description": "Below the chapter pages, above the navigation controls.",
    },
    {
        "key": "browse_top",
        "label": "Browse — Top",
        "scope": "browse",
        "description": "Above the browse results grid.",
    },
    {
        "key": "browse_bottom",
        "label": "Browse — Bottom",
        "scope": "browse",
        "description": "Below the browse results grid.",
    },
]

PLACEMENT_KEYS = frozenset(item["key"] for item in AD_PLACEMENTS)


def is_valid_placement(placement: str | None) -> bool:
    """Return True when ``placement`` is empty or a known placement key.

    An empty placement is allowed: it means "not placed yet", which keeps a
    slot editable in the admin panel without forcing it on-screen.
    """

    if placement is None or placement == "":
        return True
    return placement in PLACEMENT_KEYS


def list_placements() -> List[Dict[str, Any]]:
    """Return the placement catalogue for the admin dropdown."""

    return [dict(item) for item in AD_PLACEMENTS]


__all__ = [
    "AD_PLACEMENTS",
    "PLACEMENT_KEYS",
    "is_valid_placement",
    "list_placements",
]
