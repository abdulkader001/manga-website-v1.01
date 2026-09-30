from __future__ import annotations

import os
from urllib.parse import urlparse, urlunparse

import structlog
from celery import Celery, Task
from celery.signals import task_failure, worker_process_init

from .settings import settings
from ..tasks._instrumentation import (
    attach_request_id_to_publish_options,
    before_task_start,
    log_task_failure,
    log_task_success,
    strip_internal_context_kwargs,
)
from ..utils.structured_logging import clear_request_context


def _build_redis_url(default_url: str) -> str:
    parsed = urlparse(default_url)
    default_db = parsed.path.lstrip("/") or "0"
    password = getattr(settings, "redis_password", None) or os.getenv("REDIS_PASSWORD")
    if not password:
        return default_url

    username = (
        getattr(settings, "redis_username", None) or os.getenv("REDIS_USERNAME") or ""
    )
    netloc = parsed.netloc
    if "@" in netloc:
        host_port = netloc.split("@", 1)[1]
    else:
        host_port = netloc or "redis:6379"
    auth = f"{username}:{password}" if username else f":{password}"
    rebuilt = parsed._replace(netloc=f"{auth}@{host_port}", path=f"/{default_db}")
    return urlunparse(rebuilt)


def _setting(name: str, default: str | None = None) -> str | None:
    """Return a setting value allowing for camel/upper variants and fallbacks."""

    lower_name = name.lower()

    direct = getattr(settings, name, None) or getattr(settings, lower_name, None)
    if direct:
        return direct

    env_value = os.getenv(name.upper())
    if env_value:
        return env_value

    if lower_name == "celery_broker_url":
        redis_url = getattr(settings, "redis_url", None) or os.getenv("REDIS_URL")
        if redis_url:
            return redis_url
        broker_url = os.getenv("CELERY_BROKER_URL") or default
        if broker_url:
            return _build_redis_url(broker_url)
        return broker_url

    if lower_name == "celery_result_backend":
        explicit_backend = getattr(settings, "celery_result_backend", None)
        if explicit_backend:
            return explicit_backend
        env_backend = os.getenv("CELERY_RESULT_BACKEND")
        if env_backend:
            return env_backend
        redis_url = getattr(settings, "redis_url", None) or os.getenv("REDIS_URL")
        if redis_url:
            return redis_url
        backend_default = default
        if backend_default:
            return _build_redis_url(backend_default)
        return backend_default

    return default


class StructuredLoggingTask(Task):
    """Custom base task that ensures proper logging and context injection."""

    def __call__(self, *args, **kwargs):
        started_at, request_id = before_task_start(self, kwargs)
        safe_kwargs = strip_internal_context_kwargs(self, kwargs)
        try:
            result = super().__call__(*args, **safe_kwargs)
            log_task_success(self, started_at, request_id=request_id)
            return result
        except Exception as exc:
            log_task_failure(self, started_at, exc, request_id=request_id)
            raise
        finally:
            clear_request_context()

    def apply_async(self, args=None, kwargs=None, **options):
        options = attach_request_id_to_publish_options(options)
        return super().apply_async(args, kwargs, **options)


celery_app = Celery(
    "backend_fastapi",
    broker=_setting("celery_broker_url", "redis://localhost:6379/1"),
    backend=_setting("celery_result_backend", "redis://localhost:6379/2"),
    task_cls=StructuredLoggingTask,
    include=[
        "backend_fastapi.app.tasks.echo",
        "backend_fastapi.app.tasks.email_tasks",
        "backend_fastapi.app.tasks.audit_tasks",
        "backend_fastapi.app.tasks.pdf_tasks",
        "backend_fastapi.app.tasks.suggestion_tasks",
        "backend_fastapi.app.tasks.scraper_tasks",
        "backend_fastapi.app.tasks.translation_tasks",
        "backend_fastapi.app.tasks.ocr_tasks",
        "backend_fastapi.app.tasks.notification_tasks",
        "backend_fastapi.app.tasks.manga_tasks",
        "backend_fastapi.app.tasks.community_tasks",
    ],
)

celery_app.conf.timezone = _setting("timezone", "UTC")
celery_app.conf.enable_utc = True
# Run tasks inline (no broker) when CELERY_TASK_ALWAYS_EAGER is set — used by the
# test suite and for local/dev smoke runs. Never honoured in production: gated
# on the deployment environment (see core.test_mode.celery_eager_active) so a
# stray flag in a prod deploy cannot silently bypass the worker fleet.
from .test_mode import celery_eager_active  # noqa: E402

if celery_eager_active():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_store_eager_result = True
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.broker_connection_retry_on_startup = True
# Finite retries (not 0/infinite): a broker outage must not let a publisher
# (e.g. the FastAPI SWR cache dispatching a refresh task) retry forever.
celery_app.conf.broker_connection_max_retries = 3
celery_app.conf.result_backend_transport_options = {"retry_on_timeout": True}
celery_app.conf.worker_pool_restarts = True
# H6: workers run in the default synchronous prefork pool. Scraper tasks
# (base_scraper) therefore use blocking time.sleep/requests by design — they run
# in separate processes, not on the API's async event loop. If you switch to an
# async pool (gevent/eventlet), convert those blocking calls to async first.

# ---------------------------------------------------------------------------
# Item 38 — isolated queues, at-least-once delivery, bounded retries, DLQ.
# A flood of one job type (e.g. a big scrape) must not starve unrelated work
# (email, maintenance). Tasks are routed to dedicated named queues so workers
# can be bound per-queue (celery -Q scrape / -Q ocr / ...). acks_late +
# reject_on_worker_lost give at-least-once semantics, and prefetch=1 keeps a
# slow task from hoarding queued messages.
# ---------------------------------------------------------------------------
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.worker_prefetch_multiplier = 1
# Workload priority policy (SRS 1C.5.3): user-facing translation (High) must
# not queue behind background OCR (Medium) or scheduled scraping (Low). The
# per-route ``priority`` is honoured by brokers that support message priority
# and is harmless otherwise; queue isolation already prevents cross-type
# starvation.
from .workload_priority import priority_for  # noqa: E402

celery_app.conf.task_routes = {
    "backend_fastapi.app.tasks.scraper_tasks.*": {
        "queue": "scrape",
        "priority": priority_for("backend_fastapi.app.tasks.scraper_tasks"),
    },
    "backend_fastapi.app.tasks.ocr_tasks.*": {
        "queue": "ocr",
        "priority": priority_for("backend_fastapi.app.tasks.ocr_tasks"),
    },
    "backend_fastapi.app.tasks.translation_tasks.*": {
        "queue": "translation",
        "priority": priority_for("backend_fastapi.app.tasks.translation_tasks"),
    },
    "backend_fastapi.app.tasks.email_tasks.*": {
        "queue": "email",
        "priority": priority_for("backend_fastapi.app.tasks.email_tasks"),
    },
    "backend_fastapi.app.tasks.pdf_tasks.*": {
        "queue": "maintenance",
        "priority": priority_for("backend_fastapi.app.tasks.pdf_tasks"),
    },
    "backend_fastapi.app.tasks.audit_tasks.*": {
        "queue": "maintenance",
        "priority": priority_for("backend_fastapi.app.tasks.audit_tasks"),
    },
    "backend_fastapi.app.tasks.suggestion_tasks.*": {
        "queue": "maintenance",
        "priority": priority_for("backend_fastapi.app.tasks.suggestion_tasks"),
    },
    "backend_fastapi.app.tasks.notification_tasks.*": {
        "queue": "notifications",
        "priority": priority_for("backend_fastapi.app.tasks.notification_tasks"),
    },
    "backend_fastapi.app.tasks.community_tasks.*": {
        "queue": "maintenance",
        "priority": priority_for("backend_fastapi.app.tasks.community_tasks"),
    },
}
# Bounded retries with exponential backoff + jitter for every task by default.
#
# F-17: Task.annotate() (celery/app/task.py) resolves cls.app.annotations as
# (exact-name match, then the "*" wildcard match) and applies both in that
# order via setattr -- the wildcard is *always* applied last, so it always
# wins over a same-key exact-task entry regardless of list/dict ordering on
# our side. Confirmed by reading the installed celery 5.x source
# (celery.app.annotations.resolve_all,
# MapAnnotation.annotate/annotate_any). This previously let the six core
# scraper tasks' own retry_backoff_max=3600 decorator kwarg exist in source
# while this wildcard silently forced it back down to 600 at runtime --
# there is no way to override this attribute per-task via task_annotations
# in this version. The decorators now declare the value that's actually
# enforced instead.
celery_app.conf.task_annotations = {
    "*": {
        "max_retries": 3,
        "retry_backoff": True,
        "retry_backoff_max": 600,
        "retry_jitter": True,
    }
}

_dlq_logger = structlog.get_logger("backend_fastapi.celery.dlq")
DEAD_LETTER_KEY = "celery:dead_letter"


WORKER_IDLE_TXN_MS = int(os.getenv("CELERY_IDLE_IN_TXN_TIMEOUT_MS", "900000"))


@worker_process_init.connect
def _prepare_database_in_child(**_kwargs) -> None:  # pragma: no cover - exercised by workers
    """Give each forked worker process its own, worker-appropriate connections.

    * The parent may already hold pooled connections (opened while importing
      the app); children that inherit and share one corrupt it ("SSL
      connection has been closed unexpectedly"). ``close=False`` drops the
      inherited pool without closing sockets the parent still uses.
    * The API keeps Postgres' strict 10s idle-in-transaction limit, but a
      scrape or image job legitimately spends longer than that on network
      I/O between two queries, so worker connections get a longer allowance
      (``CELERY_IDLE_IN_TXN_TIMEOUT_MS``, default 15 minutes) instead of being
      killed mid-task.
    """

    # Roadmap item 13: workers report failed tasks to Sentry too (the API
    # initialises it in main.py; workers never import that path).
    from ..bootstrap.observability import init_sentry

    init_sentry(settings)

    from sqlalchemy import event

    from .db import engine

    engine.dispose(close=False)
    if engine.dialect.name != "postgresql":
        return

    @event.listens_for(engine, "connect")
    def _lengthen_idle_in_txn(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET idle_in_transaction_session_timeout = {int(WORKER_IDLE_TXN_MS)}")
        cursor.close()
        dbapi_connection.commit()


@task_failure.connect
def _dead_letter_on_final_failure(  # pragma: no cover - exercised by workers
    sender=None, task_id=None, exception=None, args=None, kwargs=None, **_
):
    """Record permanently-failed tasks (retries exhausted) to a dead-letter list.

    Only fires for terminal failures; tasks still eligible for retry are ignored.

    F-14/F-16/F-31: `task_failure` only ever fires for a *terminal* failure to
    begin with -- Celery re-raises via `self.retry()` internally for any
    attempt a task's own `autoretry_for`/manual retry call will retry again,
    and that path does not emit `task_failure`. So `retries < max_retries`
    was never actually distinguishing "still retrying" from "exhausted"; it
    was silently assuming every task declares `autoretry_for` and therefore
    ever gets a `retries` count above 0. Every task that has never opted into
    autoretry keeps `request.retries == 0` forever (Celery never increments
    it), while `max_retries` is still set on that task's class because the
    global task_annotations wildcard applies it to every task regardless.
    `retries(0) < max_retries(3)` was therefore always true for these tasks,
    so this handler always returned early and the *only* failure they will
    ever have was never recorded -- confirmed for 4 tasks by two earlier
    findings (F-14, F-16) and, on a full sweep, for 13 more real, dispatched
    tasks including magic-link email delivery, every in-app notification,
    and both Beat-scheduled scraper workhorses. Gating on whether the task
    actually declares `autoretry_for` (rather than inferring retry
    eligibility from `max_retries` alone, which the global wildcard sets
    unconditionally) closes the blind spot for all of them at once, present
    and future, without needing a per-task opt-in.
    """

    request = getattr(sender, "request", None)
    retries = getattr(request, "retries", 0) or 0
    max_retries = getattr(sender, "max_retries", 0) or 0
    autoretry_for = getattr(sender, "autoretry_for", None)
    if autoretry_for and max_retries and retries < max_retries:
        return  # not terminal yet — Celery will retry

    task_name = getattr(sender, "name", None)
    _dlq_logger.error(
        "celery_task_dead_letter",
        task=task_name,
        task_id=task_id,
        retries=retries,
        error=str(exception),
    )
    try:
        import json
        import redis as _redis

        broker = celery_app.conf.broker_url or ""
        if broker.startswith(("redis://", "rediss://")):
            client = _redis.Redis.from_url(broker)
            client.lpush(
                DEAD_LETTER_KEY,
                json.dumps(
                    {
                        "task": task_name,
                        "task_id": task_id,
                        "error": str(exception),
                        "retries": retries,
                    }
                ),
            )
            client.ltrim(DEAD_LETTER_KEY, 0, 999)  # keep the last 1000
    except Exception:  # best-effort; never raise from a failure handler
        _dlq_logger.warning("dead_letter_persist_failed", task=task_name)


# M4 / Blind Spot #6,#7: the schedule previously registered several entries that
# ran identical work. run_fast_scrape() and sync() are pure aliases of
# run_scheduled_scrape(), so "fast-scrape" (900s) exactly duplicated
# "scheduled-scrape" (900s) and "scraper-sync-hourly" re-ran the same job draining
# on a slower cadence; "pdf-integrity-daily" duplicated "pdf-integrity" (same task,
# same 24h period). Those duplicates are removed so each unit of work is scheduled
# exactly once. The alias task functions remain for any direct callers.
celery_app.conf.beat_schedule = {
    "audit-flush-every-5m": {
        "task": "backend_fastapi.app.tasks.audit_tasks.flush_audit",
        "schedule": 300.0,
    },
    "suggestion-scan-hourly": {
        "task": "backend_fastapi.app.tasks.suggestion_tasks.scan",
        "schedule": 60.0 * 60.0,
    },
    "scraper-cleanup-stuck-jobs": {
        "task": "backend_fastapi.app.tasks.scraper_tasks.cleanup_stuck_jobs",
        "schedule": 60.0 * 15.0,  # Run every 15 minutes
    },
    "history-prune-daily": {
        "task": "backend_fastapi.app.tasks.scraper_tasks.prune_history_task",
        "schedule": 60.0 * 60.0 * 24.0,  # Run every 24 hours
    },
    # Drain queued scraping jobs. Single canonical entry (was scheduled-scrape +
    # fast-scrape + scraper-sync-hourly, all running the same task).
    "scheduled-scrape": {
        "task": "backend_fastapi.app.tasks.scraper_tasks.run_scheduled_scrape",
        "schedule": 900.0,
    },
    # SRS 1G.12A: check due series for new chapters, lightweight and
    # low-priority. Runs every 30 minutes; each series is only actually
    # checked when its own next_check_at (8-12h default, jittered) is due.
    "scheduled-chapter-checks": {
        "task": "backend_fastapi.app.tasks.scraper_tasks.run_scheduled_chapter_checks",
        "schedule": 60.0 * 30.0,
    },
    # F-22: renamed from "nightly-full-reindex" -- the task only ever did a
    # SELECT count(*), no scraping/chapter-checks/writes of any kind, so the
    # old name implied a consistency/repair pass that never existed.
    "nightly-manga-count-metric": {
        "task": "backend_fastapi.app.tasks.scraper_tasks.report_manga_count_metric",
        "schedule": 60.0 * 60.0 * 24.0,
    },
    # Roadmap item 11: per-source-site parser health check (zero chapters or
    # zero pictures -> admin alert + parser re-detection).
    "source-health-daily": {
        "task": "backend_fastapi.app.tasks.scraper_tasks.check_source_health",
        "schedule": 60.0 * 60.0 * 24.0,
    },
    # Roadmap item 12: alert when the pictures volume passes its threshold.
    "storage-usage-daily": {
        "task": "backend_fastapi.app.tasks.scraper_tasks.check_storage_usage",
        "schedule": 60.0 * 60.0 * 24.0,
    },
    # Daily PDF integrity scan (single canonical entry; was pdf-integrity +
    # pdf-integrity-daily running the same task twice).
    "pdf-integrity": {
        "task": "backend_fastapi.app.tasks.pdf_tasks.daily_integrity_scan",
        "schedule": 60.0 * 60.0 * 24.0,
    },
    # F-28: resolved content reports (comment + meme) never expired.
    "content-reports-prune-daily": {
        "task": "backend_fastapi.app.tasks.community_tasks.prune_resolved_reports",
        "schedule": 60.0 * 60.0 * 24.0,
    },
    # The token denylist gains a row per logout and per refresh; rows past
    # their token's own expiry are dead weight.
    "revoked-tokens-purge-daily": {
        "task": "backend_fastapi.app.tasks.audit_tasks.purge_expired_revoked_tokens",
        "schedule": 60.0 * 60.0 * 24.0,
    },
}


@celery_app.task(name="backend_fastapi.app.tasks.echo.ping")
def ping():
    return "pong"
