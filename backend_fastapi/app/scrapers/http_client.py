import requests
import random
import time
import structlog

logger = structlog.get_logger(__name__)

# Current desktop browsers. Old version numbers (Chrome 119 was over a year
# old) are a common reason for bot checks.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
]

# Headers a real browser sends with every request. A request carrying only a
# User-Agent is an easy bot signal for anti-scraping filters.
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def user_agent_for(url: str) -> str:
    """One User-Agent per website, kept for every request to it.

    Like a person's browser (and like gallery-dl / Mihon), a site sees the
    same browser on every page; a User-Agent that changes between requests
    of one visit is a typical reason to be blocked.
    """

    import zlib
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return USER_AGENTS[zlib.crc32(host.encode()) % len(USER_AGENTS)]


def _with_browser_headers(url: str, headers: dict) -> dict:
    merged = dict(headers or {})
    present = {key.lower() for key in merged}
    if "user-agent" not in present:
        merged["User-Agent"] = user_agent_for(url)
    for key, value in BROWSER_HEADERS.items():
        if key.lower() not in present:
            merged[key] = value
    return merged


def retry_after_seconds(response, default: float, cap: float = 60.0) -> float:
    """Seconds a 429/503 answer asks us to wait (``Retry-After``), capped."""

    value = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        return max(0.0, min(cap, float(value)))
    except (TypeError, ValueError):
        return min(cap, default)


class RequestWrapper:
    @staticmethod
    def get(
        url: str,
        timeout: int = 15,
        max_redirects: int = 5,
        max_bytes: int | None = None,
        **kwargs,
    ) -> requests.Response:
        """
        Wrapped requests.get with user-agent rotation, jitter, and strict SSRF redirect handling.

        ``max_bytes`` caps the response body streamed in per hop; left as
        ``None`` it falls back to ``pinned_fetch.DEFAULT_MAX_FETCH_BYTES``,
        sized for the HTML pages this wrapper fetches (scraped page images go
        through the ``ocr``/``processing`` routers' own, tighter limits).
        """
        from ..services.pinned_fetch import get_pinned_following_redirects
        from ..services.url_guard import validate_scrape_url_resolved

        headers = _with_browser_headers(url, kwargs.pop("headers", {}))

        # Callers that pace their own requests (the scraper) pass
        # jitter=False; everyone else keeps a short random pause.
        if kwargs.pop("jitter", True):
            time.sleep(random.uniform(0.1, 1.5))

        kwargs.pop("allow_redirects", None)

        # Every hop -- the initial URL and each redirect target -- is validated
        # before it is fetched, and the connection is pinned to an address that
        # validation actually saw, so a low-TTL host cannot re-resolve to a
        # private IP in between. We don't check the DB allowlist here (pass
        # db_session=None) to allow CDNs/image hosts; the domain allowlist is
        # only for the starting manga URL.
        return get_pinned_following_redirects(
            url,
            lambda candidate: validate_scrape_url_resolved(
                candidate, db_session=None
            ),
            timeout=timeout,
            max_redirects=max_redirects,
            headers=headers,
            max_bytes=max_bytes,
            **kwargs,
        )

    @staticmethod
    def post(
        url: str,
        timeout: int = 15,
        data: dict | None = None,
        max_bytes: int | None = None,
        **kwargs,
    ) -> requests.Response:
        """A form POST (AJAX chapter lists) through the same SSRF-validated,
        IP-pinned connection as ``get``. Redirects are not followed: an AJAX
        endpoint that redirects is treated as a failure."""
        from ..services.pinned_fetch import get_pinned
        from ..services.url_guard import validate_scrape_url_resolved

        headers = _with_browser_headers(url, kwargs.pop("headers", {}))
        if kwargs.pop("jitter", True):
            time.sleep(random.uniform(0.1, 1.0))
        response = get_pinned(
            url,
            lambda candidate: validate_scrape_url_resolved(candidate, db_session=None),
            method="POST",
            timeout=timeout,
            headers=headers,
            max_bytes=max_bytes,
            data=data or {},
        )
        if response.is_redirect:
            raise requests.exceptions.HTTPError(f"Unexpected redirect from {url}", response=response)
        return response
