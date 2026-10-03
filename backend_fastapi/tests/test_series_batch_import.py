"""Several series addresses at once (Admin -> Series -> Import, "many at once").

Each address goes through the same checks as a single import and gets its own
result; one bad address never stops the others.
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import ApprovedSourceDomain, User, UserRole


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _admin() -> int:
    session = SessionLocal()
    try:
        user = User(
            email=f"batch-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Batch",
            role=UserRole.ADMIN,
            is_main_admin=True,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        return user.id
    finally:
        session.close()


def _approve(domain: str) -> None:
    session = SessionLocal()
    try:
        session.add(ApprovedSourceDomain(base_url=f"https://{domain}", domain=domain, status="active"))
        session.commit()
    finally:
        session.close()


def test_batch_import_queues_each_address_and_reports_each_failure(fastapi_client):
    uid = _admin()
    domain = f"batch-{uuid.uuid4().hex[:6]}.com"
    _approve(domain)
    good = [f"https://{domain}/manga/series-{n}" for n in range(3)]
    urls = good + [good[0], "not a link", f"https://unapproved-{uuid.uuid4().hex[:6]}.com/manga/x", f"https://{domain}/"]
    with mock.patch("backend_fastapi.app.tasks.scraper_tasks.process_manga_scrape") as task, mock.patch(
        "backend_fastapi.app.services.url_guard._host_addresses", return_value=["93.184.216.34"]
    ):
        task.delay.return_value = None
        response = fastapi_client.post(
            "/api/admin/series/batch",
            headers={"Authorization": f"Bearer {create_access_token(str(uid))}"},
            json={"urls": urls},
        )
    assert response.status_code == 202, response.text
    body = response.json()
    # The duplicate line is dropped; three queued, three refused with a reason.
    assert body["queued"] == 3
    assert body["failed"] == 3
    by_url = {r["url"]: r for r in body["results"]}
    assert all(by_url[u]["ok"] for u in good)
    assert not by_url["not a link"]["ok"] and by_url["not a link"]["error"]
    assert not by_url[f"https://{domain}/"]["ok"]
    assert task.delay.call_count == 3


def test_batch_import_caps_the_number_of_addresses(fastapi_client):
    uid = _admin()
    response = fastapi_client.post(
        "/api/admin/series/batch",
        headers={"Authorization": f"Bearer {create_access_token(str(uid))}"},
        json={"urls": [f"https://x.example/manga/{n}" for n in range(51)]},
    )
    assert response.status_code == 422
