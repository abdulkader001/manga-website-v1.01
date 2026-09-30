"""How a source lays its content out, and how we turn it into vertical chapters.

Some sources publish **one page per chapter** (or a handful); reading those as
hundreds of tiny chapters is unusable. A series can be imported with
``group_size`` = 5 or 10: consecutive source chapters are merged into one
chapter whose pages are all the members' pages, in order.

* Only *full* groups are published. A trailing partial group is held until
  enough chapters exist to fill it, or until the series is completed (then the
  remainder is published as a shorter group), so a group is never rewritten
  after readers have started it.
* A grouped chapter is numbered by its first member and titled with the range
  ("Chapters 6-10"); ``chapter_url`` is the first member's URL and every member
  is kept in ``group_urls`` (with its number) for scraping, new-chapter
  detection and domain remapping.

The layout also carries the settings the page compressor needs to turn
book-format scans into a single vertical flow: ``spread_mode`` (``auto``: cut
images that are clearly two pages side by side; ``always``: every image of
this source is a two-page scan; ``never``: leave images alone) and
``reading_direction`` (which half comes first: ``rtl`` for Japanese-style
manga, ``ltr`` for manhwa/manhua).

Admins can declare a site's structure by hand with ``source_format``:
``vertical`` (normal pages / long strips: nothing is split or merged),
``double`` (book format, two pages per image) and ``single`` (one page per
chapter: chapters are grouped, 10 at a time unless a size is chosen).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

MAX_GROUP_SIZE = 50


def _positive_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


SPREAD_MODES = ("auto", "always", "never")
SOURCE_FORMATS = ("auto", "vertical", "double", "single")
DEFAULT_SINGLE_GROUP = 10


def normalize_layout(raw: Any, *, series_type: Optional[str] = None) -> Dict[str, Any]:
    """Clean a layout dict from user input; unknown keys are dropped.

    ``source_format`` is a shortcut that fills in the other keys (anything set
    explicitly alongside it still wins). The legacy boolean ``split_spreads``
    maps to ``spread_mode`` (true -> auto, false -> never).
    """

    raw = raw if isinstance(raw, dict) else {}
    group = _positive_int(raw.get("group_size"))
    mode = str(raw.get("spread_mode") or "").lower()
    if mode not in SPREAD_MODES:
        mode = ""
        if "split_spreads" in raw:
            mode = "auto" if raw.get("split_spreads") else "never"
    source_format = str(raw.get("source_format") or "").lower()
    if source_format == "vertical" and not mode:
        mode = "never"
    elif source_format == "double" and not mode:
        mode = "always"
    elif source_format == "single" and not group:
        group = DEFAULT_SINGLE_GROUP
    layout: Dict[str, Any] = {}
    if source_format in SOURCE_FORMATS and source_format != "auto":
        layout["source_format"] = source_format
    if group and group > 1:
        layout["group_size"] = min(group, MAX_GROUP_SIZE)
    if mode:
        layout["spread_mode"] = mode
    direction = str(raw.get("reading_direction") or "").lower()
    if direction in {"rtl", "ltr"}:
        layout["reading_direction"] = direction
    return layout


def effective_layout(manga: Any) -> Dict[str, Any]:
    """Layout with defaults filled in: wide two-page scans are split unless
    turned off, and manga read right-to-left while manhwa/manhua read
    left-to-right."""

    stored = normalize_layout(getattr(manga, "scrape_layout", None))
    series_type = str(getattr(manga, "type", "") or "").lower()
    return {
        "group_size": stored.get("group_size", 1),
        "spread_mode": stored.get("spread_mode", "auto"),
        "reading_direction": stored.get(
            "reading_direction", "rtl" if series_type == "manga" else "ltr"
        ),
    }


def member_urls(chapter: Any) -> List[str]:
    """Every source URL a stored chapter covers."""

    urls = [chapter.chapter_url] if getattr(chapter, "chapter_url", None) else []
    for member in getattr(chapter, "group_urls", None) or []:
        url = member.get("url") if isinstance(member, dict) else member
        if url and url not in urls:
            urls.append(url)
    return urls


def known_source_urls(chapters: Iterable[Any]) -> Set[str]:
    known: Set[str] = set()
    for chapter in chapters:
        known.update(member_urls(chapter))
    return known


def _number_text(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else f"{number:g}"


def range_title(first: float, last: float) -> str:
    if first == last:
        return f"Chapter {_number_text(first)}"
    return f"Chapters {_number_text(first)}-{_number_text(last)}"


def build_chapter_rows(
    manga_id: int,
    source_chapters: List[Dict[str, Any]],
    *,
    group_size: int,
    consumed_urls: Set[str],
    flush: bool,
) -> List[Dict[str, Any]]:
    """Chapter rows to insert for the source chapters not yet stored.

    ``consumed_urls`` are the source URLs already stored (as chapters or as
    group members). With ``group_size`` 1 every new source chapter becomes a
    chapter; otherwise consecutive new ones are merged as described above.
    """

    fresh = [
        c
        for c in source_chapters
        if c.get("url") and c["url"] not in consumed_urls
    ]
    if group_size <= 1:
        return [
            {
                "manga_id": manga_id,
                "chapter_number": c.get("number", 0.0),
                "chapter_title": c.get("title", ""),
                "chapter_url": c["url"],
                "ingestion_status": "queued",
            }
            for c in fresh
        ]

    fresh.sort(key=lambda c: (float(c.get("number") or 0.0)))
    rows: List[Dict[str, Any]] = []
    for start in range(0, len(fresh), group_size):
        members = fresh[start : start + group_size]
        if len(members) < group_size and not flush:
            break  # held until the group can be filled
        numbers = [float(m.get("number") or 0.0) for m in members]
        rows.append(
            {
                "manga_id": manga_id,
                "chapter_number": numbers[0],
                "chapter_title": range_title(numbers[0], numbers[-1]),
                "chapter_url": members[0]["url"],
                "group_urls": [
                    {"url": m["url"], "number": n} for m, n in zip(members, numbers)
                ],
                "ingestion_status": "queued",
            }
        )
    return rows


def remap_members(chapter: Any, new_url_by_number: Dict[float, str]) -> bool:
    """After a domain change, point a grouped chapter's members at their new
    URLs (matched by member number). True when anything changed."""

    members = getattr(chapter, "group_urls", None)
    if not members:
        return False
    updated, changed = [], False
    for member in members:
        new_url = new_url_by_number.get(float(member.get("number", 0.0)))
        if new_url and new_url != member.get("url"):
            member = {**member, "url": new_url}
            changed = True
        updated.append(member)
    if changed:
        chapter.group_urls = updated
    return changed
