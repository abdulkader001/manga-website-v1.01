"""Double-submit-cookie CSRF protection (C6).

The previous implementation only checked that *some* ``X-CSRF-Token`` header was
present when cookie auth was in use — it never validated the value, so any
attacker-supplied header passed. This validates the header against a
server-issued ``csrf_token`` cookie using a constant-time comparison
(double-submit-cookie pattern).

Auth via the ``Authorization`` header is exempt: bearer tokens are not sent
automatically by browsers, so they carry no CSRF risk. Only cookie-authenticated
state-changing requests are checked.
"""

import secrets

import structlog
from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..core.api_errors import ErrorCode, error_body
from ..core.settings import settings

logger = structlog.get_logger("csrf")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "x-csrf-token"
ACCESS_COOKIE = "access_token_cookie"


def _uses_cookie_auth(request: Request) -> bool:
    """True when the request authenticates via cookie rather than a bearer token."""

    if request.headers.get("Authorization"):
        return False
    return bool(request.cookies.get(ACCESS_COOKIE))


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method.upper() not in SAFE_METHODS and _uses_cookie_auth(request):
            header_token = request.headers.get(CSRF_HEADER)
            cookie_token = request.cookies.get(CSRF_COOKIE)
            if (
                not header_token
                or not cookie_token
                or not secrets.compare_digest(header_token, cookie_token)
            ):
                logger.warning(
                    "csrf_validation_failed",
                    path=request.url.path,
                    has_header=bool(header_token),
                    has_cookie=bool(cookie_token),
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content=error_body(ErrorCode.FORBIDDEN, "CSRF validation failed"),
                )

        response = await call_next(request)

        # Seed a CSRF token for clients that don't have one yet, on safe requests
        # only (so we never clobber a token mid-transaction). The value is stable
        # once set because subsequent requests carry the cookie.
        if (
            request.method.upper() in SAFE_METHODS
            and request.cookies.get(CSRF_COOKIE) is None
        ):
            response.set_cookie(
                CSRF_COOKIE,
                secrets.token_urlsafe(32),
                httponly=False,  # must be readable by JS to echo in the header
                secure=bool(settings.force_https_redirects),
                samesite="lax",
            )

        return response
