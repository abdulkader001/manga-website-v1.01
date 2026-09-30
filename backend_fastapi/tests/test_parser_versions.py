"""Parser versioning + website lifecycle (SRS 1G.6.0A, 1G.6.3, 1G.8.3, 1G.8.5).

Covers: candidates never auto-activate; PA-only approval activates exactly one
version and retires the previous one; one-action rollback; the on-save flow
(parser exists -> ACTIVE, no parser -> PENDING + notification, never silence);
pending websites reject manga URL submissions.
"""

from __future__ import annotations

import json
import uuid

import pytest

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import (
    ApprovedSourceDomain,
    Notification,
    ParserVersion,
    Setting,
    User,
    UserRole,
)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(session, role, *, main=False, secondary=False) -> int:
    u = User(
        email=f"pv-{uuid.uuid4().hex}@example.com",
        is_active=True,
        name="PV",
        role=role,
        is_main_admin=main,
        is_secondary_admin=secondary,
        provider="magic_link",
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u.id


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def _definition() -> dict:
    return {
        "manga_title": "h1.title",
        "manga_description": ".desc",
        "manga_cover": "img.cover",
        "chapter_list": "ul.ch li",
        "chapter_url": "a",
        "chapter_title": "a",
        "chapter_number": "a",
        "page_images": ".pages img",
    }


def test_candidate_never_auto_activates(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    domain = f"cand-{uuid.uuid4().hex[:6]}.com"
    resp = fastapi_client.post(
        f"/api/admin/parsers/{domain}/candidates",
        headers=_h(pa_id),
        json={"definition": _definition(), "source": "rules"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "candidate"
    assert body["version"] == 1
    assert body["module_id"] == f"{domain}_v1"

    listing = fastapi_client.get(
        f"/api/admin/parsers/{domain}", headers=_h(pa_id)
    ).json()
    assert listing["active_version"] is None  # 1G.8.3: candidate != deployment

    # Nothing was published to the runtime scraper config either.
    session = SessionLocal()
    try:
        setting = (
            session.query(Setting)
            .filter(Setting.key == f"scraper_config_{domain}")
            .first()
        )
        assert setting is None
    finally:
        session.close()


def test_approval_activates_retires_and_publishes(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    domain = f"appr-{uuid.uuid4().hex[:6]}.com"
    v1 = fastapi_client.post(
        f"/api/admin/parsers/{domain}/candidates",
        headers=_h(pa_id),
        json={"definition": _definition()},
    ).json()
    approved = fastapi_client.post(
        f"/api/admin/parsers/versions/{v1['id']}/approve", headers=_h(pa_id)
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

    # Definition is published to the runtime config BaseScraper reads.
    session = SessionLocal()
    try:
        setting = (
            session.query(Setting)
            .filter(Setting.key == f"scraper_config_{domain}")
            .first()
        )
        assert setting is not None
        assert json.loads(setting.value)["manga_title"] == "h1.title"
    finally:
        session.close()

    # A second version: approving it retires v1 — exactly one active (1G.8.5).
    new_def = _definition() | {"manga_title": "h2.new-title"}
    v2 = fastapi_client.post(
        f"/api/admin/parsers/{domain}/candidates",
        headers=_h(pa_id),
        json={"definition": new_def},
    ).json()
    fastapi_client.post(
        f"/api/admin/parsers/versions/{v2['id']}/approve", headers=_h(pa_id)
    )

    listing = fastapi_client.get(
        f"/api/admin/parsers/{domain}", headers=_h(pa_id)
    ).json()
    assert listing["active_version"] == 2
    by_version = {v["version"]: v["status"] for v in listing["versions"]}
    assert by_version == {1: "retired", 2: "active"}

    # One-action rollback returns v1 to active and republishes it.
    rolled = fastapi_client.post(
        f"/api/admin/parsers/{domain}/rollback", headers=_h(pa_id)
    )
    assert rolled.status_code == 200
    assert rolled.json()["version"] == 1
    session = SessionLocal()
    try:
        setting = (
            session.query(Setting)
            .filter(Setting.key == f"scraper_config_{domain}")
            .first()
        )
        assert json.loads(setting.value)["manga_title"] == "h1.title"
        active = (
            session.query(ParserVersion)
            .filter(ParserVersion.domain == domain, ParserVersion.status == "active")
            .all()
        )
        assert len(active) == 1 and active[0].version == 1
    finally:
        session.close()


def test_parser_lifecycle_requires_permanent_admin(fastapi_client):
    session = SessionLocal()
    try:
        sec_id = _user(session, UserRole.SECONDARY, secondary=True)
        pa_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    domain = f"perm-{uuid.uuid4().hex[:6]}.com"
    denied = fastapi_client.post(
        f"/api/admin/parsers/{domain}/candidates",
        headers=_h(sec_id),
        json={"definition": _definition()},
    )
    assert denied.status_code == 403

    v1 = fastapi_client.post(
        f"/api/admin/parsers/{domain}/candidates",
        headers=_h(pa_id),
        json={"definition": _definition()},
    ).json()
    denied = fastapi_client.post(
        f"/api/admin/parsers/versions/{v1['id']}/approve", headers=_h(sec_id)
    )
    assert denied.status_code == 403


def test_website_save_with_parser_goes_active(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    domain = f"live-{uuid.uuid4().hex[:6]}.com"
    v1 = fastapi_client.post(
        f"/api/admin/parsers/{domain}/candidates",
        headers=_h(pa_id),
        json={"definition": _definition()},
    ).json()
    fastapi_client.post(
        f"/api/admin/parsers/versions/{v1['id']}/approve", headers=_h(pa_id)
    )

    saved = fastapi_client.post(
        "/api/admin/approved-domains",
        headers=_h(pa_id),
        json={"url": f"https://{domain}", "original_languages": ["ja"]},
    )
    assert saved.status_code == 201
    body = saved.json()
    assert body["status"] == "active"  # 1G.6.0A: parser exists -> ACTIVE
    assert body["original_languages"] == ["ja"]
    assert body["approved_by"] is not None


def test_website_save_without_parser_pending_and_notified(fastapi_client):
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    domain = f"nopr-{uuid.uuid4().hex[:6]}.com"
    saved = fastapi_client.post(
        "/api/admin/approved-domains",
        headers=_h(pa_id),
        json={"url": f"https://{domain}"},
    )
    assert saved.status_code == 201
    assert saved.json()["status"] == "pending"

    # Never silence (1G.8.8): the PA bell says a parser is needed.
    session = SessionLocal()
    try:
        note = (
            session.query(Notification)
            .filter(Notification.type == "parser.needed")
            .filter(Notification.data.isnot(None))
            .order_by(Notification.id.desc())
            .first()
        )
        assert note is not None
        assert domain in (note.body or "")
    finally:
        session.close()

    notes = fastapi_client.get("/api/admin/notifications", headers=_h(pa_id)).json()[
        "notifications"
    ]
    assert any(n["type"] == "parser.needed" for n in notes)


def test_pending_website_rejects_submissions(fastapi_client):
    """1G.6.3: only active websites accept manga URLs — pending rejects with
    the exact WEBSITE_NOT_APPROVED envelope, before any scraper is selected."""
    session = SessionLocal()
    try:
        pa_id = _user(session, UserRole.ADMIN, main=True)
    finally:
        session.close()

    domain = f"pend-{uuid.uuid4().hex[:6]}.com"
    fastapi_client.post(
        "/api/admin/approved-domains",
        headers=_h(pa_id),
        json={"url": f"https://{domain}"},
    )

    resp = fastapi_client.post(
        "/api/admin/series",
        headers=_h(pa_id),
        json={"url": f"https://{domain}/manga/some-title"},
    )
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "WEBSITE_NOT_APPROVED"

    # PA flips it active via the lifecycle endpoint -> submission opens.
    session = SessionLocal()
    try:
        entry = (
            session.query(ApprovedSourceDomain)
            .filter(ApprovedSourceDomain.domain == domain)
            .first()
        )
        entry_id = entry.id
    finally:
        session.close()

    flipped = fastapi_client.put(
        f"/api/admin/approved-domains/{entry_id}/status",
        headers=_h(pa_id),
        json={"status": "active"},
    )
    assert flipped.status_code == 200
    assert flipped.json()["status"] == "active"

    resp = fastapi_client.post(
        "/api/admin/series",
        headers=_h(pa_id),
        json={"url": f"https://{domain}/manga/some-title"},
    )
    assert resp.status_code != 422 or (
        resp.json().get("error", {}).get("code") != "WEBSITE_NOT_APPROVED"
    )
