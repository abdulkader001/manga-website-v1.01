"""Shared structured logging configuration and context helpers."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging() -> None:
    """Configure stdlib + structlog to emit JSON logs with contextvars."""

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            timestamper,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            timestamper,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)


def bind_request_context(
    *,
    request_id: str | None = None,
    path: str | None = None,
    method: str | None = None,
    **kwargs: Any,
) -> None:
    """Bind request/task correlation fields to structlog contextvars."""

    payload: dict[str, Any] = dict(kwargs)
    if request_id is not None:
        payload["request_id"] = request_id
    if path is not None:
        payload["path"] = path
    if method is not None:
        payload["method"] = method
    structlog.contextvars.bind_contextvars(**payload)


def clear_request_context() -> None:
    """Clear bound contextvars to avoid leaks between requests/tasks."""

    structlog.contextvars.clear_contextvars()
