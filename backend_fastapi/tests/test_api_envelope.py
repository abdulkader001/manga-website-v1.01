"""Tests for the standard API envelope and error registry (SRS 1B.4)."""

from __future__ import annotations

from backend_fastapi.app.core.api_errors import (
    ApiError,
    ErrorCode,
    error_body,
    pagination_meta,
    success_body,
)


def test_error_code_http_status_registry():
    # A representative sample from the 1B.4.3 table.
    assert ErrorCode.UNAUTHENTICATED.status == 401
    assert ErrorCode.FORBIDDEN.status == 403
    assert ErrorCode.VALIDATION_FAILED.status == 422
    assert ErrorCode.WEBSITE_NOT_APPROVED.status == 422
    assert ErrorCode.DUPLICATE_MANGA_URL.status == 409
    assert ErrorCode.NOT_IMPLEMENTED.status == 501


def test_error_body_shape():
    body = error_body(
        ErrorCode.WEBSITE_NOT_APPROVED,
        "nope",
        field="manga_url",
        details={"domain": "example.com"},
    )
    assert body == {
        "success": False,
        "error": {
            "code": "WEBSITE_NOT_APPROVED",
            "message": "nope",
            "field": "manga_url",
            "details": {"domain": "example.com"},
        },
    }


def test_error_body_omits_optional_fields():
    body = error_body(ErrorCode.FORBIDDEN, "no")
    assert body == {"success": False, "error": {"code": "FORBIDDEN", "message": "no"}}


def test_success_body_with_meta():
    body = success_body([1, 2], meta=pagination_meta(1, 50, 120))
    assert body["success"] is True
    assert body["data"] == [1, 2]
    assert body["meta"] == {
        "page": 1,
        "per_page": 50,
        "total": 120,
        "total_pages": 3,
    }


def test_api_error_carries_status_and_body():
    exc = ApiError(ErrorCode.DUPLICATE_MANGA_URL, "dupe", field="manga_url")
    assert exc.status == 409
    assert exc.to_body()["error"]["code"] == "DUPLICATE_MANGA_URL"


def test_pagination_meta_rounds_up():
    assert pagination_meta(1, 50, 0)["total_pages"] == 0
    assert pagination_meta(1, 50, 1)["total_pages"] == 1
    assert pagination_meta(1, 50, 50)["total_pages"] == 1
    assert pagination_meta(1, 50, 51)["total_pages"] == 2
