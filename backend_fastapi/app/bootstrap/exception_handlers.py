"""Global exception handlers rendering the standard error envelope (SRS 1B.4).

Every response body an error can produce is emitted from this single module:

  * ``ApiError`` renders as the 1B.4.2 error envelope with the code's status.
  * ``HTTPException`` (FastAPI's and Starlette's — the two are the same class
    hierarchy) is wrapped into the same envelope, mapping its status code to a
    generic ``ErrorCode`` and its ``detail`` into ``message``/``details``.
  * Request validation failures (the historical "bare 422") render as a
    ``VALIDATION_FAILED`` envelope that always names the offending ``field`` and
    a human-readable ``message`` (SRS 1B.4.2 / 1B.4.3).
  * Any other unhandled ``Exception`` renders as a generic 500 envelope. The
    traceback is logged server-side and never reaches the client.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.api_errors import ApiError, ErrorCode, error_body

logger = structlog.get_logger("backend_fastapi.errors")

# Best-effort mapping from a raw HTTP status code (as passed to a legacy
# ``HTTPException(status_code=..., detail=...)`` call) to a generic
# ``ErrorCode``. Routes that need a precise, domain-specific code should raise
# ``ApiError`` directly instead — this table only backstops the remaining
# legacy call sites so every response still carries a stable machine code.
_STATUS_TO_ERROR_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    422: ErrorCode.VALIDATION_FAILED,
    429: ErrorCode.RATE_LIMITED,
    500: ErrorCode.INTERNAL_ERROR,
    501: ErrorCode.NOT_IMPLEMENTED,
    502: ErrorCode.BAD_GATEWAY,
    503: ErrorCode.SERVICE_UNAVAILABLE,
    504: ErrorCode.GATEWAY_TIMEOUT,
}


def _code_for_status(status_code: int) -> ErrorCode:
    code = _STATUS_TO_ERROR_CODE.get(status_code)
    if code is not None:
        return code
    return ErrorCode.BAD_REQUEST if status_code < 500 else ErrorCode.INTERNAL_ERROR


def _first_field(errors: list[dict]) -> str | None:
    """Best-effort field name from a pydantic/validation error list."""

    if not errors:
        return None
    loc = errors[0].get("loc") or []
    # Skip the leading location segment ("body"/"query"/"path") when present.
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) if parts else (str(loc[-1]) if loc else None)


def configure_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=exc.to_body())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        field = _first_field(errors)
        message = errors[0].get("msg") if errors else "Input validation failed"
        return JSONResponse(
            status_code=ErrorCode.VALIDATION_FAILED.status,
            content=error_body(
                ErrorCode.VALIDATION_FAILED,
                str(message) if message else "Input validation failed",
                field=field,
                details={"errors": errors} if errors else None,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException):
        code = _code_for_status(exc.status_code)
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(
                detail.get("message") or detail.get("error") or code.value
            )
            details = detail
        elif detail is None:
            message = code.value.replace("_", " ").title()
            details = None
        else:
            message = str(detail)
            details = None
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message, details=details),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled_exception(request: Request, exc: Exception):
        # Full traceback stays server-side (structured log / Sentry via its
        # own integration); the client only ever sees a generic message.
        logger.exception(
            "Unhandled exception", path=request.url.path, method=request.method
        )
        return JSONResponse(
            status_code=ErrorCode.INTERNAL_ERROR.status,
            content=error_body(
                ErrorCode.INTERNAL_ERROR,
                "An unexpected error occurred. Please try again later.",
            ),
        )
