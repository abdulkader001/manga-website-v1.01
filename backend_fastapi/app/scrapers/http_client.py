import requests
import random
import time
import structlog

logger = structlog.get_logger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


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

        headers = kwargs.pop("headers", {})
        if "User-Agent" not in headers:
            headers["User-Agent"] = random.choice(USER_AGENTS)

        # Optional jitter delay
        jitter = random.uniform(0.1, 1.5)
        time.sleep(jitter)

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

        headers = kwargs.pop("headers", {})
        if "User-Agent" not in headers:
            headers["User-Agent"] = random.choice(USER_AGENTS)
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
