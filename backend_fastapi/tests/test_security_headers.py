"""Baseline security headers on every response (SRS 1H.2)."""

from __future__ import annotations


def _headers_dict(response):
    headers = response.headers
    return dict(headers) if isinstance(headers, list) else headers


def test_security_headers_present_on_normal_response(fastapi_client):
    resp = fastapi_client.get("/api/manga")
    headers = _headers_dict(resp)
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert headers.get("content-security-policy") == (
        "default-src 'none'; frame-ancestors 'none'"
    )


def test_security_headers_present_on_error_response(fastapi_client):
    """Headers must survive error paths too, not just the happy path."""
    resp = fastapi_client.get("/api/admin/users/999999999")
    assert resp.status_code in (401, 403, 404)
    headers = _headers_dict(resp)
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("content-security-policy") is not None


def test_hsts_is_absent_without_tls_termination(fastapi_client):
    """The test stack runs plain HTTP (FORCE_HTTPS_REDIRECTS=false).

    Emitting HSTS there would pin a developer's browser to HTTPS for a host
    that does not serve it -- for a year, and not undoable by clearing the
    site's cookies. The header is keyed to the same setting that makes the
    auth cookies Secure, so the two can never disagree.
    """

    resp = fastapi_client.get("/api/manga")
    assert _headers_dict(resp).get("strict-transport-security") is None


def test_hsts_is_emitted_where_tls_is_terminated():
    """With FORCE_HTTPS_REDIRECTS on, every response carries HSTS."""

    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from backend_fastapi.app.bootstrap.middleware import SecurityHeadersMiddleware

    app = Starlette(routes=[Route("/", lambda request: PlainTextResponse("ok"))])
    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        header = _headers_dict(client.get("/")).get("strict-transport-security")

    assert header is not None
    assert "max-age=31536000" in header
    assert "includeSubDomains" in header
