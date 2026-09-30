"""Deprecation signal on the legacy (non-``/api/v1``) route aliases.

Every route is mounted three times (canonical ``/api/v1``, no-prefix, and
``/api``) for backward compatibility. This does not remove either legacy
alias -- it only tags responses so real usage can be measured. See
``bootstrap/routers.register_api_routes`` and
``bootstrap/middleware.LegacyApiAliasDeprecationMiddleware``.

Uses the (auth-gated) bookmarks route as a stand-in matched route: the
assertions are about the alias-detection middleware, not about bookmarks
auth, so a 401 is a fine response to check headers on.
"""

from __future__ import annotations


def _headers(resp) -> dict[str, str]:
    """Normalize a test-client response's headers to a lowercase dict.

    The repo's offline httpx stub (installed by conftest for network-free
    tests) returns ``response.headers`` as a bare list of tuples rather than
    a case-insensitive mapping, so tests can't call ``.get()`` on it directly.
    """
    return {k.lower(): v for k, v in resp.headers}


def test_canonical_v1_path_has_no_deprecation_header(fastapi_client):
    resp = fastapi_client.get("/api/v1/bookmarks")
    assert resp.status_code == 401
    assert "deprecation" not in _headers(resp)


def test_legacy_api_prefixed_alias_is_flagged(fastapi_client):
    resp = fastapi_client.get("/api/bookmarks")
    assert resp.status_code == 401
    headers = _headers(resp)
    assert headers.get("deprecation") == "true"
    assert headers.get("link") == '</api/v1/bookmarks>; rel="successor-version"'


def test_legacy_no_prefix_alias_is_flagged(fastapi_client):
    resp = fastapi_client.get("/bookmarks")
    assert resp.status_code == 401
    headers = _headers(resp)
    assert headers.get("deprecation") == "true"
    assert headers.get("link") == '</api/v1/bookmarks>; rel="successor-version"'


def test_root_and_infra_routes_are_never_flagged(fastapi_client):
    for path in ("/", "/health", "/healthz"):
        resp = fastapi_client.get(path)
        assert "deprecation" not in _headers(resp), path


def test_unmatched_path_is_not_flagged(fastapi_client):
    resp = fastapi_client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert "deprecation" not in _headers(resp)


def _alias_count(alias: str) -> float:
    from prometheus_client import REGISTRY

    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name != "legacy_api_alias_requests":
            continue
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels["alias"] == alias:
                total += sample.value
    return total


def test_legacy_alias_calls_are_counted_per_alias(fastapi_client):
    """Roadmap item 9: /metrics must show which aliases are still in use."""
    prefixed, bare = _alias_count("api-prefix"), _alias_count("no-prefix")

    fastapi_client.get("/api/bookmarks")
    fastapi_client.get("/bookmarks")
    fastapi_client.get("/api/v1/bookmarks")

    assert _alias_count("api-prefix") == prefixed + 1
    assert _alias_count("no-prefix") == bare + 1
