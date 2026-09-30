"""Prometheus metrics (item 42).

Exposes a ``/metrics`` endpoint and records per-request latency/count/in-flight
via middleware. Request IDs are already propagated by ``LoggingMiddleware``; this
adds the numeric telemetry (latency, error rate per route, in-flight) plus a
gauge that other subsystems (rate limiter, cache, DB pool) can update.

Metrics are safe to scrape from a single ``/metrics`` route; label cardinality
is bounded by using the matched *route template* (e.g. ``/api/manga/{manga_id}``)
rather than the raw path.
"""

from __future__ import annotations

import time

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except Exception:  # pragma: no cover - prometheus_client is a pinned dependency
    _PROM_AVAILABLE = False


if _PROM_AVAILABLE:
    REQUEST_COUNT = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
    )
    REQUEST_LATENCY = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "path"],
    )
    REQUESTS_IN_PROGRESS = Gauge(
        "http_requests_in_progress",
        "In-flight HTTP requests",
        ["method"],
    )


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _PROM_AVAILABLE or request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        REQUESTS_IN_PROGRESS.labels(method=method).inc()
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            path = _route_template(request)
            REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)
            REQUEST_COUNT.labels(
                method=method, path=path, status=str(status_code)
            ).inc()
            REQUESTS_IN_PROGRESS.labels(method=method).dec()


def add_prometheus_middleware(app: FastAPI) -> None:
    """Register the request-instrumentation middleware.

    Kept separate from :func:`setup_metrics` because the middleware's position
    in the stack matters (see ``bootstrap.middleware.configure_middleware``):
    it sits just inside SecurityHeaders so it observes the same status code the
    client receives, including short-circuits from the layers below it.
    """

    if not _PROM_AVAILABLE:
        return

    app.add_middleware(PrometheusMiddleware)


def setup_metrics(app: FastAPI) -> None:
    """Register the ``/metrics`` scrape endpoint."""

    if not _PROM_AVAILABLE:
        return

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
