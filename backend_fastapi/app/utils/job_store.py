"""Lightweight async-job store for OCR/translation (item 39).

Submit-and-poll pattern: an endpoint enqueues a Celery task and returns a
``job_id`` immediately; the task writes status/result here; a status endpoint
reads it back. Backed by Redis (shared across workers/instances — keeps the app
stateless) with an in-process dict fallback for single-process/dev/test use
(and for Celery eager mode, where the task runs inside the API process).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

import structlog

logger = structlog.get_logger("backend_fastapi.job_store")

JOB_TTL_SECONDS = 3600
_KEY_PREFIX = "job:"

# Process-local fallback; also used in tests (no Redis) and Celery eager mode.
_LOCAL: dict[str, dict[str, Any]] = {}

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = {STATUS_DONE, STATUS_FAILED}


def _redis_client():
    try:
        import redis

        from ..core.celery_app import celery_app

        url = celery_app.conf.broker_url or ""
        if url.startswith(("redis://", "rediss://")):
            return redis.Redis.from_url(url)
    except Exception:  # pragma: no cover - defensive
        return None
    return None


def new_job_id() -> str:
    return uuid.uuid4().hex


def _write(job_id: str, doc: dict[str, Any]) -> None:
    _LOCAL[job_id] = doc
    client = _redis_client()
    if client is not None:
        try:
            client.setex(f"{_KEY_PREFIX}{job_id}", JOB_TTL_SECONDS, json.dumps(doc))
        except Exception:  # pragma: no cover - best effort
            logger.warning("job_store_write_failed", job_id=job_id)


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    client = _redis_client()
    if client is not None:
        try:
            raw = client.get(f"{_KEY_PREFIX}{job_id}")
            if raw:
                return json.loads(raw)
        except Exception:  # pragma: no cover - fall back to local
            pass
    return _LOCAL.get(job_id)


def create_job(
    kind: str, job_id: Optional[str] = None, *, user_id: Optional[int] = None
) -> str:
    job_id = job_id or new_job_id()
    _write(
        job_id,
        {
            "job_id": job_id,
            "kind": kind,
            "status": STATUS_QUEUED,
            "result": None,
            "error": None,
            "created_at": time.time(),
            "user_id": user_id,
        },
    )
    return job_id


def _update(job_id: str, **fields: Any) -> None:
    doc = get_job(job_id) or {"job_id": job_id, "kind": None}
    doc.update(fields)
    doc["updated_at"] = time.time()
    _write(job_id, doc)


def mark_running(job_id: str) -> None:
    _update(job_id, status=STATUS_RUNNING)


def mark_done(job_id: str, result: Any) -> None:
    _update(job_id, status=STATUS_DONE, result=result, error=None)


def mark_failed(job_id: str, error: str) -> None:
    _update(job_id, status=STATUS_FAILED, error=error)
