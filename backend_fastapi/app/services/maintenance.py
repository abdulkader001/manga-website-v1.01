"""Maintenance mode: while enabled, API calls from anyone below Secondary
Administrator get a 503, except the endpoints needed to sign in and to
render the site chrome."""

from __future__ import annotations

import time

import structlog
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..core.api_errors import error_body

logger = structlog.get_logger("backend_fastapi.maintenance")

_CACHE_TTL_SECONDS = 10.0
_cache: dict[str, float | bool] = {"value": False, "expires": 0.0}

ALWAYS_OPEN_PREFIXES = (
    "/auth/",
    "/system/",
    "/branding",
    "/footer",
    "/social-links",
    "/announcements",
    "/config",
    "/health",
    "/healthz",
    "/metrics",
    "/version",
    "/admin/",
)


def invalidate_maintenance_cache() -> None:
    _cache["expires"] = 0.0


def _maintenance_on() -> bool:
    now = time.monotonic()
    if now < float(_cache["expires"]):
        return bool(_cache["value"])
    value = False
    try:
        from ..core.db import SessionLocal
        from .site_content_service import maintenance_enabled

        with SessionLocal() as session:
            value = maintenance_enabled(session)
    except Exception:  # never let a settings read take the API down
        logger.warning("maintenance_flag_read_failed")
    _cache["value"] = value
    _cache["expires"] = now + _CACHE_TTL_SECONDS
    return value


def _api_path(path: str) -> str:
    for prefix in ("/api/v1", "/api"):
        if path == prefix or path.startswith(prefix + "/"):
            return path[len(prefix):] or "/"
    return path


def _requester_is_admin(request: Request) -> bool:
    from ..core.db import SessionLocal
    from ..core.security import decode_token
    from ..dependencies.auth import is_secondary_or_higher
    from ..models import User

    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    token = token or request.cookies.get("access_token_cookie")
    if not token:
        return False
    try:
        subject = decode_token(token).get("sub")
        user_id = int(subject)
    except (JWTError, TypeError, ValueError):
        return False
    with SessionLocal() as session:
        user = session.get(User, user_id)
        return bool(user is not None and user.is_active and is_secondary_or_higher(user))


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api") or not _maintenance_on():
            return await call_next(request)
        api_path = _api_path(path)
        if api_path.startswith(ALWAYS_OPEN_PREFIXES) or _requester_is_admin(request):
            return await call_next(request)
        from ..core.api_errors import ErrorCode

        body = error_body(
            ErrorCode.SCRAPER_UNAVAILABLE,
            "The site is under maintenance. Please check back shortly.",
        )
        body["error"]["code"] = "MAINTENANCE"
        return JSONResponse(status_code=503, content=body, headers={"Retry-After": "300"})
