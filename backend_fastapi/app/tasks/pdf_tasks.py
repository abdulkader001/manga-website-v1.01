"""PDF maintenance Celery tasks."""

from __future__ import annotations

from typing import Dict

from ..core.celery_app import celery_app
from ..services import pdf_service


@celery_app.task(name="backend_fastapi.app.tasks.pdf_tasks.daily_integrity_scan")
def daily_integrity_scan() -> Dict[str, object]:
    """Run the PDF integrity checker."""

    return pdf_service.refresh_pdf_integrity()


__all__ = ["daily_integrity_scan"]
