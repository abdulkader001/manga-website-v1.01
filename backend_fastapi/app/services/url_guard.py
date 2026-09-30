"""Network safety helpers ported from the legacy Flask backend."""

from __future__ import annotations

import ipaddress
import os
import socket
from functools import lru_cache
from typing import Iterable, Optional
from urllib.parse import urlparse

__all__ = [
    "validate_remote_image_url",
    "validate_remote_image_url_resolved",
    "validate_scrape_url",
    "validate_scrape_url_resolved",
    "normalize_url",
    "canonicalize_source_url",
]

# Query parameters that never identify a distinct manga page — analytics and
# share-tracking noise stripped during canonicalization (SRS 1G.4.1).
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "referrer",
        "source",
        "spm",
        "share",
    }
)


def canonicalize_source_url(url: str) -> str:
    """Canonical form of a manga source URL for duplicate detection (1G.4.1).

    Collapses the variance the SRS names: protocol (http/https), ``www.`` and
    host case, trailing slashes, tracking parameters, and fragments — so the
    same manga page submitted two slightly different ways is recognized as one.
    Remaining query parameters are kept (sorted) because on some sites they DO
    identify the series (e.g. ``?id=123``).
    """

    from urllib.parse import parse_qsl, urlencode

    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    # Keep only non-default explicit ports.
    port = parsed.port
    if port in (80, 443, None):
        netloc = host
    else:
        netloc = f"{host}:{port}"

    path = parsed.path or ""
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")

    kept_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING_PARAMS:
            continue
        if any(lowered.startswith(p) for p in _TRACKING_PARAM_PREFIXES):
            continue
        kept_params.append((key, value))
    kept_params.sort()

    canonical = f"https://{netloc}{path}"
    if kept_params:
        canonical += "?" + urlencode(kept_params)
    return canonical


@lru_cache(maxsize=1)
def _url_allowlist() -> tuple[str, ...]:
    allowlist_env = os.getenv("OCR_URL_ALLOWLIST", "")
    if not allowlist_env:
        return ()
    items: list[str] = []
    for raw in allowlist_env.split(","):
        cleaned = raw.strip().lower()
        if cleaned:
            items.append(cleaned)
    return tuple(items)


def _is_forbidden_ip(ip_obj: ipaddress._BaseAddress) -> bool:
    return any(
        (
            ip_obj.is_loopback,
            ip_obj.is_private,
            ip_obj.is_link_local,
            ip_obj.is_reserved,
            ip_obj.is_unspecified,
            ip_obj.is_multicast,
        )
    )


def _host_addresses(hostname: str) -> Iterable[str]:
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return []
    for info in addr_info:
        sockaddr = info[4] if len(info) > 4 else None
        if not sockaddr:
            continue
        address = sockaddr[0]
        if "%" in address:
            address = address.split("%", 1)[0]
        yield address


def normalize_url(url: str) -> str:
    """Normalize a URL to ensure consistent formatting."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower() if parsed.scheme else "https"
    netloc = parsed.netloc.lower()
    path = parsed.path
    if path.endswith("/") and len(path) > 1:
        path = path.rstrip("/")

    # Reconstruct
    normalized = f"{scheme}://{netloc}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized


def _check_host_addresses(hostname: str) -> tuple[Optional[str], tuple[str, ...]]:
    """Resolve ``hostname`` and reject it unless *every* address is public.

    Returns ``(error, addresses)``. On success ``error`` is ``None`` and
    ``addresses`` holds the exact IPs that passed the check -- callers pin the
    connection to one of these so the fetch cannot land on a different address
    than the one that was validated (see ``services/pinned_fetch.py``).
    """

    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        host_ip = None

    if host_ip is not None:
        if _is_forbidden_ip(host_ip):
            return "IP address is not permitted", ()
        return None, (str(host_ip),)

    addresses = list(_host_addresses(hostname))
    if not addresses:
        return "Failed to resolve host", ()

    for addr in addresses:
        try:
            ip_obj = ipaddress.ip_address(addr)
        except ValueError:
            return "Failed to resolve host", ()
        if _is_forbidden_ip(ip_obj):
            return "IP address is not permitted", ()

    return None, tuple(addresses)


def validate_scrape_url_resolved(
    url: str, db_session=None
) -> tuple[Optional[str], tuple[str, ...]]:
    """Like :func:`validate_scrape_url` but also returns the validated IPs.

    See :func:`validate_remote_image_url_resolved` for why callers want them.
    """

    if not url:
        return "URL is required", ()

    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format", ()

    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return "Only http and https URLs are allowed", ()

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return "URL must include a valid host", ()

    # SSRF checks
    if hostname in {"localhost", "127.0.0.1"} or hostname.endswith(".localhost"):
        return "Local addresses are not permitted", ()

    error, addresses = _check_host_addresses(hostname)
    if error:
        return error, ()

    # Domain allowlist check. A website is approved when the Permanent
    # Administrator has saved it; matching accepts the exact host or any
    # subdomain of an approved apex domain (``colamanga.com`` approves
    # ``www.colamanga.com``) so this stays consistent with the ingestion gate
    # in ``manga_service._host_is_approved``.
    if db_session:
        from ..models import ApprovedSourceDomain

        approved = False
        for entry in db_session.query(ApprovedSourceDomain).all():
            domain = (entry.domain or "").strip().lower()
            if not domain:
                continue
            if hostname == domain or hostname.endswith("." + domain):
                approved = True
                break
        if not approved:
            return "Domain is not in the approved allowlist", ()

    return None, addresses


def validate_scrape_url(url: str, db_session=None) -> Optional[str]:
    """Validate that a URL is safe for scraping and is in the domain allowlist.
    Returns ``None`` if safe, or an error message if invalid/forbidden.
    """

    error, _addresses = validate_scrape_url_resolved(url, db_session=db_session)
    return error


def validate_remote_image_url_resolved(
    url: str,
) -> tuple[Optional[str], tuple[str, ...]]:
    """Like :func:`validate_remote_image_url` but also returns the validated IPs.

    Returning the addresses is what closes the DNS-rebinding window: validation
    and the fetch would otherwise be two independent lookups, so a domain with
    a low TTL can answer with a public IP here and ``169.254.169.254`` a
    moment later when the HTTP client resolves it again. Callers pass these
    addresses to ``services.pinned_fetch`` so the socket connects to an address
    that was actually checked.
    """

    if not url:
        return "URL is required", ()

    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL", ()

    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return "Only http and https URLs are allowed", ()

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return "URL must include a valid host", ()

    allowlist = _url_allowlist()
    if allowlist and hostname not in allowlist:
        return "Host is not in the OCR allowlist", ()
    # Blind Spot #11: an allowlisted hostname is NOT exempt from the IP checks
    # below. A hostname allowlist gives no protection against DNS rebinding
    # (the attacker controls what the name resolves to at fetch time), so every
    # host — allowlisted or not — is still resolved and rejected if it maps to a
    # private/loopback/link-local/reserved address.

    if hostname in {"localhost", "127.0.0.1"} or hostname.endswith(".localhost"):
        return "Local addresses are not permitted", ()

    return _check_host_addresses(hostname)


def validate_remote_image_url(url: str) -> Optional[str]:
    """Validate that a remote image URL is safe for server-side fetching.

    Returns ``None`` when the URL is considered safe, or an error message
    describing the first validation issue discovered.
    """

    error, _addresses = validate_remote_image_url_resolved(url)
    return error
