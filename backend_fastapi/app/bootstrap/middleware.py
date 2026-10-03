"""HTTP middleware classes and registration helpers."""

from __future__ import annotations


import os
import time
import uuid
from collections.abc import Iterable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import structlog

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware

from ..utils.client_ip import _is_trusted_peer, resolve_client_ip
from ..utils.rate_limiter import RateLimitMiddleware
from ..utils.structured_logging import bind_request_context, clear_request_context
from ..utils.csrf_middleware import CSRFMiddleware
from ..services.maintenance import MaintenanceModeMiddleware
from .backpressure import BackpressureMiddleware
from .geolock_middleware import GeolockMiddleware
from .metrics import add_prometheus_middleware, record_legacy_alias
from .timeout import TimeoutMiddleware

logger = structlog.get_logger("backend_fastapi.app")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that logs every request and response, and injects a request_id context var."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = (request.headers.get("X-Request-ID") or "").strip()
        if not request_id:
            request_id = str(uuid.uuid4())

        clear_request_context()
        request.state.request_id = request_id

        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"

        bind_request_context(request_id=request_id, path=path, method=request.method)
        logger.info("http_request_start")
        start_time = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            logger.exception(
                "Unhandled exception while processing request",
                method=request.method,
                path=path,
            )
            raise
        finally:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                "http_request_end",
                status_code=status_code,
                duration_ms=round(duration_ms, 2),
            )
            clear_request_context()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security headers on every response (SRS 1H.2).

    CSP is intentionally strict for an API backend: this service serves JSON
    (and the OpenAPI/Swagger UI at /docs), never application HTML, so
    ``default-src 'none'`` is safe and does not need per-route tuning. Swagger
    UI's inline assets are exempted narrowly rather than loosening the policy
    globally.
    """

    _SWAGGER_PATHS = ("/docs", "/redoc")

    def __init__(self, app, *, hsts_max_age: int | None = None) -> None:
        super().__init__(app)
        # Strict-Transport-Security is only meaningful (and only safe) when
        # the deployment actually terminates TLS. It is keyed off the same
        # setting that flips the auth cookies to Secure, so the two can never
        # disagree. 0 disables the header.
        self.hsts_max_age = (
            hsts_max_age
            if hsts_max_age is not None
            else int(os.getenv("HSTS_MAX_AGE_SECONDS", "31536000"))
        )

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)

        if self.hsts_max_age > 0:
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={self.hsts_max_age}; includeSubDomains",
            )

        if request.url.path.startswith(self._SWAGGER_PATHS):
            # FastAPI's bundled Swagger/Redoc UI needs inline scripts/styles
            # and CDN assets; scope the relaxed policy to those two paths only.
            csp = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
                "img-src 'self' data: fastapi.tiangolo.com; "
                "font-src 'self' data:"
            )
        else:
            csp = "default-src 'none'; frame-ancestors 'none'"

        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response


class LegacyApiAliasDeprecationMiddleware(BaseHTTPMiddleware):
    """Flag requests hitting the undocumented legacy route aliases.

    Every route is mounted three times: the canonical ``/api/v1/...``, plus a
    no-prefix alias and an ``/api/...`` alias kept for backward compatibility
    (see ``bootstrap/routers.register_api_routes``). This tags traffic on the
    two legacy aliases with a log line and standard deprecation headers so
    real usage can be measured before either alias is ever removed — it does
    not change the response body or status.
    """

    _EXEMPT_PREFIXES = (
        "/docs",
        "/redoc",
        "/openapi.json",
        "/health",
        "/healthz",
        "/metrics",
        "/sitemap.xml",
        "/rss.xml",
        "/feed.xml",
    )

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)

        path = request.url.path
        if path == "/" or path.startswith(self._EXEMPT_PREFIXES):
            return response
        if path.startswith("/api/v1/"):
            return response
        # Only tag requests that actually matched an application route.
        if request.scope.get("route") is None:
            return response

        if path.startswith("/api/"):
            alias = "api-prefix"
            canonical = f"/api/v1{path[len('/api'):]}"
        else:
            alias = "no-prefix"
            canonical = f"/api/v1{path}"

        record_legacy_alias(alias, request)
        logger.warning(
            "legacy_api_alias_used",
            alias=alias,
            path=path,
            canonical=canonical,
        )
        response.headers["Deprecation"] = "true"
        response.headers["Link"] = f'<{canonical}>; rel="successor-version"'
        return response


class ForwardedHeadersMiddleware(BaseHTTPMiddleware):
    """Minimal middleware that respects common proxy forwarding headers.

    ``X-Forwarded-For`` is only honored via ``resolve_client_ip`` -- which
    checks the immediate peer against a trusted-proxy allowlist and reads
    the last (proxy-attested) hop rather than the first (client-controlled)
    one. See ``utils/client_ip.py`` for why: blindly trusting the first hop
    let any caller forge its own rate-limit identity and audit-log IP.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        scope = request.scope
        headers = request.headers

        # Scheme, host and port are believed only from our own proxy, like
        # the client address: anyone else reaching the backend port could
        # otherwise claim https or another host (plan.md P2-2).
        peer_ip = scope["client"][0] if scope.get("client") else None
        if not _is_trusted_peer(peer_ip):
            return await call_next(request)

        forwarded_proto = headers.get("x-forwarded-proto")
        if forwarded_proto:
            scope["scheme"] = forwarded_proto.split(",")[0].strip()

        client_ip = resolve_client_ip(request)
        if client_ip and client_ip != "unknown":
            port = None
            if scope.get("client"):
                port = scope["client"][1]
            scope["client"] = (client_ip, port)

        forwarded_host = headers.get("x-forwarded-host")
        forwarded_port = headers.get("x-forwarded-port")
        if forwarded_host:
            host_value = forwarded_host.split(",")[0].strip()
            port = None
            if forwarded_port:
                try:
                    port = int(forwarded_port.split(",")[0].strip())
                except (TypeError, ValueError):
                    port = None
            elif scope.get("server"):
                port = scope["server"][1]
            scope["server"] = (host_value, port)

        return await call_next(request)


def sanitize_origins(*candidates: Iterable[str | None]) -> list[str]:
    """Return a unique list of origins with trailing slashes removed."""

    origins: list[str] = []
    for collection in candidates:
        for value in collection:
            if value is None:
                continue
            origin = value.strip()
            if not origin:
                continue
            if origin.endswith("/"):
                origin = origin.rstrip("/")
            if origin not in origins:
                origins.append(origin)
    return origins


class LiveCORSMiddleware(CORSMiddleware):
    """CORS that follows the Secret Vault's website domain without a restart.

    The origin list is fixed when the app starts; after the main admin changes
    the domain, the vault updates the live settings, and this re-resolves the
    list so the new origin is accepted immediately.
    """

    def is_allowed_origin(self, origin: str) -> bool:
        if super().is_allowed_origin(origin):
            return True
        try:
            from ..core.settings import get_settings

            live, credentials = resolve_cors_configuration(get_settings())
        except Exception:  # pragma: no cover - never break a request over CORS
            return False
        return credentials and origin.rstrip("/") in live


def resolve_cors_configuration(settings) -> tuple[list[str], bool]:
    """Compute CORS origins and credentials policy from settings and env."""

    allowed_origins = settings.cors_allowed_origins
    if allowed_origins is None:
        allowed_origins = sanitize_origins(
            (
                (settings.allowed_origins or "").split(",")
                if settings.allowed_origins
                else []
            ),
            [settings.frontend_url] if settings.frontend_url else [],
        )
    else:
        allowed_origins = sanitize_origins(allowed_origins)

    if not allowed_origins:
        logger.info(
            "No CORS origins configured; defaulting to wildcard '*' (credentials disabled)"
        )
        return ["*"], False

    if allowed_origins == ["*"]:
        return allowed_origins, False

    if "*" in allowed_origins:
        logger.warning(
            "CORS origin list contains '*' alongside specific origins; treating as wildcard"
        )
        return ["*"], False

    return allowed_origins, True


def _resolve_rate_limit(value: int | None, fallback_env: str, default: int) -> int:
    if isinstance(value, int):
        return value
    raw = os.getenv(fallback_env)
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "Invalid %s value '%s'; falling back to %s", fallback_env, raw, default
            )
    return default


HEALTH_PROBE_PATHS = frozenset({"/healthz", "/health"})


class HealthExemptHTTPSRedirectMiddleware(HTTPSRedirectMiddleware):
    """HTTPS redirect that never redirects container liveness probes.

    The docker-compose backend healthcheck calls http://localhost:8000/healthz
    from *inside* the container, bypassing the TLS-terminating proxy, so no
    X-Forwarded-Proto is present and the plain HTTPSRedirectMiddleware answers
    307 -> https://localhost:8000/healthz. urllib follows that redirect into a
    TLS handshake against a plain-HTTP port, raises, and the healthcheck exits
    non-zero -- so the backend never reports healthy and every service gated on
    ``condition: service_healthy`` (web/nginx, all celery workers, celery beat)
    refuses to start. Exempting the two probe paths keeps the redirect for all
    real traffic while letting the probe answer 200 over loopback HTTP.
    """

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") in HEALTH_PROBE_PATHS:
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


def configure_middleware(app: FastAPI, settings) -> list[str]:
    """Attach common middleware stack and return allowed CORS origins.

    Intended runtime order, outermost (first to see a request, last to touch
    the response) to innermost::

        CORS -> SecurityHeaders -> Prometheus -> Geolock -> ForwardedHeaders ->
        HTTPSRedirect -> Timeout -> Backpressure -> LegacyAlias -> Logging ->
        GZip -> MaintenanceMode -> CSRF -> RateLimit -> router

    Starlette's ``add_middleware`` *prepends*, so the registration calls below
    run in exactly the reverse of that list -- read them bottom-up.

    Two placements are load-bearing:

    * **CORS is outermost.** Anything it wraps can short-circuit a request
      (RateLimit 429s, Timeout 504s, Backpressure 503s) and those responses
      must still carry ``Access-Control-Allow-Origin``; otherwise the browser
      reports an opaque network error instead of the real status.
    * **HTTPSRedirect sits inside ForwardedHeaders.** It decides on
      ``scope["scheme"]``, and only ForwardedHeaders populates that from
      ``X-Forwarded-Proto``. Outside it, every request behind a
      TLS-terminating proxy looks like plain HTTP and gets redirected to a URL
      that redirects again -- an infinite loop.
    """

    allowed_origins, allow_credentials = resolve_cors_configuration(settings)

    rate_limit_count = _resolve_rate_limit(
        getattr(settings, "generic_rate_limit_requests", None),
        "GENERIC_RATE_LIMIT_REQUESTS",
        300,
    )
    rate_limit_window = _resolve_rate_limit(
        getattr(settings, "generic_rate_limit_window", None),
        "GENERIC_RATE_LIMIT_WINDOW",
        60,
    )

    if rate_limit_count > 0 and rate_limit_window > 0:
        app.add_middleware(
            RateLimitMiddleware,
            limit=rate_limit_count,
            window_seconds=rate_limit_window,
        )

        logger.info(
            "Generic rate limiter enabled (limit=%s requests, window=%ss)",
            rate_limit_count,
            rate_limit_window,
        )
    else:
        logger.info(
            "Generic rate limiter disabled (limit=%s, window=%s)",
            rate_limit_count,
            rate_limit_window,
        )

    app.add_middleware(CSRFMiddleware)
    app.add_middleware(MaintenanceModeMiddleware)
    app.add_middleware(GZipMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(LegacyApiAliasDeprecationMiddleware)

    max_concurrency = int(os.getenv("FASTAPI_MAX_CONCURRENCY", "500"))
    app.add_middleware(BackpressureMiddleware, max_concurrency=max_concurrency)

    # C3: long-running OCR/translation routes are exempt from the short global
    # timeout and bounded by their own generous ceiling instead of returning
    # spurious 504s. Both values are env-configurable.
    global_timeout = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5.0"))
    long_timeout_env = os.getenv("LONG_REQUEST_TIMEOUT_SECONDS", "120")
    exempt_timeout = float(long_timeout_env) if long_timeout_env else None
    app.add_middleware(
        TimeoutMiddleware,
        timeout_seconds=global_timeout,
        exempt_timeout_seconds=exempt_timeout,
    )

    if settings.force_https_redirects:
        app.add_middleware(HealthExemptHTTPSRedirectMiddleware)

    # Must wrap HTTPSRedirect: it rewrites scope["scheme"] from
    # X-Forwarded-Proto, which is what stops the redirect loop behind a
    # TLS-terminating proxy.
    app.add_middleware(ForwardedHeadersMiddleware)

    # Geolock: refuse blocked countries before any other work, inside CORS and
    # the security headers so the 451 still carries both.
    app.add_middleware(GeolockMiddleware)

    add_prometheus_middleware(app)

    # Security headers land on every response, including the error responses
    # produced by the layers below (SRS 1H.2). HSTS is emitted only where TLS
    # is actually terminated — the same switch that makes the auth cookies
    # Secure — so a plain-HTTP dev/staging box never pins itself to HTTPS.
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_max_age=(
            None
            if settings.force_https_redirects
            else 0
        ),
    )

    # Outermost: CORS headers must be attached to short-circuit responses
    # (429/503/504) too, or the browser sees an opaque network error.
    app.add_middleware(
        LiveCORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    return allowed_origins
