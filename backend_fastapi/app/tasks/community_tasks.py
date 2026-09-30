"""Community moderation maintenance Celery tasks (SRS Part 3 / 1F.4.1)."""

from __future__ import annotations

import structlog

from ..core.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="backend_fastapi.app.tasks.community_tasks.prune_resolved_reports"
)
def prune_resolved_reports() -> dict:
    """F-28: resolved content reports never expired -- delete ones past
    their retention window so the queue table doesn't grow unbounded."""

    from ..core.db import SessionLocal
    from ..services import comment_service

    db = SessionLocal()
    try:
        deleted = comment_service.prune_resolved_reports(db)
        logger.info("content_reports_pruned", deleted=deleted)
        return {"deleted": deleted}
    finally:
        db.close()


__all__ = ["prune_resolved_reports"]
