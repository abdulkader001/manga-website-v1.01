"""Fetch remote URLs over a connection pinned to a pre-validated IP address.

``services.url_guard`` resolves a hostname and rejects it if any answer is
loopback/private/link-local/reserved/multicast, and ``scrapers.http_client``
re-runs that check on every redirect hop. Both are correct, and both are
defeated by the same gap: validation and the fetch performed *two independent
DNS lookups*. A domain served with a 0-second TTL can answer the validating
lookup with a public address and answer the connecting lookup a few
milliseconds later with ``169.254.169.254``. The check passes; the socket lands
on the cloud metadata service.

This module closes the window by resolving once and connecting to the address
that was actually validated, while keeping the request's TLS identity intact:

* the socket connects to the pinned IP,
* SNI and certificate hostname verification still use the real hostname,
* the ``Host`` header still carries the real hostname (and port).

Pinning is purely additive. Every request still goes through the full
``url_guard`` validation first, and redirects are still re-validated hop by hop
by the caller -- pinning only removes the attacker's ability to change the
answer between the check and the connection.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter

__all__ = [
    "PinnedIPAdapter",
    "PinnedConnectionError",
    "ResponseTooLarge",
    "DEFAULT_MAX_FETCH_BYTES",
    "build_pinned_session",
    "get_pinned",
    "get_pinned_following_redirects",
]

# Validator signature: ``(url) -> (error_message_or_None, validated_addresses)``.
Validator = Callable[[str], "tuple[Optional[str], tuple[str, ...]]"]

# Fallback ceiling for callers that don't pass their own ``max_bytes`` (e.g. the
# HTML fetches in scrapers/http_client.py). Callers downloading something with
# a known, tighter size expectation -- a remote OCR image, say -- should pass
# their own limit instead of relying on this default.
DEFAULT_MAX_FETCH_BYTES = int(
    os.getenv("SSRF_FETCH_MAX_BYTES", str(20 * 1024 * 1024))
)
_CHUNK_SIZE = 64 * 1024


class PinnedConnectionError(requests.exceptions.ConnectionError):
    """Raised when none of the validated addresses could be connected to."""


class ResponseTooLarge(requests.exceptions.RequestException):
    """Raised when a response body exceeds its configured byte ceiling.

    Raised while the body is still streaming in -- the oversized remainder is
    never pulled into memory, unlike a check performed against ``len(content)``
    after ``requests`` has already buffered the whole thing.
    """


def _format_host_for_url(address: str) -> str:
    """Return ``address`` in the form a URL netloc expects (IPv6 bracketed)."""

    if isinstance(ipaddress.ip_address(address), ipaddress.IPv6Address):
        return f"[{address}]"
    return address


class PinnedIPAdapter(HTTPAdapter):
    """``HTTPAdapter`` that dials a fixed IP but keeps the hostname identity.

    ``server_hostname``/``assert_hostname`` are handed to urllib3's connection
    pool so TLS still negotiates SNI for -- and validates the certificate
    against -- the original hostname even though the URL passed down carries
    the IP. Dropping either of those would turn IP pinning into a downgrade of
    certificate verification, which is exactly what this must not do.
    """

    def __init__(self, hostname: str, address: str, **kwargs) -> None:
        self._pinned_hostname = hostname
        self._pinned_address = address
        super().__init__(**kwargs)

    def init_poolmanager(self, *args, **kwargs):  # type: ignore[override]
        kwargs.setdefault("server_hostname", self._pinned_hostname)
        kwargs.setdefault("assert_hostname", self._pinned_hostname)
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):  # type: ignore[override]
        # A proxy terminates the connection on our behalf and does its own DNS
        # resolution, so the pin cannot be honored. Refuse rather than silently
        # fetching through an unvalidated path.
        raise PinnedConnectionError(
            "Refusing to fetch a pinned URL through an HTTP proxy: "
            "the proxy would re-resolve the hostname, defeating IP pinning."
        )

    def send(self, request, **kwargs):  # type: ignore[override]
        parts = urlsplit(request.url)
        netloc = _format_host_for_url(self._pinned_address)
        if parts.port is not None:
            netloc = f"{netloc}:{parts.port}"

        # Preserve the Host header the origin expects; without this http.client
        # would derive it from the connection and send the bare IP.
        original_host = parts.netloc
        request.headers["Host"] = original_host
        request.url = urlunsplit(
            (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
        )
        return super().send(request, **kwargs)


def build_pinned_session(url: str, address: str) -> requests.Session:
    """Return a ``Session`` whose only mount pins ``url``'s host to ``address``."""

    parts = urlsplit(url)
    hostname = (parts.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("URL must include a host to pin")

    session = requests.Session()
    # Mount for both schemes so a caller reusing the session cannot accidentally
    # fall back to the default, unpinned adapter.
    adapter = PinnedIPAdapter(hostname, address)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    # Redirects are re-validated by the caller, one hop at a time.
    session.max_redirects = 0
    # requests honors HTTP_PROXY/HTTPS_PROXY from the environment by default,
    # which would route around the pin. See ``proxy_manager_for``.
    session.trust_env = False
    # trust_env also gates the CA bundle environment variables, so carry those
    # over explicitly -- turning off proxy discovery must not quietly fall back
    # to a different trust store than the rest of the app uses.
    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get(
        "CURL_CA_BUNDLE"
    )
    if ca_bundle:
        session.verify = ca_bundle
    return session


def _consume_within_limit(response: requests.Response, max_bytes: int) -> None:
    """Read ``response`` incrementally, aborting once ``max_bytes`` is exceeded.

    Populates ``response._content``/``_content_consumed`` the same way
    ``requests`` would after a non-streaming request, so callers can keep
    using ``response.content``/``response.text`` unchanged -- the only
    difference is that a body larger than ``max_bytes`` never finishes
    downloading, let alone gets fully buffered first.
    """

    chunks = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
            if not chunk:
                continue
            chunks.extend(chunk)
            if len(chunks) > max_bytes:
                raise ResponseTooLarge(
                    f"Response body for {response.url} exceeded the "
                    f"{max_bytes}-byte limit"
                )
    finally:
        response.close()
    response._content = bytes(chunks)
    response._content_consumed = True


def get_pinned(
    url: str,
    validator: Validator,
    *,
    method: str = "GET",
    timeout: float | int = 15,
    headers: Optional[dict] = None,
    max_bytes: Optional[int] = None,
    **kwargs,
) -> requests.Response:
    """Validate ``url``, then fetch it over a connection pinned to a checked IP.

    ``validator`` is one of ``url_guard``'s ``*_resolved`` functions. Its error
    message is raised as ``requests.exceptions.InvalidURL`` so callers can keep
    treating a rejected URL the same way they already do.

    Redirects are never followed here: the caller re-validates each hop and
    calls back in, so every hop gets its own resolution, its own SSRF check and
    its own pin.

    The response body is streamed in and checked against ``max_bytes``
    (``DEFAULT_MAX_FETCH_BYTES`` if not given) as it arrives, raising
    :class:`ResponseTooLarge` before an oversized body is ever fully buffered.
    """

    error, addresses = validator(url)
    if error:
        raise requests.exceptions.InvalidURL(f"SSRF Check Failed: {error} for url {url}")
    if not addresses:
        raise requests.exceptions.InvalidURL(
            f"SSRF Check Failed: Failed to resolve host for url {url}"
        )

    effective_max_bytes = DEFAULT_MAX_FETCH_BYTES if max_bytes is None else max_bytes

    kwargs.pop("allow_redirects", None)
    # Always stream: _consume_within_limit is what actually reads the body, so
    # it -- not requests -- decides when enough bytes have arrived to stop.
    kwargs["stream"] = True

    last_error: Optional[Exception] = None
    for address in addresses:
        session = build_pinned_session(url, address)
        try:
            response = session.request(
                method,
                url,
                timeout=timeout,
                headers=headers,
                allow_redirects=False,
                **kwargs,
            )
            _consume_within_limit(response, effective_max_bytes)
            return response
        except ResponseTooLarge:
            # The size ceiling, not connectivity, failed -- every other
            # validated address would hit the same oversized resource, so
            # retrying them would only waste a connection each.
            raise
        except requests.exceptions.SSLError:
            # Certificate/hostname verification failed. That is a hard failure,
            # not an unreachable address -- retrying other IPs would only hide
            # it, and never turns into a success.
            raise
        except requests.exceptions.ConnectionError as exc:
            # Try the next validated address; a multi-homed host is allowed to
            # have some addresses unreachable. Every candidate here already
            # passed the SSRF check, so failing over stays inside the checked
            # set.
            last_error = exc
            continue
        finally:
            session.close()

    raise PinnedConnectionError(
        f"Could not connect to any validated address for {url}"
    ) from last_error


def get_pinned_following_redirects(
    url: str,
    validator: Validator,
    *,
    timeout: float | int = 15,
    max_redirects: int = 5,
    headers: Optional[dict] = None,
    max_bytes: Optional[int] = None,
    **kwargs,
) -> requests.Response:
    """Follow redirects manually, re-validating and re-pinning every hop.

    ``requests``' own redirect handling would resolve each ``Location`` itself,
    which is precisely the unchecked lookup this module exists to prevent. Each
    hop therefore goes back through :func:`get_pinned`: fresh SSRF validation,
    fresh resolution, fresh pin. ``max_bytes`` (see :func:`get_pinned`) applies
    to each hop's body independently.
    """

    current_url = url
    for _ in range(max_redirects + 1):
        response = get_pinned(
            current_url,
            validator,
            timeout=timeout,
            headers=headers,
            max_bytes=max_bytes,
            **kwargs,
        )
        if not response.is_redirect:
            return response

        location = response.headers.get("Location")
        if not location:
            # A redirect status with no target; nothing safe to follow.
            return response
        current_url = urljoin(current_url, location)

    raise requests.exceptions.TooManyRedirects(f"Exceeded {max_redirects} redirects.")
