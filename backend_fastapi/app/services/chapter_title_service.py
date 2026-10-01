"""Readable chapter titles.

Source sites put whatever they like in the chapter link text, e.g.
``"522 원준 522화 2024-11-07"`` (number, series name, "episode 522", upload
date). Shown raw, that is noise in a foreign script. This module turns it into
``"Chapter 522"`` -- plus a real subtitle, translated, when there is one:

1. :func:`clean_title` strips dates, episode markers that only restate the
   number (522화, 第12话, Ch. 12, Episode 12 ...) and the bare number.
2. Words left over in most of a series' chapters are the series name, not a
   subtitle, and are dropped (:func:`series_noise`).
3. What remains, if it is in another script than the reader's language, is
   translated once per (chapter, language) and cached on the chapter row.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from ..models import Chapter, Manga
from ..models.manga import chapter_number_value

_NUM = r"\d+(?:[.,]\d+)?"

_PATTERNS = [
    # Dates: 2024-11-07, 2024.11.07, 24.11.07, 2024/11/07, 2024년 11월 7일
    re.compile(r"\b\d{2,4}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{1,2}\b"),
    re.compile(r"\d{2,4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"),
    # Korean: 522화, 제522화, 522 화, 522회
    re.compile(rf"제?\s*{_NUM}\s*[화회]"),
    # Chinese / Japanese: 第12话, 第12話, 第12章, 第12回, 12話
    re.compile(rf"第?\s*{_NUM}\s*[话話章回集]"),
    # Latin: Chapter 12, Ch. 12, Chap 12, Episode 12, Ep. 12, #12
    re.compile(rf"\b(?:chapter|chap|ch|episode|ep)\.?\s*{_NUM}\b", re.IGNORECASE),
    re.compile(rf"#\s*{_NUM}"),
]

_NON_LATIN = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏㐀-鿿가-힯豈-﫿]")
_SEPARATORS = re.compile(r"^[\s\-–—:|/.,·•_()\[\]{}]+|[\s\-–—:|/.,·•_()\[\]{}]+$")
_SPACES = re.compile(r"\s+")

# Languages written in the scripts _NON_LATIN matches.
_CJK_LANGS = {"ko", "ja", "zh"}


def _number_tokens(number: Any) -> List[str]:
    value = chapter_number_value(number)
    if value is None:
        return []
    text = str(value)
    tokens = {text}
    if isinstance(value, float) and value.is_integer():
        tokens.add(str(int(value)))
    return sorted(tokens, key=len, reverse=True)


def clean_title(raw: Optional[str], number: Any = None) -> Optional[str]:
    """The part of a scraped title that says something beyond the number."""

    text = (raw or "").strip()
    if not text:
        return None
    for pattern in _PATTERNS:
        text = pattern.sub(" ", text)
    for token in _number_tokens(number):
        text = re.sub(rf"(?<![\d.]){re.escape(token)}(?![\d.])", " ", text)
    text = _SPACES.sub(" ", text)
    # Separators left dangling once the number/date around them is gone.
    previous = None
    while previous != text:
        previous = text
        text = _SEPARATORS.sub("", text).strip()
    return text or None


def series_noise(cleaned: Iterable[Optional[str]]) -> set[str]:
    """Leftovers that repeat across most chapters (the series name, the site's
    label for it): those are not chapter subtitles."""

    values = [c for c in cleaned]
    present = [c for c in values if c]
    if len(values) < 3 or not present:
        return set()
    counts = Counter(present)
    # More than half of all chapters, and at least three: a subtitle reused
    # by a couple of chapters ("Part 1"/"Part 2" arcs) is still a subtitle.
    return {text for text, n in counts.items() if n >= 3 and n * 2 > len(values)}


def needs_translation(text: str, target_lang: str) -> bool:
    return bool(_NON_LATIN.search(text)) and (target_lang or "en")[:2] not in _CJK_LANGS


def _label(number: Any) -> str:
    value = chapter_number_value(number)
    return f"Chapter {value}" if value is not None else "Chapter"


def display_titles(
    db: Session,
    manga: Manga,
    target_lang: str,
    *,
    translate: Optional[Callable[[str], Optional[str]]] = None,
    max_new_translations: int = 30,
) -> Dict[int, Dict[str, Optional[str]]]:
    """``{chapter_id: {"title": ..., "original": ...}}`` for every chapter.

    ``translate`` is called once per distinct subtitle that is not cached yet
    (at most ``max_new_translations`` per call; the rest are picked up on the
    next one). Without it, foreign-script subtitles are left out rather than
    shown untranslated.
    """

    lang = (target_lang or "en").strip().lower()[:8] or "en"
    chapters: Sequence[Chapter] = (
        db.query(Chapter).filter(Chapter.manga_id == manga.id).all()
    )
    cleaned = {c.id: clean_title(c.chapter_title, c.chapter_number) for c in chapters}
    noise = series_noise(cleaned.values())
    series_names = {
        _SPACES.sub("", t).lower()
        for t in [manga.title, *(manga.alternative_titles or [])]
        if isinstance(t, str) and t.strip()
    }

    noise_compact = {_SPACES.sub("", t).lower() for t in noise}

    def is_series_name(text: str) -> bool:
        compact = _SPACES.sub("", text).lower()
        return compact in noise_compact or compact in series_names

    pending: Dict[str, List[Chapter]] = {}
    out: Dict[int, Dict[str, Optional[str]]] = {}
    for chapter in chapters:
        sub = cleaned[chapter.id]
        if sub and is_series_name(sub):
            sub = None
        label = _label(chapter.chapter_number)
        title = label
        if sub:
            if not needs_translation(sub, lang):
                title = f"{label}: {sub}"
            else:
                cached = (chapter.title_translations or {}).get(lang)
                if cached:
                    title = f"{label}: {cached}"
                else:
                    pending.setdefault(sub, []).append(chapter)
        out[chapter.id] = {"title": title, "original": chapter.chapter_title}

    if translate and pending:
        changed = False
        for sub, owners in list(pending.items())[:max_new_translations]:
            try:
                translated = (translate(sub) or "").strip()
            except Exception:
                translated = ""
            # A provider that echoes the source (none configured, refused...)
            # is not a translation.
            if not translated or translated == sub or _NON_LATIN.search(translated):
                continue
            for chapter in owners:
                cache = dict(chapter.title_translations or {})
                cache[lang] = translated
                chapter.title_translations = cache
                out[chapter.id]["title"] = f"{_label(chapter.chapter_number)}: {translated}"
            changed = True
        if changed:
            db.commit()
    return out


__all__ = ["clean_title", "display_titles", "needs_translation", "series_noise"]
