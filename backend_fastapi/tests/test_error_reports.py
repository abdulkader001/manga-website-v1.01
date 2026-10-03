"""Admin -> Error Report: errors are recorded, grouped, explained and private."""

from __future__ import annotations

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import ErrorReport
from backend_fastapi.app.services import error_report_service as reports
from _support import staff

URL = "/api/v1/admin/error-reports"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _clean():
    staff.reset_staff()
    with SessionLocal() as session:
        session.query(ErrorReport).delete()
        session.commit()
    yield
    staff.reset_staff()


def _rows():
    with SessionLocal() as session:
        return session.query(ErrorReport).all()


# ------------------------------------------------------------------ diagnosis


@pytest.mark.parametrize(
    "source, kind, message, category",
    [
        ("server", "OperationalError", 'relation "error_reports" does not exist', "database"),
        ("server", "OperationalError", "could not connect to server: Connection refused", "database"),
        ("server", "ConnectionError", "Error 111 connecting to redis:6379. Connection refused.", "redis"),
        ("server", "OSError", "[Errno 28] No space left on device", "server"),
        ("server", "PROVIDER_FAILED", "Provider openai answered 401: invalid_api_key", "provider"),
        ("server", "SCRAPER_EXTRACTION_FAILED", "No chapters found on the page", "scraper"),
        ("server", "AttributeError", "'NoneType' object has no attribute 'title'", "code"),
        ("worker", "SMTPAuthenticationError", "(535, b'Authentication unsuccessful')", "email"),
        ("browser", "ChunkLoadError", "Loading chunk 42 failed.", "update"),
        ("browser", "TypeError", "Failed to fetch", "network"),
        ("browser", "TypeError", "Cannot read properties of undefined (reading 'map')", "code"),
        ("browser", "Error", "ResizeObserver loop limit exceeded", "harmless"),
        ("browser", "Error", "Script error.", "extension"),
        ("server", "KeyError", "'DATABASE_READ_URL'", "config"),
        ("server", "WeirdError", "something nobody expected", "unknown"),
    ],
)
def test_each_error_gets_a_plain_cause_and_fix(source, kind, message, category):
    got, cause, fix = reports.diagnose(source, kind, message, None)
    assert got == category
    assert cause and fix


def test_a_line_number_in_the_stack_is_not_read_as_an_http_status():
    stack = 'File "app/x.py", line 429, in f\n  File "app/y.py", line 502, in g'
    assert reports.diagnose("server", "KeyError", "'title'", stack)[0] == "code"


# ------------------------------------------------------------------ privacy


def test_emails_ips_and_tokens_are_masked_before_saving():
    reports.record(
        source="server",
        kind="ValueError",
        message="bad user reader@example.com from 203.0.113.9 token=abc123 Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlc2ln",
        location="GET /api/v1/auth/magic/verify?token=secret&code=123",
        stack="postgresql://admin:hunter2@db:5432/manga",
    )
    (row,) = _rows()
    text = f"{row.message} {row.location} {row.stack}"
    for leaked in ("reader@example.com", "203.0.113.9", "abc123", "eyJhbGci", "hunter2", "secret", "code=123"):
        assert leaked not in text, leaked
    assert row.location == "GET /api/v1/auth/magic/verify"


# ------------------------------------------------------------------ grouping


def test_the_same_error_is_one_row_with_a_count_and_comes_back_when_it_repeats():
    for n in (1, 2, 3):
        reports.record(source="server", kind="KeyError", message=f"'chapter {n}'", location="GET /manga/{id}")
    (row,) = _rows()
    assert row.count == 3
    with SessionLocal() as session:
        session.get(ErrorReport, row.id).resolved = True
        session.commit()
    reports.record(source="server", kind="KeyError", message="'chapter 9'", location="GET /manga/{id}")
    (row,) = _rows()
    assert row.count == 4 and row.resolved is False


def test_unhandled_server_exceptions_are_recorded(fastapi_app):
    from fastapi.testclient import TestClient

    @fastapi_app.get("/__boom_for_error_report")
    def _boom():
        raise RuntimeError("database is locked")

    with TestClient(fastapi_app, raise_server_exceptions=False) as client:
        assert client.get("/__boom_for_error_report").status_code == 500
    (row,) = _rows()
    assert row.source == "server" and row.kind == "RuntimeError"
    assert row.location == "GET /__boom_for_error_report"
    assert "RuntimeError" in (row.stack or "")


# ------------------------------------------------------------------ browser reports


def test_anyone_can_report_a_browser_error(fastapi_client):
    resp = fastapi_client.post(
        "/api/v1/errors/report",
        json={"kind": "TypeError", "message": "x is not a function", "page": "/manga/12?ref=abc", "stack": "at f (app.js:1:2)"},
    )
    assert resp.status_code == 202, resp.text
    (row,) = _rows()
    assert row.source == "browser" and row.location == "/manga/12" and row.category == "code"


# ------------------------------------------------------------------ who sees it


def test_owner_and_admins_see_the_report_sub_admins_and_readers_do_not(fastapi_client):
    reports.record(source="server", kind="KeyError", message="'x'")
    for who, code in ((staff.owner(), 200), (staff.admin(), 200), (staff.sub_admin(), 403), (staff.reader(), 403)):
        resp = fastapi_client.get(URL, headers=staff.headers(who))
        assert resp.status_code == code, (who, resp.text)
    body = fastapi_client.get(URL, headers=staff.headers(staff.owner())).json()
    assert body["summary"]["open"] == 1
    item = body["items"][0]
    assert item["cause"] and item["fix"] and item["count"] == 1


def test_mark_fixed_reopen_and_clear(fastapi_client):
    rid = reports.record(source="browser", kind="Error", message="Script error.")
    h = staff.headers(staff.owner())
    assert fastapi_client.post(f"{URL}/{rid}/resolve", headers=h).json()["resolved"] is True
    assert fastapi_client.get(URL, headers=h).json()["items"] == []
    assert len(fastapi_client.get(URL, params={"status": "resolved"}, headers=h).json()["items"]) == 1
    assert fastapi_client.post(f"{URL}/{rid}/reopen", headers=h).json()["resolved"] is False
    fastapi_client.post(f"{URL}/{rid}/resolve", headers=h)
    assert fastapi_client.delete(f"{URL}/resolved", headers=h).json() == {"removed": 1}
    assert _rows() == []
    assert fastapi_client.post(f"{URL}/{rid}/resolve", headers=h).status_code == 404
