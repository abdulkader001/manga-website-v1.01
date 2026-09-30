"""Workload priority policy (SRS 1C.5.3).

Three levels. High-priority work must not be delayed by a saturated
lower-priority queue: a reader waiting on a translation must never sit behind a
continuously-running scraper batch.

| Priority | Workload                         | Rationale                       |
|----------|----------------------------------|---------------------------------|
| High     | user-requested manga translation | a person is waiting             |
| Medium   | background OCR processing        | pre-processing, no one blocked  |
| Low      | scheduled scraping / catalogue   | can wait; runs continuously     |

The numeric values follow Celery/Redis convention (higher = more urgent). They
are attached to each task family via ``task_routes`` so brokers that honour
message priority schedule high-priority work first. Queue isolation (a dedicated
queue + worker per task type) already prevents cross-type starvation; these
priorities add ordering when work shares a broker/worker.

F-30: that queue-isolation foundation is NOT what the default (non-scale)
``docker-compose.yml`` provides. Its ``celery_worker`` service is a single
container consuming all 8 queues with one shared worker pool
(``CELERY_QUEUES`` lists every queue, ``CELERY_CONCURRENCY: 8``) -- on that
deployment, message ``priority`` only reorders which task a worker picks up
next off one shared connection; it cannot preempt an already-running task or
manufacture a free worker slot, so a saturated pool (e.g. a
``staged_series_rescrape`` occupying a slot for up to its 3600s
``time_limit``) can still make a HIGH-priority translation job wait behind
LOW-priority scrape work despite this module's own priority values. Real
queue isolation, matching what this docstring assumes, is only provided by
``backend_fastapi/deployment/docker-compose.scale.yml``'s per-queue worker services (or an equivalent
k8s deployment) -- these priorities are a genuine anti-starvation mechanism
only there. Confirm which topology a given deployment is actually running
before relying on priority alone to protect a reader-facing workload.
"""

from __future__ import annotations

HIGH = 9
MEDIUM = 5
LOW = 1

# Task family (module prefix) -> priority level.
TASK_PRIORITY: dict[str, int] = {
    "backend_fastapi.app.tasks.translation_tasks": HIGH,
    "backend_fastapi.app.tasks.ocr_tasks": MEDIUM,
    "backend_fastapi.app.tasks.scraper_tasks": LOW,
    # Supporting background work — below user-facing translation, above scraping.
    "backend_fastapi.app.tasks.email_tasks": MEDIUM,
    "backend_fastapi.app.tasks.pdf_tasks": LOW,
    "backend_fastapi.app.tasks.audit_tasks": LOW,
    "backend_fastapi.app.tasks.suggestion_tasks": LOW,
    "backend_fastapi.app.tasks.community_tasks": LOW,
}


def priority_for(task_family: str) -> int:
    """Return the configured priority for a task family (default MEDIUM)."""

    return TASK_PRIORITY.get(task_family, MEDIUM)
