"""Per-request timeout middleware with exemptions for long-running routes (C3)."""

from __future__ import annotations

from typing import Iterable

import anyio
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..core.api_errors import ErrorCode, error_body

# Routes that legitimately run longer than the global timeout (OCR/translation
# do real CPU/network work). Applying one short global timeout to these returns
# 504s for valid requests, so they are exempted here and bounded by their own
# generous timeout instead. Prefer moving genuinely long work to a background
# job (see the job/status pattern) so the HTTP request itself stays fast.
def _mounts(path: str) -> tuple[str, ...]:
    return (f"/api/v1{path}", f"/api{path}", path)


DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (
    *_mounts("/translation/"),
    *_mounts("/ocr/"),
    # Storage & Backups and Geolock talk to outside storage / download services.
    *_mounts("/admin/backups/"),
    *_mounts("/admin/geolock/"),
)

# No timeout at all: a backup upload streams many GB for as long as it takes
# (the main admin only; nginx has the matching no-limit location).
NO_TIMEOUT_PREFIXES: tuple[str, ...] = (
    *_mounts("/admin/backups/upload"),
    *_mounts("/admin/geolock/database/upload"),
)


class TimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        timeout_seconds: float = 5.0,
        exempt_prefixes: Iterable[str] | None = None,
        exempt_timeout_seconds: float | None = None,
    ):
        super().__init__(app)
        self.timeout_seconds = timeout_seconds
        self.exempt_prefixes = tuple(
            exempt_prefixes if exempt_prefixes is not None else DEFAULT_EXEMPT_PREFIXES
        )
        # A generous ceiling for exempt routes so a hung request still can't leak
        # forever; None disables the timeout entirely for exempt routes.
        self.exempt_timeout_seconds = exempt_timeout_seconds

    def _timeout_for(self, path: str) -> float | None:
        if path.startswith(NO_TIMEOUT_PREFIXES):
            return None
        if any(path.startswith(prefix) for prefix in self.exempt_prefixes):
            return self.exempt_timeout_seconds
        return self.timeout_seconds

    async def dispatch(self, request: Request, call_next):
        timeout = self._timeout_for(request.url.path)
        if timeout is None:
            return await call_next(request)
        try:
            with anyio.fail_after(timeout):
                return await call_next(request)
        except TimeoutError:
            return JSONResponse(
                content=error_body(
                    ErrorCode.GATEWAY_TIMEOUT,
                    "Request took too long to complete.",
                ),
                status_code=504,
            )
