"""Curated overlay font set (SRS 2F.2A).

"A short, curated list, not an open font gallery" -- a handful of options
per category (standard / anime-manga / calligraphy / handwriting), chosen
for legibility at typical bubble size. The built-in list below is the
zero-config baseline; an administrator can add to or curate it without a
code change by writing a replacement list to
``SystemSettings.overlay_fonts`` (via the admin endpoint in this slice),
which fully overrides the built-ins when present.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import SystemSettings

CATEGORY_STANDARD = "standard"
CATEGORY_ANIME_MANGA = "anime_manga"
CATEGORY_CALLIGRAPHY = "calligraphy"
CATEGORY_HANDWRITING = "handwriting"

CATEGORIES = (
    CATEGORY_STANDARD,
    CATEGORY_ANIME_MANGA,
    CATEGORY_CALLIGRAPHY,
    CATEGORY_HANDWRITING,
)

# Deliberately small: a "clean, highly legible sans-serif" default, one or
# two manga/anime lettering-style fonts, one calligraphy script, one casual
# handwriting face. ``css_family`` is a web-safe/system fallback so the
# picker and live preview work even before the on-demand webfont loads.
BUILTIN_FONTS: List[Dict[str, Any]] = [
    {
        "id": "standard_sans",
        "label": "Standard",
        "category": CATEGORY_STANDARD,
        "css_family": "'Inter', 'Helvetica Neue', Arial, sans-serif",
        "file_url": None,
        "default": True,
    },
    {
        "id": "anime_ace",
        "label": "Anime Ace",
        "category": CATEGORY_ANIME_MANGA,
        "css_family": "'Anime Ace', 'Comic Sans MS', sans-serif",
        "file_url": "/static/fonts/anime-ace.woff2",
        "default": False,
    },
    {
        "id": "wild_words",
        "label": "Wild Words",
        "category": CATEGORY_ANIME_MANGA,
        "css_family": "'Wild Words', 'Comic Sans MS', sans-serif",
        "file_url": "/static/fonts/wild-words.woff2",
        "default": False,
    },
    {
        "id": "manga_calligraphy",
        "label": "Calligraphy",
        "category": CATEGORY_CALLIGRAPHY,
        "css_family": "'Pinyon Script', 'Brush Script MT', cursive",
        "file_url": "/static/fonts/pinyon-script.woff2",
        "default": False,
    },
    {
        "id": "casual_handwriting",
        "label": "Handwriting",
        "category": CATEGORY_HANDWRITING,
        "css_family": "'Patrick Hand', 'Segoe Print', cursive",
        "file_url": "/static/fonts/patrick-hand.woff2",
        "default": False,
    },
]

_KNOWN_CATEGORIES = frozenset(CATEGORIES)


class OverlayFontError(ValueError):
    pass


def _validate_font_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    font_id = str(entry.get("id") or "").strip()
    label = str(entry.get("label") or "").strip()
    category = str(entry.get("category") or "").strip().lower()
    if not font_id or not label:
        raise OverlayFontError("each font needs an id and a label")
    if category not in _KNOWN_CATEGORIES:
        raise OverlayFontError(f"category must be one of {sorted(_KNOWN_CATEGORIES)}")
    css_family = entry.get("css_family")
    if not isinstance(css_family, str) or not css_family.strip():
        raise OverlayFontError("css_family is required")
    file_url = entry.get("file_url")
    if file_url is not None and not isinstance(file_url, str):
        raise OverlayFontError("file_url must be a string or null")
    return {
        "id": font_id,
        "label": label,
        "category": category,
        "css_family": css_family.strip(),
        "file_url": file_url,
        "default": bool(entry.get("default", False)),
    }


def validate_font_list(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(entries, list) or not entries:
        raise OverlayFontError("font list must be a non-empty array")
    cleaned = [_validate_font_entry(e) for e in entries]
    ids = [f["id"] for f in cleaned]
    if len(ids) != len(set(ids)):
        raise OverlayFontError("font ids must be unique")
    return cleaned


def _admin_configured_fonts(db: Optional[Session]) -> Optional[List[Dict[str, Any]]]:
    if db is None:
        return None
    settings = db.query(SystemSettings).first()
    fonts = getattr(settings, "overlay_fonts", None) if settings else None
    if isinstance(fonts, list) and fonts:
        return fonts
    return None


def list_fonts(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    return _admin_configured_fonts(db) or list(BUILTIN_FONTS)


def is_known_font(font_id: str, db: Optional[Session] = None) -> bool:
    return any(f["id"] == font_id for f in list_fonts(db))


def default_font_id(db: Optional[Session] = None) -> str:
    for font in list_fonts(db):
        if font.get("default"):
            return font["id"]
    fonts = list_fonts(db)
    return fonts[0]["id"] if fonts else "standard_sans"


__all__ = [
    "BUILTIN_FONTS",
    "CATEGORIES",
    "OverlayFontError",
    "validate_font_list",
    "list_fonts",
    "is_known_font",
    "default_font_id",
]
