"""Async OCR-overlay translation Celery tasks (item 39).

Translates a set of already-extracted overlay text boxes in the background
(useful with the app's client-side OCR mode), returning positioned/translated
boxes via the job store. Routed to the ``ocr`` queue. The synchronous
``/ocr/translate-overlay`` endpoint (which also fetches + OCRs an image) is
unchanged; this is the additive submit-and-poll path for the translation step.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from ..core.celery_app import celery_app
from ..services.ocr_workflow import translate_overlay_items
from ..tasks.translation_tasks import _build_service
from ..utils import job_store

logger = structlog.get_logger(__name__)


@celery_app.task(
    bind=True,
    name="backend_fastapi.app.tasks.ocr_tasks.translate_overlay_job",
    max_retries=2,
)
def translate_overlay_job(
    self,
    job_id: str,
    items: List[Dict[str, Any]],
    page: Dict[str, Any],
    target_lang: str,
    source_lang: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    job_store.mark_running(job_id)
    try:
        service = _build_service(provider_config)
        boxes, metadata, errors = translate_overlay_items(
            items,
            page,
            {},
            translation_service=service,
            provider_config=provider_config,
            target_lang=target_lang,
            source_lang=source_lang,
        )
        job_store.mark_done(
            job_id, {"boxes": boxes, "metadata": metadata, "errors": errors}
        )
        return {"status": job_store.STATUS_DONE}
    except Exception as exc:
        logger.exception("translate_overlay_job failed", job_id=job_id)
        job_store.mark_failed(job_id, str(exc))
        raise
