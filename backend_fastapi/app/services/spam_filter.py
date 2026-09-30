"""Automated spam/abuse pre-filter for comments (SRS 3A.3).

A lightweight heuristic screen, not a moderation decision: a flagged comment
still posts (D5's established pattern -- flag for review, never auto-block a
false positive) but is queued for a human moderator via the same
``ContentReport`` table a user report uses.
"""

from __future__ import annotations

import re
from typing import Optional

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_REPEATED_CHAR_RE = re.compile(r"(.)\1{9,}")  # same char 10+ times in a row


def flag_reason(content: str) -> Optional[str]:
    """Return a short machine reason if ``content`` looks like spam/abuse,
    or ``None`` if it looks fine."""

    text = (content or "").strip()
    if not text:
        return None

    if len(_URL_RE.findall(text)) >= 3:
        return "excessive_links"

    if _REPEATED_CHAR_RE.search(text):
        return "character_flood"

    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 20:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio > 0.8:
            return "excessive_caps"

    return None


__all__ = ["flag_reason"]
