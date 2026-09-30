import anyio
import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..core.api_errors import ErrorCode, error_body

logger = structlog.get_logger("backend_fastapi.backpressure")


class BackpressureMiddleware(BaseHTTPMiddleware):
    """
    Global concurrency limiter to shed load when the system is saturated.
    If the number of concurrent in-flight requests exceeds the limit,
    new requests are instantly rejected with a 503 status code.
    """

    def __init__(self, app, max_concurrency: int = 500):
        super().__init__(app)
        self.max_concurrency = max_concurrency
        self._semaphore = None

    async def dispatch(self, request: Request, call_next):
        if self._semaphore is None:
            self._semaphore = anyio.Semaphore(self.max_concurrency)

        from ..core.test_mode import test_mode_active

        if test_mode_active():
            return await call_next(request)

        try:
            self._semaphore.acquire_nowait()
        except anyio.WouldBlock:
            logger.warning(
                "backpressure_shedding_request",
                path=request.url.path,
                max_concurrency=self.max_concurrency,
            )
            return JSONResponse(
                error_body(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "System is currently overloaded. Please try again later.",
                ),
                status_code=503,
                headers={"Retry-After": "5"},
            )

        try:
            return await call_next(request)
        finally:
            self._semaphore.release()
