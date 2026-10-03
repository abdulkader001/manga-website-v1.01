"""Per-site AutoThrottle: slow or pushing-back sites are read more slowly."""

from __future__ import annotations

from unittest import mock

import requests

from backend_fastapi.app.scrapers import throttle
from backend_fastapi.app.scrapers.base_scraper import BaseScraper


def test_delay_follows_the_sites_answer_time():
    assert throttle.delay_for("a.example") == 0.0
    throttle.record("a.example", 4.0, 200)
    assert throttle.delay_for("a.example") == 2.0  # halfway towards 4 s
    throttle.record("a.example", 4.0, 200)
    assert throttle.delay_for("a.example") == 3.0
    for _ in range(20):
        throttle.record("a.example", 0.2, 200)
    assert throttle.delay_for("a.example") < 0.5  # a fast site is read faster again
    assert throttle.delay_for("a.example", minimum=1.0) == 1.0  # never under the scraper's own minimum
    assert throttle.delay_for("b.example") == 0.0  # sites don't share a pace


def test_push_back_doubles_the_delay_up_to_the_cap():
    throttle.record("c.example", 0.1, 429)
    assert throttle.delay_for("c.example") == throttle.BLOCK_FLOOR
    throttle.record("c.example", 0.1, 503)
    assert throttle.delay_for("c.example") == throttle.BLOCK_FLOOR * 2
    for _ in range(10):
        throttle.record("c.example", 0.1, 403)
    assert throttle.delay_for("c.example") == throttle.MAX_DELAY
    # An error answer never speeds us up.
    before = throttle.delay_for("c.example")
    throttle.record("c.example", 0.0, 500)
    assert throttle.delay_for("c.example") == before


def test_the_scraper_waits_longer_after_a_429():
    scraper = BaseScraper("d.example", delay=0, retries=2)
    scraper.config = {}
    blocked = requests.Response()
    blocked.status_code = 429
    ok = requests.Response()
    ok.status_code = 200
    ok._content = b"<html><h1>Series</h1>" + b"x" * 2000 + b"</html>"
    sleeps = []
    with mock.patch(
        "backend_fastapi.app.scrapers.http_client.RequestWrapper.get", side_effect=[blocked, ok]
    ), mock.patch("backend_fastapi.app.scrapers.base_scraper.time.sleep", side_effect=sleeps.append), mock.patch(
        "backend_fastapi.app.scrapers.concurrency.check_rate_limit", return_value=True
    ):
        assert scraper._fetch_html("https://d.example/s/1") is not None
    # The second request waited at least the push-back floor.
    assert max(sleeps) >= throttle.BLOCK_FLOOR
