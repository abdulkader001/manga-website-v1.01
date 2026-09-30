"""Roadmap items 11 and 12: source health checks and the storage report."""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import Chapter, Manga, User, UserRole
from backend_fastapi.app.services import source_health_service as health
from backend_fastapi.app.services import storage_report_service as storage


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _series(session, host: str) -> Manga:
    manga = Manga(
        title=f"Health-{uuid.uuid4().hex[:6]}",
        source_url=f"https://{host}/manga/{uuid.uuid4().hex[:6]}",
        type="manga",
        status="ongoing",
    )
    session.add(manga)
    session.commit()
    session.refresh(manga)
    return manga


def _host() -> str:
    return f"health-{uuid.uuid4().hex[:8]}.example"


def _run(session, host, probe, redetect=None):
    manga = _series(session, host)
    with mock.patch.object(health, "probe_host", return_value=probe), mock.patch.object(
        health, "redetect", return_value=redetect or {"result": "failed"}
    ) as redetect_mock, mock.patch(
        "backend_fastapi.app.services.notification_service.notify_async"
    ) as notify:
        record = health.check_host(session, host, manga)
    return record, redetect_mock, notify


def test_healthy_source_records_ok_and_stays_quiet():
    session = SessionLocal()
    try:
        host = _host()
        record, redetect, notify = _run(
            session, host, {"status": "ok", "chapters": 12, "images": 20}
        )
        assert record["status"] == "ok" and record["last_ok_at"]
        redetect.assert_not_called()
        notify.assert_not_called()
        assert health.load(session, host)["status"] == "ok"
    finally:
        session.close()


@pytest.mark.parametrize("status", ["zero_chapters", "zero_pictures"])
def test_zero_results_alert_and_try_redetection(status):
    session = SessionLocal()
    try:
        host = _host()
        record, redetect, notify = _run(
            session, host, {"status": status, "chapters": 0, "images": 0}
        )
        redetect.assert_called_once()
        notify.assert_called_once()
        assert notify.call_args.kwargs["type"] == "website.structure_changed"
        assert record["consecutive_failures"] == 1
    finally:
        session.close()


def test_candidate_found_changes_alert_and_failures_accumulate():
    session = SessionLocal()
    try:
        host = _host()
        bad = {"status": "zero_chapters", "chapters": 0, "images": 0}
        found = {"result": "candidate_ready", "version_id": 1}
        manga = _series(session, host)
        for expected in (1, 2):
            with mock.patch.object(health, "probe_host", return_value=bad), mock.patch.object(
                health, "redetect", return_value=found
            ), mock.patch(
                "backend_fastapi.app.services.notification_service.notify_async"
            ) as notify:
                record = health.check_host(session, host, manga)
            assert record["consecutive_failures"] == expected
        assert notify.call_args.kwargs["type"] == "parser.candidate_ready"
        # Recovery resets the counter and keeps the last-ok time.
        with mock.patch.object(
            health, "probe_host", return_value={"status": "ok", "chapters": 3, "images": 9}
        ):
            record = health.check_host(session, host, manga)
        assert record["consecutive_failures"] == 0
    finally:
        session.close()


def test_unreachable_site_alerts_without_redetection():
    session = SessionLocal()
    try:
        record, redetect, notify = _run(
            session, _host(), {"status": "fetch_failed", "chapters": 0, "images": 0}
        )
        redetect.assert_not_called()
        notify.assert_called_once()
        assert notify.call_args.kwargs["type"] == "parser.needed"
    finally:
        session.close()


def test_one_sample_series_per_host_prefers_most_chapters():
    session = SessionLocal()
    try:
        host = _host()
        small, big = _series(session, host), _series(session, host)
        session.add_all(
            Chapter(
                manga_id=big.id,
                chapter_number=n,
                chapter_url=f"https://{host}/c/{uuid.uuid4().hex}",
            )
            for n in (1, 2)
        )
        session.commit()
        assert health.sample_series_per_host(session)[host].id == big.id
        assert small.id != big.id
    finally:
        session.close()


def _admin_headers(session) -> dict:
    user = User(
        email=f"sh-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="SH",
        role=UserRole.ADMIN,
        is_main_admin=True,
        provider="magic_link",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_storage_report_totals_and_threshold(monkeypatch, tmp_path):
    monkeypatch.setenv("PAGE_STORAGE_DIR", str(tmp_path))
    session = SessionLocal()
    try:
        manga = _series(session, _host())
        session.add(
            Chapter(
                manga_id=manga.id,
                chapter_number=1,
                chapter_url=f"https://x.example/{uuid.uuid4().hex}",
                pages_bytes=5_000_000,
            )
        )
        session.commit()

        monkeypatch.setenv("STORAGE_ALERT_PERCENT", "100")
        monkeypatch.delenv("STORAGE_ALERT_BYTES", raising=False)
        report = storage.build_report(session)
        assert report["picture_bytes"] >= 5_000_000
        assert any(row["id"] == manga.id for row in report["top_series"])

        monkeypatch.setenv("STORAGE_ALERT_BYTES", "1000")
        assert storage.build_report(session)["alert"]["active"] is True

        monkeypatch.setenv("STORAGE_ALERT_BYTES", "0")
        monkeypatch.setenv("STORAGE_ALERT_PERCENT", "0")
        assert storage.build_report(session)["alert"]["active"] is True
    finally:
        session.close()


def test_admin_endpoints_require_permission_and_answer(fastapi_client, monkeypatch, tmp_path):
    monkeypatch.setenv("PAGE_STORAGE_DIR", str(tmp_path))
    assert fastapi_client.get("/api/v1/admin/storage").status_code in (401, 403)
    session = SessionLocal()
    try:
        headers = _admin_headers(session)
    finally:
        session.close()
    body = fastapi_client.get("/api/v1/admin/storage", headers=headers)
    assert body.status_code == 200 and "volume" in body.json()
    sources = fastapi_client.get("/api/v1/admin/sources/health", headers=headers)
    assert sources.status_code == 200 and "sources" in sources.json()


def test_probe_host_classifies_real_scraper_results(monkeypatch):
    """probe_host turns scraper output into the statuses the check acts on."""
    from backend_fastapi.app.scrapers import base_scraper, source_pipeline

    class Fake:
        config = {"page_images": "img"}
        chapters = [{"url": "https://h.example/c/1"}]
        soup = object()
        images = ["a.jpg"]
        boom = False

        def __init__(self, domain):
            pass

        def scrape_manga(self, url, _none, dry_run=False):
            if Fake.boom:
                raise RuntimeError("blocked")
            return {"chapters": Fake.chapters}

        def _fetch_html(self, url):
            return Fake.soup

    monkeypatch.setattr(base_scraper, "BaseScraper", Fake)
    monkeypatch.setattr(source_pipeline, "_images_on", lambda *a, **k: Fake.images)

    assert health.probe_host("h.example", "u")["status"] == "ok"
    Fake.images = []
    assert health.probe_host("h.example", "u")["status"] == "zero_pictures"
    Fake.chapters = []
    assert health.probe_host("h.example", "u")["status"] == "zero_chapters"
    Fake.boom = True
    assert health.probe_host("h.example", "u")["status"] == "fetch_failed"
