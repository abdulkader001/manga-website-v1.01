"""Find (or create) a parser that can read a website.

For a series URL the pipeline tries, cheapest and most trustworthy first:

1. the website's approved parser, saved config, or built-in preset;
2. **any known parser** (every built-in preset and every parser approved for
   another domain) against this page -- which is how a site that moved to a
   new domain is recognised without any configuration;
3. structural auto-detection (biggest group of chapter-like links / page
   images), which needs no site knowledge;
4. the scraper-generation AI, refined against real test results.

Whatever works must pass the same test: a real series page yielding a title
and chapters, and two real chapter pages yielding page images. Anything found
in steps 2-4 is registered as a parser *candidate* and activated only when
the requester holds the activate_parser permission. Nothing is invented: when
no step works, the result says why and what is needed.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

import structlog
from sqlalchemy.orm import Session

from ..models import ApprovedSourceDomain, ParserVersion, User
from ..services import (
    parser_generation_service,
    parser_versions_service,
    scraper_ai_service,
)
from . import autodetect, presets
from .base_scraper import BaseScraper

logger = structlog.get_logger(__name__)

PREVIEW_CHAPTERS = 10
AI_ATTEMPTS = 3
Definition = Dict[str, Any]


def host_of(url: str) -> str:
    return (urlparse(url or "").hostname or "").strip().lower()


def origin_of(url: str) -> str:
    parsed = urlparse(url or "")
    return f"{parsed.scheme or 'https'}://{parsed.netloc}/" if parsed.netloc else ""


def parser_key(db: Session, host: str) -> str:
    """The domain a parser is stored under: the approved website's domain that
    covers ``host``, else the host without ``www.``."""

    for entry in db.query(ApprovedSourceDomain).all():
        domain = (entry.domain or "").strip().lower()
        if domain and (host == domain or host.endswith("." + domain)):
            return domain
    return host[4:] if host.startswith("www.") else host


def known_pool(db: Session) -> List[Definition]:
    """Every parser worth trying on an unfamiliar page: built-ins first, then
    whatever the admin has approved for other domains."""

    pool = presets.known_definitions()
    for version in (
        db.query(ParserVersion).filter(ParserVersion.status == "active").all()
    ):
        if isinstance(version.definition, dict) and version.definition not in pool:
            pool.append(version.definition)
    return pool


def _summarise(data: Dict[str, Any]) -> Dict[str, Any]:
    chapters = data.get("chapters") or []
    return {
        "title": data.get("title"),
        "description": data.get("description"),
        "cover": data.get("cover"),
        "authors": data.get("authors") or [],
        "genres": data.get("genres") or [],
        "total_chapters": int(data.get("total_chapters") or len(chapters)),
        "chapters": chapters[-PREVIEW_CHAPTERS:][::-1],
    }


def _try_series(
    scraper: BaseScraper, url: str, definition: Optional[Definition]
) -> Optional[Dict[str, Any]]:
    try:
        data = scraper.scrape_manga(url, None, _ai_config=definition, dry_run=True)
    except Exception as exc:
        logger.info("source_probe_failed", url=url, error=str(exc)[:200])
        return None
    return data if data.get("chapters") else None


def _images_on(scraper: BaseScraper, soup: Any, url: str, definition: Definition) -> List[str]:
    try:
        return scraper._extract_page_images(
            soup, definition.get("page_images"), url, definition
        )
    except Exception:
        return []


def _describe_existing(db: Session, key: str, host: str) -> str:
    if parser_versions_service.active_for(db, key) is not None:
        return "approved parser"
    if presets.preset_for_domain(host) is not None:
        return "built-in preset"
    return "saved parser"


def _hotlink_referer(scraper: BaseScraper, image_url: str, page_url: str) -> Optional[str]:
    """``"page"`` when the image CDN refuses requests without the reader page as
    Referer (hotlink protection), so the reader must load it via our proxy."""

    from .http_client import RequestWrapper

    def fetch(referer: Optional[str]) -> bool:
        headers = {"Accept": "image/*"}
        if referer:
            headers["Referer"] = referer
        try:
            response = RequestWrapper.get(image_url, timeout=15, headers=headers, max_bytes=12 * 1024 * 1024)
        except Exception:
            return False
        content_type = (response.headers.get("Content-Type") or "").lower()
        return response.status_code == 200 and content_type.startswith("image/")

    if fetch(None):
        return None
    return "page" if fetch(page_url) else None


def _series_candidates(
    db: Session, scraper: BaseScraper, url: str, html: str, base_url: Optional[str]
) -> Iterator[Tuple[str, Definition, Optional[Dict[str, Any]]]]:
    """(label, definition, generation test_results) for each way of writing a
    series-page parser, cheapest first. Lazy: the AI is only asked if the
    earlier candidates all failed."""

    known = presets.detect_family(html, "manga", known_pool(db))
    if known:
        yield "known parser", known, None
    structural = autodetect.detect_series_definition(html, url)
    if structural:
        yield "auto-detected structure", structural, None

    if not scraper_ai_service.is_configured():
        return
    feedback: Optional[str] = None
    hints = _series_hints(html, structural)
    for attempt in range(AI_ATTEMPTS):
        selectors = scraper_ai_service.generate_selectors(
            html, "manga", feedback=feedback, hints=hints
        )
        if not selectors:
            return
        test = parser_generation_service._test_series_selectors(html, selectors)
        if test["passed"]:
            yield "AI-generated parser", selectors, {"attempt": attempt + 1, "series_page": test}
            return
        feedback = _series_feedback(selectors, test)


def _series_hints(html: str, structural: Optional[Definition]) -> str:
    lines = []
    if structural:
        lines.append(
            "A structural analysis found the chapter links with the selector "
            f"{structural['chapter_list']!r} and the title with {structural['manga_title']!r}; "
            "prefer these unless the HTML clearly shows better ones."
        )
    return "\n".join(lines)


def _series_feedback(selectors: Definition, test: Dict[str, Any]) -> str:
    problems = []
    if not test.get("title"):
        problems.append(
            f"manga_title {selectors.get('manga_title')!r} matched no non-empty element"
        )
    if not test.get("chapter_urls"):
        problems.append(
            f"chapter_list {selectors.get('chapter_list')!r} with chapter_url "
            f"{selectors.get('chapter_url', 'a')!r} produced no chapter links "
            f"({test.get('chapter_count', 0)} list elements matched)"
        )
    return (
        "Your previous selectors failed when tested on this exact page: "
        + "; ".join(problems)
        + ". Return corrected selectors as JSON."
    )


def _reader_candidates(
    db: Session, scraper: BaseScraper, series_def: Definition, chapter_url: str, html: str
) -> Iterator[Tuple[str, Definition]]:
    if series_def.get("page_images") or series_def.get("image_source"):
        yield "series parser", {
            k: series_def[k] for k in ("page_images", "image_source", "image_attr") if k in series_def
        }
    known = presets.detect_family(html, "chapter", known_pool(db))
    if known:
        yield "known parser", {k: known[k] for k in ("page_images", "image_source", "image_attr") if k in known}
    structural = autodetect.detect_reader_definition(html, chapter_url)
    if structural:
        yield "auto-detected structure", structural

    if not scraper_ai_service.is_configured():
        return
    feedback: Optional[str] = None
    for _attempt in range(AI_ATTEMPTS):
        selectors = scraper_ai_service.generate_selectors(html, "chapter", feedback=feedback)
        if not selectors:
            return
        yield "AI-generated parser", selectors
        feedback = (
            f"page_images {selectors.get('page_images')!r} matched no images on this page. "
            "Return a corrected selector as JSON."
        )


def build_parser(
    db: Session,
    scraper: BaseScraper,
    series_url: str,
    series_html: str,
    *,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble and test a full definition (series page + reader page)."""

    for label, series_def, gen_results in _series_candidates(
        db, scraper, series_url, series_html, base_url
    ):
        data = _try_series(scraper, series_url, series_def)
        if not data:
            continue
        chapter_urls = [c["url"] for c in data["chapters"]]
        # Newest and an older chapter, so a layout that changed over time
        # is caught.
        samples = list(dict.fromkeys([chapter_urls[-1], chapter_urls[len(chapter_urls) // 2]]))[:2]
        soups = []
        for chapter_url in samples:
            soup = scraper._fetch_html(chapter_url)
            if soup is None:
                return _failure("fetch_chapter_page")
            soups.append((chapter_url, soup))
        first_url, first_soup = soups[0]
        for reader_label, reader_def in _reader_candidates(
            db, scraper, series_def, first_url, str(first_soup)
        ):
            merged = {**series_def, **reader_def}
            counts = [len(_images_on(scraper, soup, url, merged)) for url, soup in soups]
            if all(counts):
                sample_image = _images_on(scraper, first_soup, first_url, merged)[0]
                referer = _hotlink_referer(scraper, sample_image, first_url)
                if referer:
                    merged["image_referer"] = referer
                return {
                    "ok": True,
                    "definition": merged,
                    "series": data,
                    "label": label if label == reader_label else f"{label} + {reader_label}",
                    "test_results": {
                        "series_page": {
                            "url": series_url,
                            "title": data.get("title"),
                            "chapter_count": data.get("total_chapters"),
                            "passed": True,
                            "generation": gen_results,
                        },
                        "chapter_pages": [
                            {"url": url, "image_count": count, "passed": True}
                            for (url, _), count in zip(soups, counts)
                        ],
                    },
                }
        return _failure("test_chapter_pages")
    return _failure("test_series_page")


def _failure(step: str) -> Dict[str, Any]:
    report = scraper_ai_service.honest_failure_report("")
    report["ok"] = False
    report["failed_step"] = step
    return report


def _register(
    db: Session,
    *,
    key: str,
    definition: Definition,
    label: str,
    test_results: Dict[str, Any],
    actor: Optional[User],
    activate: bool,
) -> Dict[str, Any]:
    source = "ai_generated" if "AI" in label else "rules"
    existing = next(
        (
            v
            for v in parser_versions_service.list_for(db, key)
            if v.definition == definition and v.status in ("candidate", "active")
        ),
        None,
    )
    version = existing or parser_versions_service.create_candidate(
        db,
        domain=key,
        definition=definition,
        source=source,
        created_by=actor.id if actor else None,
        test_results=test_results,
        notes=f"Found by the source pipeline ({label}).",
    )
    activated = version.status == "active"
    if activate and not activated and actor is not None:
        from ..services.permissions_service import has_permission

        if has_permission(db, actor, "activate_parser"):
            parser_versions_service.activate(db, version.id, actor_id=actor.id)
            activated = True
    db.commit()
    return {"version_id": version.id, "version": version.version, "activated": activated}


def resolve_parser(
    db: Session,
    series_url: str,
    *,
    base_url: Optional[str] = None,
    actor: Optional[User] = None,
    activate: bool = False,
) -> Dict[str, Any]:
    """Probe ``series_url`` and return

    ``{"ok": True, "parser": {...}, "series": {...}}`` or
    ``{"ok": False, "reason": ..., "message": ..., "required_inputs": [...]}``.
    """

    host = host_of(series_url)
    if not host:
        return {"ok": False, "reason": "invalid_url", "message": "The series URL is not valid."}

    blocked = presets.unsupported_reason(host)
    if blocked:
        return {
            "ok": False,
            "reason": "unsupported_site",
            "message": (
                f"{host} cannot be scraped: it {blocked}. Its chapters cannot be read "
                "by fetching pages, so no parser can be written for it."
            ),
        }

    key = parser_key(db, host)
    scraper = BaseScraper(host)

    # 1. The parser this domain already has (approved, saved, or preset).
    if scraper.config:
        data = _try_series(scraper, series_url, None)
        if data:
            return {
                "ok": True,
                "parser": {"source": _describe_existing(db, key, host), "domain": key},
                "series": _summarise(data),
            }

    soup = scraper._fetch_html(series_url)
    if soup is None:
        return {
            "ok": False,
            "reason": "fetch_failed",
            "message": (
                "The source page could not be loaded (blocked, offline, or not a public "
                "address). Check the series URL."
            ),
        }

    # 2-4. Known parsers on this page, structure detection, AI.
    built = build_parser(db, scraper, series_url, str(soup), base_url=base_url)
    if built.get("ok"):
        registered = _register(
            db,
            key=key,
            definition=built["definition"],
            label=built["label"],
            test_results=built["test_results"],
            actor=actor,
            activate=activate,
        )
        return {
            "ok": True,
            "parser": {"source": built["label"], "domain": key, **registered},
            "series": _summarise(built["series"]),
        }

    built["reason"] = "no_parser"
    if not scraper_ai_service.is_configured():
        built["message"] = (
            "Structure analysis could not read this website, and no Scraper AI key is "
            "configured. Add one in Scraper AI API so a parser can be generated."
        )
    return built


# ---------------------------------------------------------------------------
# Background admin tasks (run by the Celery worker via tasks.scraper_tasks)
# ---------------------------------------------------------------------------


def _chapter_rows(series: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"number": c.get("number"), "title": c.get("title"), "url": c.get("url")}
        for c in series.get("chapters") or []
    ]


def sample_layout(
    series_url: str, chapters: List[Dict[str, Any]], total: int = 0
) -> Optional[Dict[str, Any]]:
    """Look at a few real chapters and say how the source lays its content out.

    Samples the first, middle and last chapter: how many pages each has, and
    whether the first picture is a wide two-page scan. Best effort -- any
    failure just means no hint, never a failed preview.
    """

    from ..services import page_image_service
    from .base_scraper import BaseScraper

    rows = sorted(
        (c for c in chapters if c.get("url")), key=lambda c: float(c.get("number") or 0.0)
    )
    if len(rows) < 2:
        return None
    picks = list({rows[0]["url"]: rows[0], rows[len(rows) // 2]["url"]: rows[len(rows) // 2],
                  rows[-1]["url"]: rows[-1]}.values())
    scraper = BaseScraper(host_of(series_url))
    counts: List[int] = []
    first_pages: List[str] = []
    for row in picks:
        try:
            pages = scraper.scrape_chapter(row["url"]).get("pages") or []
        except Exception as exc:
            logger.info("layout_sample_chapter_failed", url=row["url"], error=str(exc)[:160])
            continue
        counts.append(len(pages))
        if pages:
            first_pages.append((row["url"], pages[0]))
    if not counts:
        return None

    hint: Dict[str, Any] = {"sample_page_counts": counts, "suggested_group_size": None,
                            "suggested_source_format": None, "message": ""}
    total = max(total, len(rows))
    if total >= 6 and max(counts) <= 1:
        hint.update(
            suggested_group_size=10,
            suggested_source_format="single",
            message="Each chapter has a single page. Group them (10 per chapter) so it reads as a long vertical chapter.",
        )
    elif total >= 6 and max(counts) <= 3 and sum(counts) / len(counts) <= 2.5:
        hint.update(
            suggested_group_size=5,
            suggested_source_format="single",
            message="Chapters have only a few pages each. Grouping 5 per chapter is recommended.",
        )
    if first_pages:
        chapter_url, image_url = first_pages[0]
        try:
            from io import BytesIO

            from PIL import Image

            referer, headers = page_image_service.referer_for_chapter(chapter_url)
            width, height = Image.open(BytesIO(page_image_service._download(image_url, referer, headers))).size
            if height and width / height >= page_image_service.SPREAD_MIN_ASPECT:
                hint["suggested_source_format"] = "double"
                hint["message"] = (hint["message"] + " " if hint["message"] else "") + (
                    "Pictures are wide two-page (book format) scans; they will be split into single vertical pages."
                )
        except Exception:
            pass
    return hint


def run_preview(db: Session, payload: Dict[str, Any], actor: Optional[User]) -> Dict[str, Any]:
    """Series import preview: MangaUpdates metadata + the chapters the source
    site really has, exactly as an import would ingest them."""

    from ..services import mangaupdates_service

    series_url = str(payload.get("url") or "").strip()
    mu_url = str(payload.get("mangaupdates_url") or "").strip()
    warnings: List[str] = []
    metadata: Optional[mangaupdates_service.SeriesMetadata] = None

    if mu_url:
        try:
            metadata = mangaupdates_service.fetch_series(mu_url)
        except mangaupdates_service.MangaUpdatesError as exc:
            warnings.append(f"MangaUpdates: {exc}")

    source: Optional[Dict[str, Any]] = None
    if series_url:
        source = resolve_parser(
            db,
            series_url,
            base_url=str(payload.get("base_url") or "") or None,
            actor=actor,
            activate=True,
        )
        if not source.get("ok"):
            warnings.append(source.get("message") or "The source site could not be read.")

    if metadata is None and not (source and source.get("ok")):
        return {
            "ok": False,
            "message": " ".join(warnings) or "Enter a MangaUpdates link and a source series URL.",
            "warnings": warnings,
            "source": {k: v for k, v in (source or {}).items() if k != "series"},
        }

    series = (source or {}).get("series") or {}
    meta = metadata.to_dict() if metadata else {}
    total = int(series.get("total_chapters") or 0)
    preview = {
        "title": meta.get("title") or series.get("title") or "",
        "alt_titles": meta.get("alt_titles") or [],
        "description": meta.get("description") or series.get("description") or "",
        "author": ", ".join(meta.get("authors") or series.get("authors") or []),
        "artist": ", ".join(meta.get("artists") or []),
        "genres": meta.get("genres") or series.get("genres") or [],
        "categories": meta.get("categories") or [],
        "tags": meta.get("categories") or [],
        "status": meta.get("status") or "ongoing",
        "type": meta.get("type"),
        "coverImage": meta.get("cover_url") or series.get("cover") or "",
        "cover_url": meta.get("cover_url") or series.get("cover") or "",
        "mangaupdates_url": mu_url,
        "source_url": series_url,
        "chapters": _chapter_rows(series),
        "detectedChapterCount": total,
        "parser": (source or {}).get("parser"),
    }
    if source and source.get("ok"):
        try:
            hint = sample_layout(series_url, series.get("chapters") or [], total)
        except Exception as exc:
            logger.info("layout_sample_failed", url=series_url, error=str(exc)[:160])
            hint = None
        if hint:
            preview["layout_hint"] = hint
    return {"ok": True, "preview": preview, "warnings": warnings}


def run_generate_parser(db: Session, payload: Dict[str, Any], actor: Optional[User]) -> Dict[str, Any]:
    """Custom parser for a website: given a series URL (best) or the site's
    homepage, work out and test a parser, approve the website for the admin
    who may, and report exactly what was found."""

    from ..services import series_import

    raw = str(payload.get("url") or "").strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if not parsed.netloc:
        return {"ok": False, "message": "Enter the website's address, for example https://example-manga.com/series/some-title."}
    url = parsed.geturl()
    base = origin_of(url)

    series_url = url
    if parsed.path in {"", "/"}:
        # Homepage: find a real series page to learn from.
        listing = parser_generation_service._fetch_html(url)
        if not listing:
            return {"ok": False, "message": "The website's homepage could not be loaded."}
        links = parser_generation_service._find_series_links(url, listing)
        if not links:
            report = scraper_ai_service.honest_failure_report(parsed.netloc)
            report["ok"] = False
            report["message"] = (
                "No series page could be found from the homepage. Paste the address of one "
                "series page on this website instead."
            )
            return report
        series_url = links[0]

    result = resolve_parser(db, series_url, base_url=base, actor=actor, activate=True)
    if not result.get("ok"):
        return result

    approved = False
    if actor is not None:
        try:
            series_import.ensure_website_approved(
                db, actor, series_url, base_url=base, can_approve=None
            )
            approved = True
        except Exception:
            approved = series_import.is_approved(db, series_url)
    series = result["series"]
    return {
        "ok": True,
        "domain": host_of(series_url),
        "series_url": series_url,
        "parser": result["parser"],
        "approved": approved,
        "sample": {
            "title": series.get("title"),
            "chapters_found": series.get("total_chapters"),
            "chapters": series.get("chapters"),
        },
        "message": (
            f"Parser ready for {host_of(series_url)}: found {series.get('total_chapters')} "
            f"chapters on the sample series ({result['parser'].get('source')})."
        ),
    }


def run_task(db: Session, kind: str, payload: Dict[str, Any], actor: Optional[User]) -> Dict[str, Any]:
    if kind == "preview":
        return run_preview(db, payload, actor)
    if kind == "parser":
        return run_generate_parser(db, payload, actor)
    return {"ok": False, "message": f"Unknown task kind {kind!r}."}
