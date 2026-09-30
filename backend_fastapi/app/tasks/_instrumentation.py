"""Shared task instrumentation for structured logging and correlation."""

from __future__ import annotations

import inspect
import time
from typing import Any

import structlog

from ..utils.structured_logging import bind_request_context, clear_request_context

logger = structlog.get_logger("celery.task")


def resolve_task_request_id(task, kwargs: dict[str, Any] | None = None) -> str | None:
    """Extract a request_id from task request metadata, kwargs, or headers."""

    kwargs = kwargs or {}
    request_id = kwargs.get("request_id") or kwargs.get("_request_id")
    if request_id:
        return request_id

    request = getattr(task, "request", None)
    if request is None:
        return None

    request_id = getattr(request, "request_id", None)
    if request_id:
        return request_id

    headers = getattr(request, "headers", None) or {}
    return headers.get("request_id") or headers.get("X-Request-ID")


def strip_internal_context_kwargs(
    task, kwargs: dict[str, Any] | None
) -> dict[str, Any]:
    """Drop reserved observability kwargs unless the task run() accepts them."""

    kwargs = dict(kwargs or {})
    accepted_params = set(inspect.signature(task.run).parameters.keys())

    for reserved in ("request_id", "_request_id"):
        if reserved in kwargs and reserved not in accepted_params:
            kwargs.pop(reserved, None)

    return kwargs


def before_task_start(
    task, kwargs: dict[str, Any] | None = None
) -> tuple[float, str | None]:
    """Bind context and emit celery_task_start event."""

    clear_request_context()
    request_id = resolve_task_request_id(task, kwargs)
    context = {
        "task_name": getattr(task, "name", "unknown"),
        "task_id": getattr(getattr(task, "request", None), "id", None),
    }
    if request_id:
        context["request_id"] = request_id

    bind_request_context(**context)
    logger.info("celery_task_start", **context)
    return time.perf_counter(), request_id


def log_task_success(task, started_at: float, request_id: str | None = None) -> None:
    """Emit celery_task_success with duration metadata."""

    duration_ms = (time.perf_counter() - started_at) * 1000
    payload = {
        "task_name": getattr(task, "name", "unknown"),
        "task_id": getattr(getattr(task, "request", None), "id", None),
        "duration_ms": round(duration_ms, 2),
        "outcome": "success",
    }
    if request_id:
        payload["request_id"] = request_id
    logger.info("celery_task_success", **payload)


def log_task_failure(
    task, started_at: float, exc: Exception, request_id: str | None = None
) -> None:
    """Emit celery_task_failure with duration and exception data."""

    duration_ms = (time.perf_counter() - started_at) * 1000
    payload = {
        "task_name": getattr(task, "name", "unknown"),
        "task_id": getattr(getattr(task, "request", None), "id", None),
        "duration_ms": round(duration_ms, 2),
        "outcome": "failure",
        "exception": str(exc),
    }
    if request_id:
        payload["request_id"] = request_id
    logger.exception("celery_task_failure", **payload)


def attach_request_id_to_publish_options(options: dict[str, Any]) -> dict[str, Any]:
    """Propagate active request_id into Celery publish headers when present."""

    context = structlog.contextvars.get_contextvars()
    request_id = context.get("request_id")
    if request_id:
        headers = options.setdefault("headers", {})
        headers.setdefault("request_id", request_id)
    return options
