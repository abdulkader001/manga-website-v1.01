"""Expose lightweight per-process resource stats without external deps.

Deliberately **not** mounted at ``/metrics``: that path belongs to the real
Prometheus exposition produced by ``bootstrap/metrics.py`` (request counters,
latency histograms, in-flight gauge). Two endpoints called "metrics" serving
different payloads made scrape configs ambiguous, so this psutil-backed process
snapshot lives at ``/api/v1/system/stats`` instead.
"""

from __future__ import annotations

import os
import time

import psutil
from fastapi import APIRouter, Depends, Response

from ...dependencies.auth import require_main_admin_user

# Process stats describe the server (uptime, memory, CPU): main admin only.
# The Prometheus scraper uses /metrics, which nginx does not expose (F-90).
router = APIRouter(
    prefix="/system/stats",
    tags=["monitoring"],
    dependencies=[Depends(require_main_admin_user)],
)

_PROCESS = psutil.Process()
_PROCESS_START_TIME = _PROCESS.create_time()
_SERVICE_NAME = os.getenv("SERVICE_NAME", "backend_fastapi")


@router.get("", response_class=Response)
async def get_system_stats() -> Response:
    """Return a minimal text-based process-stats payload.

    The output follows the Prometheus exposition format so it can be scraped by
    monitoring systems, but it is a *supplement* to ``/metrics`` rather than a
    replacement: it reports only uptime/RSS/CPU for the process that happens to
    serve the request. We intentionally avoid the optional ``prometheus_client``
    dependency here to keep the runtime footprint minimal and avoid network
    access when installing requirements during CI validation.
    """

    process = psutil.Process()
    uptime = max(0.0, time.time() - _PROCESS_START_TIME)
    cpu_percent = process.cpu_percent(interval=None)
    memory_bytes = float(process.memory_info().rss)

    metrics_lines = [
        "# HELP app_uptime_seconds Application uptime in seconds.",
        "# TYPE app_uptime_seconds gauge",
        f'app_uptime_seconds{{service="{_SERVICE_NAME}"}} {uptime:.3f}',
        "# HELP app_process_resident_memory_bytes Resident set size in bytes.",
        "# TYPE app_process_resident_memory_bytes gauge",
        f'app_process_resident_memory_bytes{{service="{_SERVICE_NAME}"}} {memory_bytes:.0f}',
        "# HELP app_process_cpu_percent CPU utilisation percentage sampled from psutil.",
        "# TYPE app_process_cpu_percent gauge",
        f'app_process_cpu_percent{{service="{_SERVICE_NAME}"}} {cpu_percent:.2f}',
    ]

    body = "\n".join(metrics_lines) + "\n"
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
