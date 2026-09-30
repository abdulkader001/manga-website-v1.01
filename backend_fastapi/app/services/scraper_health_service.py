"""Per-website scraper health + structure-change detection (SRS 1G.7.5/1G.7.8).

Health state is persisted per domain (one ``Setting`` row per website — no
shared mutable state between scrapers, 1G.7.2) and drives the degraded ->
confirmation -> failing progression:

    healthy --(DEGRADE_AFTER consecutive failures)--> degraded
    degraded --(any success)--> healthy         (transient blip, logged)
    degraded --(FAIL_AFTER consecutive failures)--> failing
    failing  --> website auto-disabled, PA alerted with the evidence,
                 ingestion halted for THIS website only (1G.7.7)

Existing ingested data is never touched — series and chapters from a broken
website remain readable; only new ingestion stops.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

import structlog
from sqlalchemy.orm import Session

from ..models import ApprovedSourceDomain, Setting

logger = structlog.get_logger(__name__)

# Consecutive-failure thresholds for the 1G.7.8 progression. Degrading too
# eagerly would page the PA on every network blip; these mirror common
# monitoring defaults (3 strikes to suspect, 6 to confirm).
DEGRADE_AFTER = 3
FAIL_AFTER = 6

_KEY_PREFIX = "scraper_health_"


def _load(db: Session, domain: str) -> Dict[str, Any]:
    row = db.query(Setting).filter(Setting.key == _KEY_PREFIX + domain).first()
    if row is None or not row.value:
        return {
            "consecutive_failures": 0,
            "success_count": 0,
            "failure_count": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "state": "healthy",
        }
    try:
        return json.loads(row.value)
    except ValueError:
        return {"consecutive_failures": 0, "state": "healthy"}


def _save(db: Session, domain: str, health: Dict[str, Any]) -> None:
    key = _KEY_PREFIX + domain
    row = db.query(Setting).filter(Setting.key == key).first()
    payload = json.dumps(health)
    if row is None:
        db.add(Setting(key=key, value=payload))
    else:
        row.value = payload


def _website(db: Session, domain: str) -> Optional[ApprovedSourceDomain]:
    hostname = (domain or "").strip().lower()
    for entry in db.query(ApprovedSourceDomain).all():
        entry_domain = (entry.domain or "").strip().lower()
        if not entry_domain:
            continue
        if hostname == entry_domain or hostname.endswith("." + entry_domain):
            return entry
    return None


def health_for(db: Session, domain: str) -> Dict[str, Any]:
    return _load(db, (domain or "").strip().lower())


def record_success(db: Session, domain: str) -> None:
    """A successful extraction: recover degraded websites (transient blip)."""

    domain = (domain or "").strip().lower()
    health = _load(db, domain)
    was = health.get("state", "healthy")
    health["consecutive_failures"] = 0
    health["success_count"] = int(health.get("success_count") or 0) + 1
    health["last_success_at"] = datetime.utcnow().isoformat()
    health["state"] = "healthy"
    _save(db, domain, health)

    website = _website(db, domain)
    if website is not None:
        website.last_health_check = datetime.utcnow()
        if was in ("degraded",) and (website.status or "active") == "degraded":
            # 1G.7.8: transient / recovered -> back to healthy, log the blip.
            website.status = "active"
            logger.info("scraper_recovered", domain=domain)
    db.commit()


def record_failure(db: Session, domain: str, exc: Exception) -> str:
    """A failed extraction: advance the degraded -> failing progression.

    Returns the resulting health state. On the transition to ``failing`` the
    website is auto-disabled (halting ingestion for that website ONLY) and the
    Permanent Administrator is alerted with the failing step, the selector
    that stopped matching, and the error evidence.
    """

    from ..scrapers.errors import error_details_for

    domain = (domain or "").strip().lower()
    health = _load(db, domain)
    details = error_details_for(exc)

    health["consecutive_failures"] = int(health.get("consecutive_failures") or 0) + 1
    health["failure_count"] = int(health.get("failure_count") or 0) + 1
    health["last_failure_at"] = datetime.utcnow().isoformat()
    health["last_error"] = details
    failures = health["consecutive_failures"]

    website = _website(db, domain)
    previous_state = health.get("state", "healthy")

    if failures >= FAIL_AFTER:
        health["state"] = "failing"
    elif failures >= DEGRADE_AFTER:
        health["state"] = "degraded"

    _save(db, domain, health)

    if website is not None:
        website.last_health_check = datetime.utcnow()
        current = website.status or "active"
        if health["state"] == "degraded" and current == "active":
            # Suspicion, not verdict (1G.7.8): degraded still accepts
            # submissions; it is flagged for attention.
            website.status = "degraded"
            logger.warning(
                "scraper_degraded", domain=domain, consecutive_failures=failures
            )
        elif health["state"] == "failing" and current in ("active", "degraded"):
            # Confirmed: halt ingestion for THIS website only (1G.7.7) and
            # alert the PA with the evidence. No data is deleted.
            website.status = "disabled"
            from .notification_service import notify_async

            notify_async(
                type="website.structure_changed",
                title=f"{domain}: parser failing — ingestion halted",
                body=(
                    f"Repeated extraction failures confirmed for {domain} "
                    f"({failures} consecutive). Failing step: "
                    f"{details.get('missing_field') or 'unknown'}; selector: "
                    f"{details.get('selector_used') or 'n/a'}; module: "
                    f"{details.get('scraper_module') or 'n/a'}; last error: "
                    f"{details.get('message')}. Ingestion for this website "
                    "is halted (all other websites continue). Existing "
                    "series remain readable. Use the Repair action to "
                    "regenerate or supply a new parser."
                ),
                data={"domain": domain, "evidence": details},
                target_type="website",
                target_id=domain,
                dedup_key=f"structure_changed:{domain}",
            )
            logger.error(
                "scraper_failing_disabled",
                domain=domain,
                consecutive_failures=failures,
            )

    db.commit()
    if previous_state != health["state"]:
        logger.info(
            "scraper_health_transition",
            domain=domain,
            from_state=previous_state,
            to_state=health["state"],
        )
    return health["state"]


def is_halted(db: Session, domain: str) -> bool:
    """True when ingestion for this website is halted (disabled)."""

    website = _website(db, (domain or "").strip().lower())
    if website is None:
        return False
    return (website.status or "active") == "disabled"


def dashboard(db: Session) -> list[dict]:
    """Website & Source Management rows (1G.8.6): per-site status, parser
    version, last OK, and whether Repair is needed."""

    from . import parser_versions_service

    out: list[dict] = []
    for entry in (
        db.query(ApprovedSourceDomain).order_by(ApprovedSourceDomain.domain).all()
    ):
        health = _load(db, entry.domain)
        active = parser_versions_service.active_for(db, entry.domain)
        out.append(
            {
                "domain": entry.domain,
                "website_status": entry.status or "active",
                "health_state": health.get("state", "healthy"),
                "parser_version": active.version if active else None,
                "parser_module": active.module_id if active else None,
                "last_success_at": health.get("last_success_at"),
                "consecutive_failures": health.get("consecutive_failures", 0),
                "last_error": health.get("last_error"),
                "action": (
                    "repair"
                    if health.get("state") == "failing"
                    else "inspect"
                    if health.get("state") == "degraded"
                    else None
                ),
            }
        )
    return out
