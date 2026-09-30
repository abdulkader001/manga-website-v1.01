"""Regression tests for the HTTP middleware stack ordering.

Middleware order is easy to break silently: ``add_middleware`` prepends, so a
call added in a "natural looking" place lands at the opposite end of the stack
from what the author intended. Two placements here are security/UX relevant and
are asserted explicitly below.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend_fastapi.app.bootstrap.middleware import configure_middleware
from backend_fastapi.app.core.settings import get_settings

# Outermost first. Keep in sync with the docstring of configure_middleware.
EXPECTED_ORDER = [
    "CORSMiddleware",
    "SecurityHeadersMiddleware",
    "PrometheusMiddleware",
    "ForwardedHeadersMiddleware",
    "TimeoutMiddleware",
    "BackpressureMiddleware",
    "LegacyApiAliasDeprecationMiddleware",
    "LoggingMiddleware",
    "GZipMiddleware",
    "CSRFMiddleware",
    "RateLimitMiddleware",
]


def _stack(app: FastAPI) -> list[str]:
    return [getattr(m.cls, "__name__", str(m.cls)) for m in app.user_middleware]


def _header(response, name: str) -> str | None:
    """Case-insensitive header lookup that tolerates the local httpx stub.

    The repo ships a minimal ``httpx`` shim for the TestClient whose ``headers``
    is sometimes a plain list of pairs rather than a mapping.
    """

    headers = response.headers
    if isinstance(headers, list):
        headers = dict(headers)
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return value
    return next(
        (v for k, v in dict(headers).items() if k.lower() == name.lower()),
        None,
    )


def test_runtime_middleware_order(fastapi_app):
    """The live app's stack matches the documented outermost->innermost order.

    HTTPSRedirect is absent here because the test settings leave
    FORCE_HTTPS_REDIRECTS off; ``test_https_redirect_sits_inside_forwarded_headers``
    covers its position.
    """

    assert _stack(fastapi_app) == EXPECTED_ORDER


def test_cors_is_outermost(fastapi_app):
    """CORS must wrap every layer that can short-circuit a request.

    RateLimit (429), Backpressure (503) and Timeout (504) all return without
    reaching the router. If CORS sat inside them those responses would carry no
    ``Access-Control-Allow-Origin`` and the browser would surface an opaque
    network error instead of the real status.
    """

    assert _stack(fastapi_app)[0] == "CORSMiddleware"

    stack = _stack(fastapi_app)
    for short_circuiting in (
        "RateLimitMiddleware",
        "BackpressureMiddleware",
        "TimeoutMiddleware",
    ):
        assert stack.index("CORSMiddleware") < stack.index(short_circuiting)


def test_rate_limited_response_carries_cors_headers():
    """A 429 must reach the browser as a 429, not an opaque network error."""

    settings = get_settings().model_copy(
        update={
            "cors_allowed_origins": ["http://localhost:8080"],
            "generic_rate_limit_requests": 2,
            "generic_rate_limit_window": 60,
            "force_https_redirects": False,
        }
    )

    app = FastAPI()
    configure_middleware(app, settings)

    @app.get("/limited")
    def limited() -> dict[str, bool]:
        return {"ok": True}

    origin = {"Origin": "http://localhost:8080"}
    with TestClient(app) as client:
        for _ in range(30):
            response = client.get("/limited", headers=origin)
            if response.status_code == 429:
                break
        else:  # pragma: no cover - the limiter is configured to trip well before this
            pytest.fail("rate limiter never tripped")

    assert response.status_code == 429
    assert _header(response, "access-control-allow-origin") == "http://localhost:8080"


def test_https_redirect_sits_inside_forwarded_headers():
    """HTTPSRedirect must see the proxy-supplied scheme, or it loops forever."""

    settings = get_settings().model_copy(update={"force_https_redirects": True})

    app = FastAPI()
    configure_middleware(app, settings)
    stack = _stack(app)

    assert "HealthExemptHTTPSRedirectMiddleware" in stack
    assert stack.index("ForwardedHeadersMiddleware") < stack.index(
        "HealthExemptHTTPSRedirectMiddleware"
    )


def test_health_probes_are_not_redirected_when_https_is_forced():
    """The container healthcheck must get a 200 over plain loopback HTTP.

    docker-compose probes ``http://localhost:8000/healthz`` from *inside* the
    container, so there is no X-Forwarded-Proto and the unmodified
    HTTPSRedirectMiddleware answers 307 -> https://... . urllib follows that
    into a TLS handshake against a plain-HTTP port and raises, the healthcheck
    exits non-zero, and every service gated on ``condition: service_healthy``
    never starts. The rest of the suite runs with FORCE_HTTPS_REDIRECTS off,
    which is why this has to be asserted with the setting explicitly on.
    """

    settings = get_settings().model_copy(update={"force_https_redirects": True})

    app = FastAPI()
    configure_middleware(app, settings)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/manga")
    def manga() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        for probe in ("/healthz", "/health"):
            response = client.get(
                f"http://testserver{probe}", follow_redirects=False
            )
            assert response.status_code == 200, (
                f"{probe} must answer 200 over plain HTTP, got "
                f"{response.status_code}"
            )

        # Real traffic still gets redirected, so the assertions above are not
        # passing because the redirect was disabled wholesale.
        for path in ("/", "/api/v1/manga"):
            redirected = client.get(
                f"http://testserver{path}", follow_redirects=False
            )
            assert redirected.status_code in (301, 307, 308), (
                f"{path} should still be redirected to https, got "
                f"{redirected.status_code}"
            )


def test_forwarded_proto_prevents_redirect_loop():
    """A request marked https by the proxy is served, not redirected."""

    settings = get_settings().model_copy(update={"force_https_redirects": True})

    app = FastAPI()
    configure_middleware(app, settings)

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get(
            "http://testserver/ping",
            headers={"X-Forwarded-Proto": "https"},
            follow_redirects=False,
        )

    assert response.status_code == 200

    # Without the header the redirect still fires, so the check above is not
    # passing for the wrong reason.
    with TestClient(app) as client:
        plain = client.get("http://testserver/ping", follow_redirects=False)

    assert plain.status_code in (redirect := (301, 307, 308)), (
        f"expected one of {redirect}, got {plain.status_code}"
    )
