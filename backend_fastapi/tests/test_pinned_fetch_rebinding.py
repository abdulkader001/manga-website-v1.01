"""DNS-rebinding regression tests for the SSRF-pinned fetcher.

``url_guard`` resolves a hostname and rejects private/link-local answers, but
before IP pinning the *fetch* performed its own second lookup. A domain with a
low TTL could therefore answer the validating lookup with a public address and
the connecting lookup with ``169.254.169.254``, and the request would sail
through every check. These tests simulate exactly that: a resolver whose first
answer is public and whose every later answer is private.
"""

from __future__ import annotations

import socket

import pytest
import requests

from backend_fastapi.app.services import pinned_fetch, url_guard

PUBLIC_IP = "93.184.216.34"
METADATA_IP = "169.254.169.254"
REBIND_HOST = "rebind.example.com"


class _RebindingResolver:
    """Resolves ``REBIND_HOST`` publicly once, then to the metadata service."""

    def __init__(self, first: str = PUBLIC_IP, later: str = METADATA_IP) -> None:
        self.first = first
        self.later = later
        self.calls = 0

    def addresses(self, hostname: str):
        self.calls += 1
        return [self.first] if self.calls == 1 else [self.later]

    def getaddrinfo(self, host, port, *args, **kwargs):
        address = self.addresses(host)[0]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 80))]


@pytest.fixture
def rebinding(monkeypatch):
    resolver = _RebindingResolver()
    monkeypatch.setattr(url_guard, "_host_addresses", resolver.addresses)
    return resolver


def test_validation_alone_is_fooled_by_rebinding(rebinding):
    """Baseline: the guard passes on the first (public) answer -- as designed.

    This is the window the pin closes; it is asserted so a future change to the
    guard cannot make the pinning tests below pass vacuously.
    """

    error, addresses = url_guard.validate_remote_image_url_resolved(
        f"https://{REBIND_HOST}/page.png"
    )
    assert error is None
    assert addresses == (PUBLIC_IP,)

    # The very next resolution -- the one a normal HTTP client would perform --
    # already points at the metadata service.
    assert list(url_guard._host_addresses(REBIND_HOST)) == [METADATA_IP]


@pytest.fixture
def dialed(monkeypatch):
    """Capture what ``PinnedIPAdapter`` hands to the real transport.

    ``PinnedIPAdapter.send`` rewrites the URL and Host header and then defers
    to ``HTTPAdapter.send``, so intercepting the base implementation observes
    the exact address the socket would have been opened to -- without opening
    one.
    """

    records: list[tuple[str, str | None]] = []

    def _fake_send(self, request, **kwargs):
        records.append(
            (
                requests.utils.urlparse(request.url).hostname,
                request.headers.get("Host"),
            )
        )
        raise requests.exceptions.ConnectionError("blocked in test")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _fake_send)
    return records


def test_fetch_connects_only_to_the_validated_address(rebinding, dialed):
    """The socket must target the validated IP, never the rebound one."""

    with pytest.raises(pinned_fetch.PinnedConnectionError):
        pinned_fetch.get_pinned(
            f"https://{REBIND_HOST}/page.png",
            url_guard.validate_remote_image_url_resolved,
        )

    # Exactly one dial, to the address validation approved -- and the origin
    # still sees its own hostname in the Host header.
    assert dialed == [(PUBLIC_IP, REBIND_HOST)]
    assert all(address != METADATA_IP for address, _host in dialed)

    # The guard resolved once; nothing re-resolved behind its back.
    assert rebinding.calls == 1


def test_rebound_host_is_refused_when_it_rebinds_before_validation(monkeypatch):
    """If the private answer arrives during validation, the fetch is refused."""

    monkeypatch.setattr(url_guard, "_host_addresses", lambda host: [METADATA_IP])

    with pytest.raises(requests.exceptions.InvalidURL) as excinfo:
        pinned_fetch.get_pinned(
            f"https://{REBIND_HOST}/page.png",
            url_guard.validate_remote_image_url_resolved,
        )

    assert "IP address is not permitted" in str(excinfo.value)


def test_redirect_hop_to_a_rebinding_host_is_revalidated(monkeypatch):
    """Each redirect target gets its own resolution, check and pin."""

    seen: list[str] = []

    def _validator(url: str):
        seen.append(url)
        if "second" in url:
            return "IP address is not permitted", ()
        return None, (PUBLIC_IP,)

    def _fake_get_pinned(url, validator, **kwargs):
        error, _addresses = validator(url)
        if error:
            raise requests.exceptions.InvalidURL(f"SSRF Check Failed: {error}")
        response = requests.Response()
        response.status_code = 302
        response.url = url
        response.headers["Location"] = "https://second.example.com/img.png"
        return response

    monkeypatch.setattr(pinned_fetch, "get_pinned", _fake_get_pinned)

    with pytest.raises(requests.exceptions.InvalidURL):
        pinned_fetch.get_pinned_following_redirects(
            "https://first.example.com/img.png", _validator
        )

    assert seen == [
        "https://first.example.com/img.png",
        "https://second.example.com/img.png",
    ]


def test_pinned_adapter_preserves_host_header_and_sni(dialed):
    """Pinning must not degrade the request's TLS/HTTP identity.

    Rewriting the URL to an IP without carrying the hostname over would send
    the wrong Host header *and* verify the certificate against the IP -- a
    silent downgrade of TLS verification in the name of a security fix.
    """

    adapter = pinned_fetch.PinnedIPAdapter("images.example.com", PUBLIC_IP)
    request = requests.Request("GET", "https://images.example.com/a.png").prepare()

    with pytest.raises(requests.exceptions.ConnectionError):
        adapter.send(request)

    assert dialed == [(PUBLIC_IP, "images.example.com")]
    pool_kw = adapter.poolmanager.connection_pool_kw
    assert pool_kw["server_hostname"] == "images.example.com"
    assert pool_kw["assert_hostname"] == "images.example.com"


def test_explicit_port_is_carried_onto_the_pinned_address(dialed):
    """A non-default port must survive the host rewrite."""

    adapter = pinned_fetch.PinnedIPAdapter("images.example.com", PUBLIC_IP)
    request = requests.Request(
        "GET", "https://images.example.com:8443/a.png"
    ).prepare()

    with pytest.raises(requests.exceptions.ConnectionError):
        adapter.send(request)

    assert requests.utils.urlparse(request.url).netloc == f"{PUBLIC_IP}:8443"
    assert request.headers["Host"] == "images.example.com:8443"


def test_proxies_are_refused_because_they_defeat_the_pin():
    """A proxy re-resolves the hostname itself, so pinning cannot hold."""

    adapter = pinned_fetch.PinnedIPAdapter("images.example.com", PUBLIC_IP)

    with pytest.raises(pinned_fetch.PinnedConnectionError):
        adapter.proxy_manager_for("http://proxy.internal:3128")
