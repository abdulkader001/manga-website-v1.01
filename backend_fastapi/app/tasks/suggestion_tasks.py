"""Suggestion generation Celery tasks."""

from __future__ import annotations

import structlog
from typing import Dict, List, Optional

from ..core.celery_app import celery_app
from ..services import suggestion_service

logger = structlog.get_logger(__name__)


@celery_app.task(
    name="backend_fastapi.app.tasks.suggestion_tasks.generate_user_suggestions"
)
def generate_user_suggestions(user_id: int, limit: int = 10) -> List[Dict]:
    """Generate user-specific manga suggestions."""

    service = suggestion_service.SuggestionsService()
    return service.get_recommendations(user_id, limit)


@celery_app.task(name="backend_fastapi.app.tasks.suggestion_tasks.scan")
def scan(limit: Optional[int] = None) -> Dict[str, object]:
    """Placeholder hourly scan for suggestion housekeeping."""

    logger.info("Suggestion scan triggered - no-op implementation")
    return {"status": "noop", "limit": limit}


__all__ = ["generate_user_suggestions", "scan"]
