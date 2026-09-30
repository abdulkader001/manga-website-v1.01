"""Tests for the Celery container healthcheck.

The compose services previously curled the *backend's* ``/healthz``, so a dead
worker stayed "healthy" for as long as the API was up. These tests pin the two
properties that make the replacement meaningful: it recognises a real celery
daemon, and it does not recognise anything else -- including itself.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "celery_healthcheck.py"
)
_spec = importlib.util.spec_from_file_location("celery_healthcheck", _SCRIPT)
celery_healthcheck = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(celery_healthcheck)


@pytest.mark.parametrize(
    "argv",
    [
        # Bare console script.
        ["celery", "-A", "app:celery_app", "worker", "--loglevel=INFO"],
        # How the kernel actually reports a console script (shebang interpreter
        # first, script path second).
        ["/usr/bin/python3", "/usr/local/bin/celery", "-A", "app", "worker"],
        # Module invocation.
        ["python", "-m", "celery", "-A", "app", "worker"],
    ],
)
def test_recognises_real_celery_worker_invocations(argv):
    assert celery_healthcheck._is_celery_invocation(argv)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        # The healthcheck's own command line: contains "celery" and "worker",
        # and must NOT count -- otherwise the check always passes.
        ["python", "/app/backend_fastapi/scripts/celery_healthcheck.py", "worker"],
        # A shell wrapper that merely mentions celery.
        ["sh", "-c", "echo celery worker"],
        # -m with a different module.
        ["python", "-m", "pytest", "celery", "worker"],
    ],
)
def test_rejects_non_celery_command_lines(argv):
    assert not celery_healthcheck._is_celery_invocation(argv)


def test_role_is_matched_on_the_subcommand(monkeypatch):
    """A running beat must not satisfy the worker check, and vice versa."""

    beat_argv = ["celery", "-A", "app", "beat", "--loglevel=INFO"]
    monkeypatch.setattr(
        celery_healthcheck, "_process_cmdlines", lambda: iter([beat_argv])
    )

    assert celery_healthcheck._celery_process_running("beat")
    assert not celery_healthcheck._celery_process_running("worker")


def test_dead_worker_fails_the_check(monkeypatch):
    """No matching process => non-zero exit, regardless of broker health."""

    monkeypatch.setattr(celery_healthcheck, "_process_cmdlines", lambda: iter([]))
    monkeypatch.setattr(celery_healthcheck, "_broker_reachable", lambda: True)

    assert celery_healthcheck.main(["celery_healthcheck.py", "worker"]) == 1


def test_unreachable_broker_fails_the_check(monkeypatch):
    monkeypatch.setattr(
        celery_healthcheck,
        "_process_cmdlines",
        lambda: iter([["celery", "-A", "app", "worker"]]),
    )
    monkeypatch.setattr(celery_healthcheck, "_broker_reachable", lambda: False)

    assert celery_healthcheck.main(["celery_healthcheck.py", "worker"]) == 1


def test_healthy_worker_passes(monkeypatch):
    monkeypatch.setattr(
        celery_healthcheck,
        "_process_cmdlines",
        lambda: iter([["celery", "-A", "app", "worker"]]),
    )
    monkeypatch.setattr(celery_healthcheck, "_broker_reachable", lambda: True)

    assert celery_healthcheck.main(["celery_healthcheck.py", "worker"]) == 0


def test_unknown_role_is_a_usage_error(monkeypatch):
    assert celery_healthcheck.main(["celery_healthcheck.py", "flower"]) == 2
