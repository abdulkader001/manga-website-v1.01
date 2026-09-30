"""Simple echo task for diagnostics."""

from __future__ import annotations

from datetime import datetime
from typing import Dict

from ..core.celery_app import celery_app


@celery_app.task(name="backend_fastapi.app.tasks.echo.echo")
def echo(message: str) -> Dict[str, str]:
    """Echo the provided message with a timestamp."""

    return {"message": message, "queued_at": datetime.utcnow().isoformat()}


__all__ = ["echo"]
