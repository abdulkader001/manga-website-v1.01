"""Daily health check per source website (roadmap item 11).

Source sites change their markup over time; a parser that used to work then
returns nothing and new chapters silently stop arriving. Once a day this
picks one series for each source host, runs that host's current parser against
it and records the result:

* ``ok``           -- chapters found and the newest chapter shows pictures.
* ``zero_chapters`` / ``zero_pictures`` -- the parser extracts nothing. An
  admin alert is raised and re-detection is tried (known parsers, structure
  detection, then the Scraper AI if a key is configured). A working
  replacement is saved as a *candidate* parser version only -- activating it
  stays an admin decision.
* ``fetch_failed`` -- the site could not be reached. Alerted, but no
  re-detection: the parser is not the evidence of the problem.

The latest result per host lives in the ``settings`` table under
``source_health:<host>`` (JSON), so no schema change is needed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Chapter, Manga
from ..models.settings import Setting

logger = structlog.get_logger(__name__)

KEY_PREFIX = "source_health:"
OK = "ok"
FAILING = ("zero_chapters", "zero_pictures", "fetch_failed")
# Cap per run so a large catalogue with many hosts cannot run for hours.
MAX_HOSTS_PER_RUN = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _host(url: str) -> str:
    from ..scrapers.source_pipeline import host_of

    return host_of(url)


def sample_series_per_host(db: Session) -> Dict[str, Manga]:
    """One series per source host: the one with the most chapters, since a
    series that has chapters is proof the parser once worked on it."""

    counts = dict(
        db.query(Chapter.manga_id, func.count(Chapter.id)).group_by(Chapter.manga_id).all()
    )
    best: Dict[str, Manga] = {}
    for manga in db.query(Manga).filter(Manga.source_url.isnot(None)).all():
        host = _host(manga.source_url)
        if not host:
            continue
        current = best.get(host)
        if current is None or counts.get(manga.id, 0) > counts.get(current.id, 0):
            best[host] = manga
    return best


def probe_host(host: str, series_url: str) -> Dict[str, Any]:
    """Run the host's current parser: ``{"status": ..., "chapters": n, "images": n}``."""

    from ..scrapers.base_scraper import BaseScraper
    from ..scrapers.source_pipeline import _images_on

    scraper = BaseScraper(host)
    try:
        data = scraper.scrape_manga(series_url, None, dry_run=True)
    except Exception as exc:
        return {"status": "fetch_failed", "chapters": 0, "images": 0, "detail": str(exc)[:200]}
    chapters = data.get("chapters") or []
    if not chapters:
        return {"status": "zero_chapters", "chapters": 0, "images": 0}

    chapter_url = chapters[-1]["url"]
    soup = scraper._fetch_html(chapter_url)
    if soup is None:
        return {
            "status": "fetch_failed",
            "chapters": len(chapters),
            "images": 0,
            "detail": "the newest chapter page could not be loaded",
        }
    images = len(_images_on(scraper, soup, chapter_url, scraper.config or {}))
    status = OK if images else "zero_pictures"
    return {"status": status, "chapters": len(chapters), "images": images}


def redetect(db: Session, host: str, series_url: str) -> Dict[str, Any]:
    """Try to write a replacement parser. Never activates it."""

    from ..scrapers import source_pipeline
    from ..scrapers.base_scraper import BaseScraper

    scraper = BaseScraper(host)
    soup = scraper._fetch_html(series_url)
    if soup is None:
        return {"result": "skipped", "detail": "series page could not be loaded"}
    built = source_pipeline.build_parser(db, scraper, series_url, str(soup))
    if not built.get("ok"):
        return {"result": "failed", "detail": built.get("failed_step") or "no parser found"}
    registered = source_pipeline._register(
        db,
        key=source_pipeline.parser_key(db, host),
        definition=built["definition"],
        label=built["label"],
        test_results=built["test_results"],
        actor=None,
        activate=False,
    )
    return {"result": "candidate_ready", "label": built["label"], **registered}


def load(db: Session, host: str) -> Optional[Dict[str, Any]]:
    row = db.query(Setting).filter(Setting.key == KEY_PREFIX + host).first()
    if row is None or not row.value:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


def _save(db: Session, host: str, record: Dict[str, Any]) -> None:
    key = (KEY_PREFIX + host)[:100]
    row = db.query(Setting).filter(Setting.key == key).first()
    payload = json.dumps(record)
    if row is None:
        db.add(Setting(key=key, value=payload))
    else:
        row.value = payload
    db.commit()


def _alert(host: str, record: Dict[str, Any], manga: Manga) -> None:
    from .notification_service import notify_async

    redetect_result = (record.get("redetect") or {}).get("result")
    if redetect_result == "candidate_ready":
        title = f"{host}: parser broke, replacement ready to approve"
        body = (
            f"The parser for {host} stopped working ({record['status']}). A replacement "
            "was found and saved as a candidate parser; review and activate it."
        )
        kind = "parser.candidate_ready"
    else:
        title = f"{host}: parser is not working"
        body = (
            f"The parser for {host} returned {record['status'].replace('_', ' ')} on "
            f"'{manga.title}'. "
            + (
                "No replacement could be found automatically."
                if redetect_result
                else "The site may be down."
            )
        )
        kind = "website.structure_changed" if redetect_result else "parser.needed"
    notify_async(
        type=kind,
        title=title,
        body=body,
        data={"host": host, "status": record["status"], "series_id": manga.id},
        dedup_key=f"source_health:{host}:{record['checked_at'][:10]}",
    )


def check_host(db: Session, host: str, manga: Manga) -> Dict[str, Any]:
    probe = probe_host(host, manga.source_url)
    previous = load(db, host) or {}
    record: Dict[str, Any] = {
        "host": host,
        "status": probe["status"],
        "chapters": probe.get("chapters", 0),
        "images": probe.get("images", 0),
        "detail": probe.get("detail"),
        "checked_at": _now(),
        "last_ok_at": previous.get("last_ok_at"),
        "sample_series_id": manga.id,
        "consecutive_failures": 0,
        "redetect": None,
    }
    if probe["status"] == OK:
        record["last_ok_at"] = record["checked_at"]
    else:
        record["consecutive_failures"] = int(previous.get("consecutive_failures") or 0) + 1
        if probe["status"] in ("zero_chapters", "zero_pictures"):
            try:
                record["redetect"] = redetect(db, host, manga.source_url)
            except Exception as exc:
                logger.warning("source_redetect_failed", host=host, error=str(exc)[:200])
                record["redetect"] = {"result": "failed", "detail": str(exc)[:200]}
        logger.warning(
            "source_health_failing",
            host=host,
            status=probe["status"],
            consecutive_failures=record["consecutive_failures"],
        )
        _alert(host, record, manga)
    _save(db, host, record)
    return record


def run_health_checks(db: Session) -> Dict[str, Any]:
    samples = sample_series_per_host(db)
    summary = {"checked": 0, "failing": 0, "results": {}}
    for host in sorted(samples)[:MAX_HOSTS_PER_RUN]:
        try:
            record = check_host(db, host, samples[host])
        except Exception as exc:  # one broken host must not stop the rest
            logger.exception("source_health_check_error", host=host, error=str(exc)[:200])
            continue
        summary["checked"] += 1
        summary["results"][host] = record["status"]
        if record["status"] != OK:
            summary["failing"] += 1
    return summary


def all_statuses(db: Session) -> List[Dict[str, Any]]:
    rows = db.query(Setting).filter(Setting.key.like(KEY_PREFIX + "%")).all()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row.value or "{}"))
        except ValueError:
            continue
    return sorted(out, key=lambda r: (r.get("status") == OK, r.get("host") or ""))
