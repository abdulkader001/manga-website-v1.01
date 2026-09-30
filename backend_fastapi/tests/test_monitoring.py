from __future__ import annotations

from fastapi.testclient import TestClient


def test_system_stats_endpoint_available(fastapi_client: TestClient) -> None:
    response = fastapi_client.get("/api/v1/system/stats")
    assert response.status_code == 200
    headers = response.headers
    if isinstance(headers, list):
        headers = dict(headers)
    content_type = headers.get("content-type") if hasattr(headers, "get") else None
    assert content_type is not None
    assert "text/plain" in content_type
    assert b"app_uptime_seconds" in response.content


def test_metrics_path_serves_prometheus_exposition_only(
    fastapi_client: TestClient,
) -> None:
    """``/metrics`` must not double as the psutil process-stats endpoint."""

    response = fastapi_client.get("/metrics")
    assert response.status_code == 200
    assert b"app_uptime_seconds" not in response.content
    assert b"http_requests_total" in response.content

    # The legacy aliases of the application router must not resurrect it either.
    assert fastapi_client.get("/api/metrics").status_code == 404


def test_healthz_endpoint_available(fastapi_client: TestClient) -> None:
    response = fastapi_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_root_endpoint_reports_service_metadata(fastapi_client: TestClient) -> None:
    response = fastapi_client.get("/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "manga-stack-backend"
    assert payload["docs_url"] == "/docs"
    assert payload["openapi_url"] == "/openapi.json"

    features = payload.get("features")
    assert isinstance(features, dict)
    assert {"ocr", "translation"}.issubset(features)

    subsystems = payload.get("subsystems")
    assert isinstance(subsystems, dict)
    assert "database" in subsystems
