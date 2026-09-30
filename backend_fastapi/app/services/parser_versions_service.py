"""Parser versioning and approval lifecycle (SRS 1G.8.3, 1G.8.4, 1G.8.5).

Every parser — AI-generated, manually written, or rule-based (1G.11) — enters
as a *candidate* and only becomes active through explicit Permanent
Administrator approval (enforced at the API layer). Exactly one version per
website is active at a time; prior versions are retired, not deleted, so a bad
repair can be rolled back in one action.

Activation also publishes the definition to the runtime scraper config
(``ConfigManager``), which is what ``BaseScraper`` executes — so approving a
version is what actually changes scraping behaviour, and nothing else does.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models import ParserVersion


def _next_version(db: Session, domain: str) -> int:
    latest = (
        db.query(ParserVersion.version)
        .filter(ParserVersion.domain == domain)
        .order_by(ParserVersion.version.desc())
        .first()
    )
    return (latest[0] + 1) if latest else 1


def active_for(db: Session, domain: str) -> Optional[ParserVersion]:
    return (
        db.query(ParserVersion)
        .filter(ParserVersion.domain == domain, ParserVersion.status == "active")
        .first()
    )


def list_for(db: Session, domain: str) -> list[ParserVersion]:
    return (
        db.query(ParserVersion)
        .filter(ParserVersion.domain == domain)
        .order_by(ParserVersion.version.desc())
        .all()
    )


def create_candidate(
    db: Session,
    *,
    domain: str,
    definition: dict,
    source: str = "manual",
    created_by: Optional[int] = None,
    test_results: Optional[dict] = None,
    notes: Optional[str] = None,
) -> ParserVersion:
    """Register a new parser candidate (1G.8.3: a candidate, not a deployment)."""

    domain = (domain or "").strip().lower()
    if not domain:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "domain is required", field="domain"
        )
    if source not in ("ai_generated", "manual", "rules"):
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "source must be ai_generated, manual, or rules",
            field="source",
        )
    if not isinstance(definition, dict) or not definition:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "definition must be a non-empty object of extraction rules",
            field="definition",
        )

    candidate = ParserVersion(
        domain=domain,
        version=_next_version(db, domain),
        status="candidate",
        source=source,
        definition=definition,
        test_results=test_results,
        notes=notes,
        created_by=created_by,
    )
    db.add(candidate)
    db.flush()
    return candidate


def _publish_definition(domain: str, definition: dict) -> None:
    from ..scrapers.config import ConfigManager

    ConfigManager.save_config(domain, definition)


def activate(db: Session, version_id: int, *, actor_id: int) -> ParserVersion:
    """Approve and activate a candidate or retired version (PA only, 1G.8.3).

    The previously active version (if any) is retired, never overwritten
    (1G.8.5). Publishing to the runtime config happens last, after the DB
    state is consistent.
    """

    version = db.get(ParserVersion, version_id)
    if version is None:
        raise ApiError(
            ErrorCode.NOT_FOUND, "Parser version not found", field="version_id"
        )
    if version.status == "active":
        return version
    if version.status == "rejected":
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "A rejected parser version cannot be activated; submit a new candidate.",
            field="version_id",
        )

    current = active_for(db, version.domain)
    if current is not None and current.id != version.id:
        current.status = "retired"

    version.status = "active"
    version.approved_by = actor_id
    version.approved_at = datetime.utcnow()
    db.commit()

    _publish_definition(version.domain, version.definition or {})
    return version


def reject(db: Session, version_id: int, *, actor_id: int) -> ParserVersion:
    version = db.get(ParserVersion, version_id)
    if version is None:
        raise ApiError(
            ErrorCode.NOT_FOUND, "Parser version not found", field="version_id"
        )
    if version.status == "active":
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Cannot reject the active version; roll back to a prior version instead.",
            field="version_id",
        )
    version.status = "rejected"
    version.approved_by = actor_id
    db.commit()
    return version


def rollback(db: Session, domain: str, *, actor_id: int) -> ParserVersion:
    """One-action rollback to the most recent retired version (1G.8.5)."""

    domain = (domain or "").strip().lower()
    previous = (
        db.query(ParserVersion)
        .filter(ParserVersion.domain == domain, ParserVersion.status == "retired")
        .order_by(ParserVersion.version.desc())
        .first()
    )
    if previous is None:
        raise ApiError(
            ErrorCode.NOT_FOUND,
            f"No prior parser version to roll back to for '{domain}'.",
            field="domain",
        )
    return activate(db, previous.id, actor_id=actor_id)
