import anyio
import structlog
from starlette.responses import JSONResponse

from ..core.api_errors import ErrorCode, error_body

logger = structlog.get_logger("backend_fastapi.backpressure")


class BackpressureMiddleware:
    """
    Global concurrency limiter to shed load when the system is saturated.
    If the number of concurrent in-flight requests exceeds the limit,
    new requests are instantly rejected with a 503 status code.

    Pure ASGI: it sits on every request, and a ``BaseHTTPMiddleware`` layer
    costs a task and a stream per request.
    """

    def __init__(self, app, max_concurrency: int = 500):
        self.app = app
        self.max_concurrency = max_concurrency
        self._semaphore = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if self._semaphore is None:
            self._semaphore = anyio.Semaphore(self.max_concurrency)

        from ..core.test_mode import test_mode_active

        if test_mode_active():
            await self.app(scope, receive, send)
            return

        try:
            self._semaphore.acquire_nowait()
        except anyio.WouldBlock:
            logger.warning(
                "backpressure_shedding_request",
                path=scope.get("path"),
                max_concurrency=self.max_concurrency,
            )
            response = JSONResponse(
                error_body(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "System is currently overloaded. Please try again later.",
                ),
                status_code=503,
                headers={"Retry-After": "5"},
            )
            await response(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            self._semaphore.release()
