from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from backend_fastapi.app import tasks
from backend_fastapi.app.bootstrap import lifecycle
from backend_fastapi.app.core.celery_app import celery_app


def test_send_magic_link_email_task_invokes_service(monkeypatch):
    calls: list[tuple[str, str, str | None]] = []

    def fake_send(email: str, link: str, locale: str | None = None) -> None:
        calls.append((email, link, locale))

    monkeypatch.setattr(tasks.email_service, "send_magic_link_email", fake_send)

    result = tasks.send_magic_link_email_task(
        "user@example.com", "https://example", locale="en"
    )
    assert result["status"] == "queued"
    assert calls == [("user@example.com", "https://example", "en")]


def test_celery_beat_schedule_registered():
    beat_tasks = set(celery_app.conf.beat_schedule.keys())
    assert {
        "scheduled-scrape",
        "nightly-manga-count-metric",
        "pdf-integrity",
    }.issubset(beat_tasks)


def test_celery_queue_isolation_and_reliability():
    """Item 38: tasks route to dedicated queues with at-least-once delivery."""
    conf = celery_app.conf
    routes = conf.task_routes or {}

    def _queue_for(task_name: str) -> str | None:
        for pattern, opts in routes.items():
            prefix = pattern.rstrip("*")
            if task_name.startswith(prefix):
                return opts.get("queue")
        return None

    assert (
        _queue_for("backend_fastapi.app.tasks.scraper_tasks.run_scheduled_scrape")
        == "scrape"
    )
    assert (
        _queue_for("backend_fastapi.app.tasks.email_tasks.send_magic_link_email")
        == "email"
    )
    assert (
        _queue_for("backend_fastapi.app.tasks.pdf_tasks.daily_integrity_scan")
        == "maintenance"
    )
    # At-least-once delivery + no prefetch hoarding.
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    # Bounded retries with backoff for every task.
    default_annotations = (conf.task_annotations or {}).get("*", {})
    assert default_annotations.get("max_retries") == 3
    assert default_annotations.get("retry_backoff") is True


def _fake_sender(*, name: str, retries: int, max_retries: int, autoretry_for):
    from types import SimpleNamespace

    return SimpleNamespace(
        name=name,
        max_retries=max_retries,
        autoretry_for=autoretry_for,
        request=SimpleNamespace(retries=retries),
    )


def test_dead_letter_records_tasks_with_no_autoretry_on_their_only_failure(
    monkeypatch,
):
    """F-14/F-16/F-31: task_failure only ever fires for a genuinely terminal
    failure -- Celery's own retry path never emits it. But the DLQ signal
    handler used to infer "still eligible to retry" from
    retries < max_retries alone, and the global task_annotations wildcard
    sets max_retries=3 on every task regardless of whether it declared
    autoretry_for. A task with no autoretry_for never has request.retries
    advance past 0 (Celery never retries it), so retries(0) < max_retries(3)
    was always true, and the handler always returned early -- the *only*
    failure such a task will ever have was never written to
    celery:dead_letter. send_magic_link_email is one of the 13 real,
    dispatched tasks this affected (no autoretry_for declared at all).
    """
    from backend_fastapi.app.core import celery_app as celery_app_module
    from backend_fastapi.app.tasks import email_tasks

    assert getattr(email_tasks.send_magic_link_email, "autoretry_for", None) is None

    written = []

    class _FakeRedisClient:
        def lpush(self, key, value):
            written.append((key, value))

        def ltrim(self, *a, **k):
            pass

    # celery_app.conf.broker_url is a read-only property that resolves
    # CELERY_BROKER_URL from the environment first (see
    # celery.app.utils.Settings.broker_url) -- patching the attribute on
    # the conf object itself is silently ignored on read, so the env var
    # is what must be patched to make the handler take the redis:// path.
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        "redis.Redis.from_url", lambda *a, **k: _FakeRedisClient()
    )

    sender = _fake_sender(
        name=email_tasks.send_magic_link_email.name,
        retries=0,
        max_retries=email_tasks.send_magic_link_email.max_retries,
        autoretry_for=getattr(email_tasks.send_magic_link_email, "autoretry_for", None),
    )
    celery_app_module._dead_letter_on_final_failure(
        sender=sender, task_id="t-1", exception=RuntimeError("smtp down")
    )

    assert len(written) == 1
    assert written[0][0] == celery_app_module.DEAD_LETTER_KEY


def test_dead_letter_still_skips_genuinely_in_progress_autoretry_task(monkeypatch):
    """A task that DOES declare autoretry_for and hasn't exhausted its
    retries yet must still be skipped -- this handler's existing correct
    behavior for the four already-known (F-14/F-16) tasks must not regress.
    """
    from backend_fastapi.app.core import celery_app as celery_app_module
    from backend_fastapi.app.tasks import scraper_tasks

    assert scraper_tasks.process_manga_scrape.autoretry_for == (Exception,)

    written = []
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **k: type(
            "R", (), {"lpush": lambda *a, **k: written.append(1), "ltrim": lambda *a, **k: None}
        )(),
    )

    sender = _fake_sender(
        name=scraper_tasks.process_manga_scrape.name,
        retries=1,
        max_retries=scraper_tasks.process_manga_scrape.max_retries,
        autoretry_for=scraper_tasks.process_manga_scrape.autoretry_for,
    )
    celery_app_module._dead_letter_on_final_failure(
        sender=sender, task_id="t-2", exception=RuntimeError("transient")
    )

    assert written == []


def test_scraper_tasks_retry_backoff_max_matches_what_is_enforced():
    """F-17: the six core scraper tasks' decorators used to claim
    retry_backoff_max=3600, but celery_app.py's wildcard task_annotations
    entry always applies after and wins over that per-task kwarg (confirmed
    via Celery's own annotation resolution order -- exact-task match, then
    the "*" wildcard, both applied via setattr in that order), so the
    actual enforced cap was 600 the whole time. The decorators must declare
    what's actually enforced.
    """
    from backend_fastapi.app.tasks import scraper_tasks

    for name in (
        "process_manga_scrape",
        "process_chapter_scrape",
        "scrape_series_by_url",
        "scrape_chapter_by_url",
        "rescrape_series",
        "rescrape_chapter",
    ):
        task = getattr(scraper_tasks, name)
        assert task.retry_backoff_max == 600, (
            f"{name}.retry_backoff_max declares {task.retry_backoff_max}, "
            "but celery_app.py's wildcard task_annotations always forces "
            "this attribute to 600 at runtime -- the decorator must match"
        )


def test_celery_beat_schedule_has_no_duplicate_tasks():
    """M4 / Blind Spot #6,#7: each task is scheduled exactly once."""
    scheduled = [entry["task"] for entry in celery_app.conf.beat_schedule.values()]
    assert len(scheduled) == len(set(scheduled))
    # The removed duplicate entries must be gone.
    keys = set(celery_app.conf.beat_schedule.keys())
    assert "fast-scrape" not in keys
    assert "pdf-integrity-daily" not in keys
    assert "scraper-sync-hourly" not in keys


def test_initialize_redis(monkeypatch):
    class DummyRedis:
        def __init__(self):
            self.pinged = False
            self.closed = False

        async def ping(self):
            self.pinged = True

        async def close(self):
            self.closed = True

    dummy = DummyRedis()

    monkeypatch.setattr(Redis, "from_url", lambda url: dummy)
    app = type("App", (), {"state": type("State", (), {})()})()

    client = asyncio.run(lifecycle.initialize_redis(app, "redis://example"))
    assert client is dummy
    assert dummy.pinged


def test_initialize_celery_handles_failure(monkeypatch):
    class DummyConnection:
        def connect(self):
            raise RuntimeError("boom")

    class DummyCelery:
        def connection(self):
            return DummyConnection()

    monkeypatch.setattr(lifecycle, "celery_app", DummyCelery())

    app = type("App", (), {"state": type("State", (), {})()})()
    result = asyncio.run(lifecycle.initialize_celery(app))
    assert result is None
