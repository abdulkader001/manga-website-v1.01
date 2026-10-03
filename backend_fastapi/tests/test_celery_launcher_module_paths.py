"""Guard against F-01: every Celery launcher must reference a real app module.

All worker/beat launch commands (shell scripts, k8s manifests, systemd units)
pass ``celery -A <module>:<attr>``. If that module path drifts from where the
Celery app actually lives — as happened when ``celery_app.py`` moved under
``app/core/`` but the launchers kept pointing at ``app.celery_app`` — every
background job silently stops being consumed.

This test scrapes the ``-A`` target out of every launcher file in the repo,
imports it, and asserts it resolves to a real ``celery.Celery`` instance. It
would have caught F-01 and blocks a future refactor from reintroducing it.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from celery import Celery

ROOT = Path(__file__).resolve().parents[2]

# Files that launch a Celery worker/beat via ``-A module:attr``. Kept explicit
# so a newly added launcher must be registered here (and thereby checked).
LAUNCHER_FILES = [
    "backend_fastapi/scripts/start_celery_worker.sh",
    "backend_fastapi/scripts/start_celery_beat.sh",
    "backend_fastapi/deployment/k8s/celery-worker.yaml",
    "backend_fastapi/deployment/k8s/celery-beat.yaml",
]

# ``-A backend_fastapi.app.core.celery_app:celery_app`` (with or without the
# ``=`` form) — capture the ``module:attr`` spec.
_APP_SPEC_RE = re.compile(r"-A[=\s]+([A-Za-z0-9_.]+:[A-Za-z0-9_]+)")


def _collect_specs() -> set[tuple[str, str]]:
    specs: set[tuple[str, str]] = set()
    for rel in LAUNCHER_FILES:
        path = ROOT / rel
        assert path.exists(), f"launcher file missing: {rel}"
        for match in _APP_SPEC_RE.finditer(path.read_text()):
            specs.add((rel, match.group(1)))
    return specs


def test_launcher_files_declare_a_celery_app() -> None:
    """Every registered launcher file must contain at least one ``-A`` spec."""

    seen_files = {rel for rel, _ in _collect_specs()}
    missing = set(LAUNCHER_FILES) - seen_files
    assert not missing, f"no `celery -A module:attr` found in: {sorted(missing)}"


@pytest.mark.parametrize("spec", sorted({spec for _, spec in _collect_specs()}))
def test_launcher_module_is_importable_celery_app(spec: str) -> None:
    """The ``module:attr`` each launcher points at must be a real Celery app."""

    module_path, attr = spec.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:  # pragma: no cover - failure path
        pytest.fail(
            f"Celery launcher references '{spec}', but module '{module_path}' "
            f"is not importable ({exc}). Background jobs would never be "
            f"consumed. Point the launcher at the real app module."
        )
    obj = getattr(module, attr, None)
    assert isinstance(obj, Celery), (
        f"Celery launcher references '{spec}', but '{attr}' on '{module_path}' "
        f"is {type(obj).__name__}, not a celery.Celery instance."
    )
