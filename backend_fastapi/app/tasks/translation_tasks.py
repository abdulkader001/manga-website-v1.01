"""Async translation Celery tasks (item 39).

Runs the same translation work as the synchronous ``/translation/text`` endpoint
but as a background job so the HTTP request returns immediately with a job id.
Routed to the ``translation`` queue (see celery_app task_routes).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from ..core.celery_app import celery_app
from ..services.translation_service import TranslationService
from ..utils import job_store

logger = structlog.get_logger(__name__)


def _build_service(config: Optional[Dict[str, Any]]) -> TranslationService | None:
    """Build a TranslationService from a provider config (mirrors the router)."""

    if not config or not config.get("api_url"):
        return None
    return TranslationService(
        default_api_url=config["api_url"],
        default_api_key=config.get("api_key"),
        default_provider_config=config,
    )


@celery_app.task(
    bind=True,
    name="backend_fastapi.app.tasks.translation_tasks.translate_text_job",
    max_retries=2,
)
def translate_text_job(
    self,
    job_id: str,
    text: str,
    source_lang: str,
    target_lang: str,
    provider_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    job_store.mark_running(job_id)
    try:
        service = _build_service(provider_config)
        if service is None:
            job_store.mark_failed(job_id, "translation_unavailable")
            return {"status": job_store.STATUS_FAILED}
        translated = service.translate(
            text, source_lang, target_lang, provider_config=provider_config
        )
        job_store.mark_done(job_id, {"translated": translated})
        return {"status": job_store.STATUS_DONE}
    except Exception as exc:
        logger.exception("translate_text_job failed", job_id=job_id)
        job_store.mark_failed(job_id, str(exc))
        raise
