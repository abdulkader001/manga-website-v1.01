"""Tests for the Prometheus /metrics endpoint (item 42)."""

from __future__ import annotations


def test_metrics_endpoint_exposes_request_metrics(fastapi_client):
    # Generate some traffic so counters/histograms have samples.
    fastapi_client.get("/api/system/state")
    fastapi_client.get("/healthz")

    resp = fastapi_client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "http_requests_in_progress" in body


def test_metrics_endpoint_records_request_path_label(fastapi_client):
    fastapi_client.get("/api/system/state")
    resp = fastapi_client.get("/metrics")
    assert resp.status_code == 200
    # The route template (not the raw path) is used as the label.
    assert "/api/system/state" in resp.text or "/system/state" in resp.text
