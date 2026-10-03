"""Standard API error registry and response envelope (SRS 1B.4).

Every API error carries a machine-readable ``code`` and a human-readable
``message`` inside a consistent envelope (SRS 1B.4.2). A bare HTTP status with an
empty body is never acceptable — this module is what kills the historical
"unusable 422" failures (SRS 1B.4.2).

The success and error envelope shapes:

    success: {"success": true,  "data": {...}, "meta": {...}?}
    error:   {"success": false, "error": {"code","message","field"?,"details"?}}
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class ErrorCode(str, Enum):
    """The complete Part 1 error-code registry (SRS 1B.4.3).

    Each member's ``.status`` is the HTTP status the code maps to. Codes are the
    stable machine contract; messages are human-facing and may be refined.
    """

    UNAUTHENTICATED = ("UNAUTHENTICATED", 401)
    SESSION_EXPIRED = ("SESSION_EXPIRED", 401)
    REVERIFICATION_REQUIRED = ("REVERIFICATION_REQUIRED", 403)
    FORBIDDEN = ("FORBIDDEN", 403)
    LOGIN_REQUIRED_FOR_PROCESSING = ("LOGIN_REQUIRED_FOR_PROCESSING", 403)
    # The main admin switched the site to members-only.
    LOGIN_REQUIRED = ("LOGIN_REQUIRED", 401)
    # The owner switched this website function off (Admin -> Site Functions).
    FUNCTION_DISABLED = ("FUNCTION_DISABLED", 403)
    VALIDATION_FAILED = ("VALIDATION_FAILED", 422)
    NOT_FOUND = ("NOT_FOUND", 404)
    WEBSITE_NOT_APPROVED = ("WEBSITE_NOT_APPROVED", 422)
    DUPLICATE_MANGA_URL = ("DUPLICATE_MANGA_URL", 409)
    SCRAPER_UNAVAILABLE = ("SCRAPER_UNAVAILABLE", 503)
    SCRAPER_EXTRACTION_FAILED = ("SCRAPER_EXTRACTION_FAILED", 502)
    PERMANENT_ADMIN_IMMUTABLE = ("PERMANENT_ADMIN_IMMUTABLE", 403)
    DISPOSABLE_EMAIL_REJECTED = ("DISPOSABLE_EMAIL_REJECTED", 403)
    MAGIC_LINK_EXPIRED = ("MAGIC_LINK_EXPIRED", 401)
    MAGIC_LINK_ALREADY_USED = ("MAGIC_LINK_ALREADY_USED", 401)
    MAGIC_LINK_INVALID = ("MAGIC_LINK_INVALID", 401)
    MAGIC_LINK_DEVICE_MISMATCH = ("MAGIC_LINK_DEVICE_MISMATCH", 403)
    RATE_LIMITED = ("RATE_LIMITED", 429)
    QUOTA_EXCEEDED = ("QUOTA_EXCEEDED", 429)
    PROVIDER_FAILED = ("PROVIDER_FAILED", 502)
    NOT_IMPLEMENTED = ("NOT_IMPLEMENTED", 501)
    # Content rights (SRS 1J) — not in the 1B.4.3 table but part of the same
    # registry so rights rejections carry a stable machine code too.
    CONTENT_HOST_FORBIDDEN = ("CONTENT_HOST_FORBIDDEN", 403)
    CONTENT_TRANSLATE_FORBIDDEN = ("CONTENT_TRANSLATE_FORBIDDEN", 403)
    CONTENT_TAKEN_DOWN = ("CONTENT_TAKEN_DOWN", 451)
    # Geolock: the main admin closed the site to the visitor's country.
    REGION_BLOCKED = ("REGION_BLOCKED", 451)
    # Community (Part 3)
    COMMUNITY_BLOCKED = ("COMMUNITY_BLOCKED", 403)
    COMMUNITY_TIMED_OUT = ("COMMUNITY_TIMED_OUT", 403)
    SELF_ACTION_FORBIDDEN = ("SELF_ACTION_FORBIDDEN", 403)
    PILL_ALREADY_CLAIMED = ("PILL_ALREADY_CLAIMED", 409)
    # Generic HTTP-status fallbacks used by the global exception handlers
    # (SRS 1B.4.4) for legacy call sites that raise a bare ``HTTPException``
    # or an uncaught error rather than a domain-specific ``ApiError`` code.
    BAD_REQUEST = ("BAD_REQUEST", 400)
    CONFLICT = ("CONFLICT", 409)
    PAYLOAD_TOO_LARGE = ("PAYLOAD_TOO_LARGE", 413)
    BAD_GATEWAY = ("BAD_GATEWAY", 502)
    SERVICE_UNAVAILABLE = ("SERVICE_UNAVAILABLE", 503)
    GATEWAY_TIMEOUT = ("GATEWAY_TIMEOUT", 504)
    INTERNAL_ERROR = ("INTERNAL_ERROR", 500)

    def __new__(cls, value: str, status: int) -> "ErrorCode":
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.status = status
        return obj


class ApiError(Exception):
    """A domain error that renders as the standard error envelope.

    Raise this anywhere in the request path; the registered exception handler
    turns it into the 1B.4.2 error envelope with the code's HTTP status.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        field: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        status: Optional[int] = None,
    ):
        self.code = code
        self.message = message
        self.field = field
        self.details = details
        self.status = status if status is not None else code.status
        super().__init__(message)

    def to_body(self) -> dict[str, Any]:
        return error_body(
            self.code, self.message, field=self.field, details=self.details
        )


def error_body(
    code: ErrorCode,
    message: str,
    *,
    field: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the error envelope (SRS 1B.4.2)."""

    error: dict[str, Any] = {"code": code.value, "message": message}
    if field is not None:
        error["field"] = field
    if details is not None:
        error["details"] = details
    return {"success": False, "error": error}


def success_body(data: Any, *, meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Build the success envelope (SRS 1B.4.2)."""

    body: dict[str, Any] = {"success": True, "data": data}
    if meta is not None:
        body["meta"] = meta
    return body


def pagination_meta(page: int, per_page: int, total: int) -> dict[str, int]:
    """Build the ``meta`` pagination block (SRS 1B.4.2 / 1B.4.5)."""

    total_pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }
