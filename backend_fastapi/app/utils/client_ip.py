"""Single source of truth for resolving a request's real client IP.

Three call sites (``ForwardedHeadersMiddleware``, ``RateLimitMiddleware``, and
``log_admin_action``) used to each parse ``X-Forwarded-For`` independently,
and all made the same mistake: they trusted the *first* comma-separated
value unconditionally. That value is fully attacker-controlled -- nginx's
``$proxy_add_x_forwarded_for`` appends to whatever the client already sent
rather than replacing it, so a request arriving with
``X-Forwarded-For: 1.2.3.4`` reaches the backend as
``X-Forwarded-For: 1.2.3.4, <real client IP>`` -- and nothing checked that
the immediate peer was actually our own reverse proxy before honoring it.
That let any caller pick its own rate-limit bucket for free and forge the
``source_ip`` recorded in ``admin_audit_logs``.

``resolve_client_ip`` fixes this in one place: the forwarded header is only
honored when the immediate TCP peer is an address we trust (by default,
private/internal ranges only -- i.e. our own nginx sitting in the same
docker network), and even then the *last* hop is used, since that's the one
nginx itself appends and attests to.
"""

from __future__ import annotations

import ipaddress
import os
from functools import lru_cache

from fastapi import Request

# Only internal/private addresses are trusted to relay X-Forwarded-For by
# default -- i.e. our own nginx, reachable only from inside the docker
# network. A request whose immediate peer is a public address (including one
# hitting the backend's published port directly, bypassing nginx entirely)
# never gets its header honored, regardless of content.
_DEFAULT_TRUSTED_PROXY_CIDRS = (
    "127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128"
)


@lru_cache(maxsize=1)
def _trusted_networks() -> tuple[ipaddress._BaseNetwork, ...]:
    raw = os.getenv("TRUSTED_PROXY_CIDRS", _DEFAULT_TRUSTED_PROXY_CIDRS)
    networks: list[ipaddress._BaseNetwork] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            networks.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_peer(peer_ip: str | None) -> bool:
    if not peer_ip:
        return False
    try:
        addr = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(addr in network for network in _trusted_networks())


def resolve_client_ip(request: Request) -> str:
    """Return the client IP this request should be identified by.

    Falls back to the raw TCP peer address whenever the peer isn't a
    trusted proxy, or the header is absent/empty -- never trusts
    client-supplied content without that check.
    """

    peer_ip = request.client.host if request.client else None

    if _is_trusted_peer(peer_ip):
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]

    return peer_ip or "unknown"
