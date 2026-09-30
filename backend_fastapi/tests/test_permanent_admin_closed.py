"""Route-audit: the Permanent Administrator role is unassignable via the API.

SRS 1F.2.3 / 1F.2.4: the Permanent Administrator is bound exclusively from
deployment configuration on first login. No API endpoint assigns that role —
not a hidden one, not an admin-only one, not one behind a feature flag. This
test walks every registered route so a future re-introduction of such a path
fails loudly, rather than relying on any single endpoint test.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from backend_fastapi.app.main import create_app


def _all_routes():
    app = create_app()
    return [r for r in app.routes if isinstance(r, APIRoute)]


def test_no_route_path_targets_permanent_admin():
    """No mounted route path exposes a /permanent assignment endpoint."""
    offenders = [
        f"{sorted(r.methods)} {r.path}"
        for r in _all_routes()
        if "/permanent" in r.path.lower()
    ]
    assert offenders == [], f"Unexpected permanent-admin route(s): {offenders}"


def test_no_route_endpoint_promotes_to_permanent_admin():
    """No route handler references the removed PA-assignment service call."""
    for route in _all_routes():
        endpoint = route.endpoint
        source_names = getattr(endpoint, "__globals__", {})
        assert (
            "set_user_permanent_admin" not in source_names
        ), f"{route.path} still imports set_user_permanent_admin"
