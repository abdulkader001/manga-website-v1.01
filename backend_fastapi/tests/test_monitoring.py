from __future__ import annotations

from fastapi.testclient import TestClient


def _main_admin_headers() -> dict:
    import uuid

    from backend_fastapi.app.core.db import Base, SessionLocal, engine
    from backend_fastapi.app.core.security import create_access_token
    from backend_fastapi.app.models import User, UserRole

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        user = User(
            email=f"stats-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Stats",
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_system_stats_requires_main_admin(fastapi_client: TestClient) -> None:
    assert fastapi_client.get("/api/v1/system/stats").status_code in (401, 403)


def test_system_stats_endpoint_available(fastapi_client: TestClient) -> None:
    response = fastapi_client.get("/api/v1/system/stats", headers=_main_admin_headers())
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
