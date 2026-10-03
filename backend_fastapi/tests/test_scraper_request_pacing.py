"""Per-site request budget: the vault setting is a ceiling a parser can only lower."""

from backend_fastapi.app.scrapers import concurrency


def test_default_budget_is_thirty_a_minute(monkeypatch):
    monkeypatch.delenv("SCRAPER_REQUESTS_PER_MINUTE", raising=False)
    assert concurrency.requests_per_minute() == 30


def test_a_parser_can_slow_down_but_not_speed_up(monkeypatch):
    monkeypatch.setenv("SCRAPER_REQUESTS_PER_MINUTE", "40")
    assert concurrency.requests_per_minute({"requests_per_minute": 12}) == 12
    assert concurrency.requests_per_minute({"requests_per_minute": 120}) == 40


def test_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv("SCRAPER_REQUESTS_PER_MINUTE", "lots")
    assert concurrency.requests_per_minute() == 30
    monkeypatch.setenv("SCRAPER_REQUESTS_PER_MINUTE", "5000")
    assert concurrency.requests_per_minute() == 600


def test_slots_run_out_then_report_a_wait(monkeypatch):
    monkeypatch.setattr(concurrency, "get_redis_client", lambda: None)
    concurrency._local_windows.clear()
    assert concurrency.take_request_slot("pace.example", 2) == 0
    assert concurrency.take_request_slot("pace.example", 2) == 0
    assert concurrency.take_request_slot("pace.example", 2) > 0
