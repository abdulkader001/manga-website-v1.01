"""Regression tests for F-62: client IP must not be spoofable via
X-Forwarded-For.

Before the fix, three call sites (ForwardedHeadersMiddleware,
RateLimitMiddleware._identify_requester, log_admin_action) each trusted the
first comma-separated value of X-Forwarded-For unconditionally -- a value
fully controlled by the caller. That let any client pick a fresh rate-limit
bucket for free (defeating progressive backoff) and forge the source_ip
recorded in admin_audit_logs.

These tests build raw ASGI scopes directly rather than going through
TestClient, since TestClient's default peer address ("testclient") isn't a
real IP and would obscure exactly the peer-trust logic being tested.
"""

from __future__ import annotations

import uuid

import pytest
from starlette.requests import Request

from backend_fastapi.app.utils.client_ip import resolve_client_ip
from backend_fastapi.app.utils.rate_limiter import RateLimitMiddleware
from backend_fastapi.app.utils.audit_logger import log_admin_action
from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import AdminAuditLog, User, UserRole


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _request(client_host: str, forwarded_for: str | None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope = {
        "type": "http",
        "client": (client_host, 12345),
        "headers": headers,
        "method": "GET",
        "path": "/",
    }
    return Request(scope)


# A real internet client IP -- never inside our trusted (private) ranges,
# and never the peer address of a request that actually passed through our
# own nginx.
UNTRUSTED_PEER = "203.0.113.7"
# Simulates the address of our own reverse proxy, sitting in the docker
# network alongside the backend.
TRUSTED_PEER = "172.20.0.5"


def test_forwarded_header_is_ignored_from_an_untrusted_peer():
    request = _request(UNTRUSTED_PEER, "9.9.9.9")
    assert resolve_client_ip(request) == UNTRUSTED_PEER


def test_forwarded_header_last_hop_is_used_from_a_trusted_peer():
    # Simulates nginx's (pre-fix) append behavior: attacker value first,
    # nginx's own attested value last.
    request = _request(TRUSTED_PEER, "1.2.3.4, 198.51.100.9")
    assert resolve_client_ip(request) == "198.51.100.9"


def test_two_spoofed_headers_from_the_same_untrusted_peer_collide_to_one_identifier():
    """The core rate-limit-bypass regression: distinct forged
    X-Forwarded-For values used to buy a distinct bucket each. They must
    now collapse to the same identifier, since the header is never trusted
    from a non-proxy peer.
    """

    request_a = _request(UNTRUSTED_PEER, "1.1.1.1")
    request_b = _request(UNTRUSTED_PEER, "2.2.2.2")

    identifier_a = RateLimitMiddleware._identify_requester(request_a)
    identifier_b = RateLimitMiddleware._identify_requester(request_b)

    assert identifier_a == identifier_b == UNTRUSTED_PEER


def _admin(session) -> int:
    u = User(
        email=f"f62-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="F62 Admin",
        role=UserRole.ADMIN,
        is_main_admin=True,
        is_secondary_admin=True,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def test_audit_log_source_ip_ignores_forged_header_from_untrusted_peer():
    session = SessionLocal()
    try:
        admin = _admin(session)
        marker = uuid.uuid4().hex[:8]
        request = _request(UNTRUSTED_PEER, "6.6.6.6")

        log_admin_action(
            db=session,
            request=request,
            admin_user=admin,
            action=f"TEST_F62_{marker}",
            target_type="user",
            target_id="123",
            result="success",
        )

        row = (
            session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == f"TEST_F62_{marker}")
            .one()
        )
        assert row.source_ip == UNTRUSTED_PEER
        assert row.source_ip != "6.6.6.6"
    finally:
        session.close()
