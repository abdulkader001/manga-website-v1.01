"""Geolock: answer 451 to visitors from countries the main admin blocked.

Pure ASGI (no BaseHTTPMiddleware overhead). When Geolock is off the check is
two environment reads; when on, one cached GeoIP lookup per new address.
Health and metrics probes are never blocked (they come from the server's own
network, which has no country anyway).
"""

from __future__ import annotations

import json

from starlette.requests import Request

from ..core.api_errors import ErrorCode, error_body
from ..services import geolock

_EXEMPT_PREFIXES = ("/healthz", "/health/live", "/health/ready", "/metrics")
MESSAGE = "This site isn't available in your country."


class GeolockMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not geolock.enabled():
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path.startswith(_EXEMPT_PREFIXES) or not geolock.is_blocked(Request(scope)):
            await self.app(scope, receive, send)
            return
        body = json.dumps(error_body(ErrorCode.REGION_BLOCKED, MESSAGE)).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 451,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
