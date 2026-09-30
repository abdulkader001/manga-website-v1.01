"""Roadmap item 13: Sentry covers Celery workers, not just the API."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from backend_fastapi.app.bootstrap import observability


def _settings(dsn):
    return SimpleNamespace(sentry_dsn=dsn, sentry_environment="test", release="r1")


def test_init_sentry_enables_celery_integration(monkeypatch):
    from sentry_sdk.integrations.celery import CeleryIntegration

    monkeypatch.setattr(observability, "_sentry_initialized", False)
    monkeypatch.setenv("ENABLE_SENTRY", "true")
    with mock.patch("sentry_sdk.init") as init:
        observability.init_sentry(_settings("https://key@example.ingest.sentry.io/1"))
    integrations = init.call_args.kwargs["integrations"]
    assert any(isinstance(i, CeleryIntegration) for i in integrations)


def test_init_sentry_is_a_no_op_without_a_dsn(monkeypatch):
    monkeypatch.setattr(observability, "_sentry_initialized", False)
    monkeypatch.setenv("ENABLE_SENTRY", "true")
    with mock.patch("sentry_sdk.init") as init:
        observability.init_sentry(_settings(None))
    init.assert_not_called()


def test_worker_process_init_initialises_sentry(monkeypatch):
    from backend_fastapi.app.core import celery_app as module

    with mock.patch.object(observability, "init_sentry") as init:
        module._prepare_database_in_child()
    init.assert_called_once()
