"""Script support model (SRS 2B.1) and script/language detection.

Capability is organised by writing system, not language, because script is
what changes the technical handling (2B.1). Adding a language within an
already-supported script is configuration plus a language pack -- zero
code changes (1H.9.1) -- so the language->script map below is the only
thing that grows when a new language is added; nothing that reads it needs
to change.

Detection works from the OCR'd text itself (Unicode block membership),
never from a caller-supplied hint alone: 1H.9.1 says a website's declared
languages are "a detection hint, never a constraint," and 1E.1.2 fixes
source language as always auto-detected, never user-selectable.
"""

from __future__ import annotations

import unicodedata
from typing import Dict, List, Optional, Tuple

SCRIPT_CJK = "cjk"
SCRIPT_LATIN = "latin"
SCRIPT_INDIC = "indic"
SCRIPT_ARABIC_HEBREW = "arabic_hebrew"
SCRIPT_CYRILLIC = "cyrillic"
SCRIPT_THAI_KHMER_LAO = "thai_khmer_lao"

# script_id -> (languages, difficulty, special_handling, default reading_order_mode)
SCRIPTS: Dict[str, Dict[str, object]] = {
    SCRIPT_CJK: {
        "label": "CJK",
        "languages": ["ja", "zh-Hans", "zh-Hant", "ko"],
        "difficulty": "hardest",
        "special_handling": "Vertical text, furigana, dense glyphs",
    },
    SCRIPT_LATIN: {
        "label": "Latin",
        "languages": ["en", "fil", "id", "es", "pt", "fr"],
        "difficulty": "easiest",
        "special_handling": "Best accuracy available",
    },
    SCRIPT_INDIC: {
        "label": "Indic",
        "languages": ["hi", "ta", "bn", "te", "mr"],
        "difficulty": "medium",
        "special_handling": "Conjunct characters, ligatures",
    },
    SCRIPT_ARABIC_HEBREW: {
        "label": "Arabic / Hebrew",
        "languages": ["ar", "ur", "he", "fa"],
        "difficulty": "medium-hard",
        "special_handling": "Right-to-left, cursive joining",
    },
    SCRIPT_CYRILLIC: {
        "label": "Cyrillic",
        "languages": ["ru", "uk"],
        "difficulty": "easy",
        "special_handling": "",
    },
    SCRIPT_THAI_KHMER_LAO: {
        "label": "Thai / Khmer / Lao",
        "languages": ["th", "km", "lo"],
        "difficulty": "medium",
        "special_handling": "No word boundaries",
    },
}

# Reading order mode per script (2B.4). Chinese manhua is explicitly
# "varies -- detect per series" in the spec; ltr_ttb is the sane default
# and callers may still override per series/website via the same
# reading_order_mode value (script_registry only supplies the default).
SCRIPT_READING_ORDER_MODE: Dict[str, str] = {
    "ja": "rtl_vertical",
    "zh-Hans": "ltr_ttb",
    "zh-Hant": "ltr_ttb",
    "ko": "ttb_column",
    SCRIPT_INDIC: "ltr_ttb",
    SCRIPT_ARABIC_HEBREW: "rtl_ttb",
    SCRIPT_CYRILLIC: "ltr_ttb",
    SCRIPT_THAI_KHMER_LAO: "ltr_ttb",
    SCRIPT_LATIN: "ltr_ttb",
}

# 2B.2: "typical size 2-15MB per language; the size is shown to the user
# before download". Approximate on-disk sizes for the browser WASM packs
# (1H.13); purely informational metadata surfaced to the client.
LANGUAGE_PACK_SIZE_MB: Dict[str, float] = {
    "ja": 15.0,
    "zh-Hans": 14.0,
    "zh-Hant": 14.0,
    "ko": 10.0,
    "en": 4.0,
    "fil": 3.0,
    "id": 3.0,
    "es": 3.5,
    "pt": 3.5,
    "fr": 3.5,
    "hi": 6.0,
    "ta": 6.5,
    "bn": 6.0,
    "te": 6.5,
    "mr": 6.0,
    "ar": 5.0,
    "ur": 5.0,
    "he": 4.5,
    "fa": 5.0,
    "ru": 4.0,
    "uk": 4.0,
    "th": 5.5,
    "km": 6.0,
    "lo": 5.5,
}


def script_for_language(lang_code: str) -> Optional[str]:
    lang_code = (lang_code or "").strip()
    for script_id, meta in SCRIPTS.items():
        if lang_code in meta["languages"]:
            return script_id
    return None


def all_languages() -> List[str]:
    langs: List[str] = []
    for meta in SCRIPTS.values():
        langs.extend(meta["languages"])
    return langs


# --- Unicode-block based script/language detection -------------------------
# A well-known, dependency-free technique: classify each character by the
# Unicode block it falls in, then take the plurality. No extra OCR pass is
# needed -- this runs on whatever text the (script-hinted) OCR pass already
# produced.

_HIRAGANA = (0x3040, 0x309F)
_KATAKANA = (0x30A0, 0x30FF)
_CJK_UNIFIED = (0x4E00, 0x9FFF)
_HANGUL = (0xAC00, 0xD7A3)
_HANGUL_JAMO = (0x1100, 0x11FF)
_ARABIC = (0x0600, 0x06FF)
_HEBREW = (0x0590, 0x05FF)
_DEVANAGARI = (0x0900, 0x097F)
_BENGALI = (0x0980, 0x09FF)
_TAMIL = (0x0B80, 0x0BFF)
_TELUGU = (0x0C00, 0x0C7F)
_CYRILLIC = (0x0400, 0x04FF)
_THAI = (0x0E00, 0x0E7F)
_KHMER = (0x1780, 0x17FF)
_LAO = (0x0E80, 0x0EFF)
_LATIN_BASIC = (0x0041, 0x024F)


def _in(code: int, block: Tuple[int, int]) -> bool:
    return block[0] <= code <= block[1]


def detect_script(text: str) -> Optional[str]:
    """Best-effort script id from the characters actually present."""

    counts: Dict[str, int] = {}

    def bump(key: str, n: int = 1) -> None:
        counts[key] = counts.get(key, 0) + n

    for ch in text or "":
        code = ord(ch)
        if not ch.strip() or unicodedata.category(ch).startswith(("P", "Z", "N")):
            continue
        if _in(code, _HIRAGANA) or _in(code, _KATAKANA):
            bump("ja")
        elif _in(code, _HANGUL) or _in(code, _HANGUL_JAMO):
            bump("ko")
        elif _in(code, _CJK_UNIFIED):
            bump("zh")
        elif _in(code, _ARABIC):
            bump(SCRIPT_ARABIC_HEBREW)
        elif _in(code, _HEBREW):
            bump(SCRIPT_ARABIC_HEBREW)
        elif (
            _in(code, _DEVANAGARI)
            or _in(code, _BENGALI)
            or _in(code, _TAMIL)
            or _in(code, _TELUGU)
        ):
            bump(SCRIPT_INDIC)
        elif _in(code, _CYRILLIC):
            bump(SCRIPT_CYRILLIC)
        elif _in(code, _THAI) or _in(code, _KHMER) or _in(code, _LAO):
            bump(SCRIPT_THAI_KHMER_LAO)
        elif _in(code, _LATIN_BASIC):
            bump(SCRIPT_LATIN)

    if not counts:
        return None

    top_key = max(counts, key=lambda k: counts[k])
    if top_key in ("ja", "ko", "zh"):
        return SCRIPT_CJK
    return top_key


def detect_language(
    text: str, *, hint: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Return (detected_language, detected_script) for OCR'd ``text``.

    ``hint`` is the website's declared language (1H.9.1) -- consulted only
    to disambiguate within a detected script (e.g. zh-Hans vs zh-Hant),
    never to override what the characters actually are.
    """

    counts: Dict[str, int] = {}

    def bump(key: str, n: int = 1) -> None:
        counts[key] = counts.get(key, 0) + n

    for ch in text or "":
        code = ord(ch)
        if not ch.strip():
            continue
        if _in(code, _HIRAGANA) or _in(code, _KATAKANA):
            bump("ja")
        elif _in(code, _HANGUL) or _in(code, _HANGUL_JAMO):
            bump("ko")
        elif _in(code, _CJK_UNIFIED):
            bump("zh")
        elif _in(code, _ARABIC):
            bump("ar")
        elif _in(code, _HEBREW):
            bump("he")
        elif _in(code, _DEVANAGARI):
            bump("hi")
        elif _in(code, _BENGALI):
            bump("bn")
        elif _in(code, _TAMIL):
            bump("ta")
        elif _in(code, _TELUGU):
            bump("te")
        elif _in(code, _CYRILLIC):
            bump("ru")
        elif _in(code, _THAI):
            bump("th")
        elif _in(code, _KHMER):
            bump("km")
        elif _in(code, _LAO):
            bump("lo")
        elif _in(code, _LATIN_BASIC):
            bump("latin")

    if not counts:
        return (hint, script_for_language(hint) if hint else None)

    top_key = max(counts, key=lambda k: counts[k])

    if top_key == "zh":
        # Script alone can't distinguish Simplified/Traditional; prefer the
        # website's declared hint when it's actually a Chinese variant,
        # otherwise default to Simplified.
        if hint in ("zh-Hans", "zh-Hant"):
            return (hint, SCRIPT_CJK)
        return ("zh-Hans", SCRIPT_CJK)

    if top_key == "latin":
        # Latin script covers many languages the character set alone can't
        # separate (accented Latin letters overlap heavily). The website's
        # declared hint decides; otherwise fall back to English.
        if hint and script_for_language(hint) == SCRIPT_LATIN:
            return (hint, SCRIPT_LATIN)
        return ("en", SCRIPT_LATIN)

    script_id = script_for_language(top_key) or {
        "ja": SCRIPT_CJK,
        "ko": SCRIPT_CJK,
    }.get(top_key)
    return (top_key, script_id)


__all__ = [
    "SCRIPTS",
    "SCRIPT_CJK",
    "SCRIPT_LATIN",
    "SCRIPT_INDIC",
    "SCRIPT_ARABIC_HEBREW",
    "SCRIPT_CYRILLIC",
    "SCRIPT_THAI_KHMER_LAO",
    "SCRIPT_READING_ORDER_MODE",
    "LANGUAGE_PACK_SIZE_MB",
    "script_for_language",
    "all_languages",
    "detect_script",
    "detect_language",
]
