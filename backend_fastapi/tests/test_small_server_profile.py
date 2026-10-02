"""F-96: the site fits a small server and never grows without bound.

* Celery children and Gunicorn workers are recycled (tasks/requests and
  memory limits), so leaking image/OCR memory goes back to the OS.
* ``docker-compose.small.yml`` runs two single-process workers that between
  them consume every routed queue (nothing is stranded), keeps reader-facing
  work apart from scraping, and pins small sizes that ``.env`` can't override.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from backend_fastapi.app.core.celery_app import celery_app

ROOT = Path(__file__).resolve().parents[2]


def _routed_queues() -> set[str]:
    routes = celery_app.conf.task_routes or {}
    queues = {celery_app.conf.task_default_queue}
    for route in routes.values():
        if isinstance(route, dict) and route.get("queue"):
            queues.add(route["queue"])
    return queues


def test_celery_children_are_recycled():
    assert celery_app.conf.worker_max_tasks_per_child == 200
    assert celery_app.conf.worker_max_memory_per_child == 400000


def test_gunicorn_workers_are_recycled():
    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf", ROOT / "backend_fastapi/deployment/gunicorn.conf.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.max_requests == 2000
    assert module.max_requests_jitter == 200


def test_small_profile_consumes_every_queue_with_two_workers():
    small = yaml.safe_load((ROOT / "docker-compose.small.yml").read_text())["services"]
    full = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]

    workers = [name for name in full if name.startswith("celery_worker")]
    enabled = [name for name in workers if "profiles" not in small.get(name, {})]
    assert sorted(enabled) == ["celery_worker", "celery_worker_scrape"]

    consumed: set[str] = set()
    for name in enabled:
        env = small[name]["environment"]
        assert env["CELERY_POOL"] == "solo"
        consumed |= set(env["CELERY_QUEUES"].split(","))
    assert _routed_queues() <= consumed

    reader_facing = set(small["celery_worker"]["environment"]["CELERY_QUEUES"].split(","))
    assert {"translation", "ocr"} <= reader_facing
    assert not reader_facing & {"scrape", "compress"}


def test_small_profile_sizes_are_pinned_not_read_from_env():
    text = (ROOT / "docker-compose.small.yml").read_text()
    small = yaml.safe_load(text)["services"]
    assert small["backend"]["environment"]["GUNICORN_WORKERS"] == 2
    assert small["redis"]["environment"]["REDIS_MAXMEMORY"] == "96mb"
    assert "max_connections=60" in small["db"]["command"]
    assert "${" not in text  # .env.example's full-size values must not leak in


def test_redis_cap_never_evicts_queues():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "maxmemory-policy volatile-lru" in compose
    assert "allkeys-lru" not in compose


def test_worker_script_supports_pool_override():
    script = (ROOT / "backend_fastapi/scripts/start_celery_worker.sh").read_text()
    assert '--pool="${CELERY_POOL}"' in script
