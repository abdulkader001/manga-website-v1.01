from __future__ import annotations

import json
import uuid

import pytest
import structlog
from fastapi.testclient import TestClient

from backend_fastapi.app.main import app
from backend_fastapi.app.core.celery_app import celery_app
from backend_fastapi.app.utils.structured_logging import (
    bind_request_context,
    clear_request_context,
    configure_logging,
)

client = TestClient(app)


def _extract_json_logs(text: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def test_middleware_generates_request_id():
    response = client.get("/healthz")
    assert response.status_code == 200
    headers_dict = (
        dict(response.headers)
        if isinstance(response.headers, list)
        else response.headers
    )
    assert "x-request-id" in headers_dict


def test_middleware_reuses_request_id():
    custom_id = f"test-id-{uuid.uuid4()}"
    response = client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    headers_dict = (
        dict(response.headers)
        if isinstance(response.headers, list)
        else response.headers
    )
    assert headers_dict["x-request-id"] == custom_id


def test_structlog_contextvars_bind():
    clear_request_context()
    bind_request_context(request_id="test-bind-id")
    context = structlog.contextvars.get_contextvars()
    assert context.get("request_id") == "test-bind-id"
    clear_request_context()
    context = structlog.contextvars.get_contextvars()
    assert "request_id" not in context


def test_http_logs_are_json_with_request_id(capfd):
    configure_logging()
    request_id = f"req-{uuid.uuid4()}"

    response = client.get("/healthz", headers={"X-Request-ID": request_id})
    assert response.status_code == 200

    out, _ = capfd.readouterr()
    logs = _extract_json_logs(out)
    request_logs = [
        entry
        for entry in logs
        if entry.get("event") in {"http_request_start", "http_request_end"}
    ]

    assert request_logs, "expected structured request logs"
    for entry in request_logs:
        assert entry.get("request_id") == request_id
        assert entry.get("method") == "GET"
        assert entry.get("path") == "/healthz"

    end_log = next(
        entry for entry in request_logs if entry.get("event") == "http_request_end"
    )
    assert end_log.get("status_code") == 200
    assert isinstance(end_log.get("duration_ms"), (int, float))


@pytest.mark.usefixtures("capfd")
def test_celery_task_observability_logs_with_request_id(capfd):
    configure_logging()

    @celery_app.task(bind=True, name="tests.observability.echo")
    def _echo_task(self, value: str):
        return value

    previous_eager = celery_app.conf.task_always_eager
    celery_app.conf.task_always_eager = True
    try:
        result = _echo_task.apply(kwargs={"value": "ok", "request_id": "request-123"})
        assert result.get() == "ok"
    finally:
        celery_app.conf.task_always_eager = previous_eager

    out, _ = capfd.readouterr()
    logs = _extract_json_logs(out)
    task_logs = [
        entry
        for entry in logs
        if str(entry.get("event", "")).startswith("celery_task_")
    ]
    events = {entry.get("event") for entry in task_logs}

    assert {"celery_task_start", "celery_task_success"}.issubset(events)

    start_log = next(
        entry for entry in task_logs if entry.get("event") == "celery_task_start"
    )
    success_log = next(
        entry for entry in task_logs if entry.get("event") == "celery_task_success"
    )

    assert start_log.get("request_id") == "request-123"
    assert success_log.get("request_id") == "request-123"
    assert success_log.get("outcome") == "success"
    assert isinstance(success_log.get("duration_ms"), (int, float))
