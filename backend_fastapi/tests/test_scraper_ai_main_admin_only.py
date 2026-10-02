"""The Scraper AI is main-admin only (owner's rule).

Its API key (Series Management -> Scraper AI API) and creating parsers with
it (Custom Parser) belong to the main admin alone: no toggle, preset or stored
override gives them to a sub-admin, every endpoint refuses a sub-admin, and
scrapes a sub-admin starts (preview, import, re-scrape) never call the AI.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest

from backend_fastapi.app.core.api_errors import ApiError
from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.permissions import MAIN_ADMIN_ONLY, catalogue
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import PermissionOverride, PermissionPreset, User, UserRole
from backend_fastapi.app.scrapers import source_pipeline
from backend_fastapi.app.scrapers.ai_fallback import AIFallbackService
from backend_fastapi.app.services import permissions_service, scraper_ai_service
from backend_fastapi.app.services.scraper_workflow_service import ScraperWorkflowService

SCRAPER_AI = sorted(MAIN_ADMIN_ONLY)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


def _user(role: UserRole, *, main: bool = False, secondary: bool = False) -> int:
    with SessionLocal() as session:
        user = User(
            email=f"mao-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="MAO",
            role=role,
            is_main_admin=main,
            is_secondary_admin=secondary,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        return user.id


def _sub_admin_with_stored_grants() -> int:
    """A sub-admin whose table rows say they hold the Scraper AI powers (as a
    toggle granted before this rule would have left them)."""

    uid = _user(UserRole.SECONDARY, secondary=True)
    with SessionLocal() as session:
        for key in SCRAPER_AI + ["view_websites", "approve_parser", "activate_parser"]:
            session.add(PermissionOverride(user_id=uid, permission=key, state="granted"))
        session.commit()
    return uid


def _h(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(uid))}"}


# ---------------------------------------------------------------------------
# Permission rules
# ---------------------------------------------------------------------------


def test_the_scraper_ai_powers_are_the_main_admin_only_set():
    assert MAIN_ADMIN_ONLY == {"trigger_scraper_ai", "configure_scraper_ai"}


def test_stored_grants_never_give_a_sub_admin_the_scraper_ai():
    sub = _sub_admin_with_stored_grants()
    main = _user(UserRole.ADMIN, main=True)
    with SessionLocal() as session:
        sub_user, main_user = session.get(User, sub), session.get(User, main)
        for key in SCRAPER_AI:
            assert permissions_service.has_permission(session, sub_user, key) is False
            assert permissions_service.has_permission(session, main_user, key) is True
        # Ordinary overrides keep working.
        assert permissions_service.has_permission(session, sub_user, "approve_parser") is True
        effective = {p["key"]: p for p in permissions_service.resolve_effective(session, sub_user)}
        for key in SCRAPER_AI:
            assert effective[key]["effective"] is False
            assert effective[key]["state"] == "inherited"


def test_granting_is_refused_and_revoking_stores_nothing():
    sub = _user(UserRole.SECONDARY, secondary=True)
    main = _user(UserRole.ADMIN, main=True)
    with SessionLocal() as session:
        target = session.get(User, sub)
        for key in SCRAPER_AI:
            with pytest.raises(ApiError) as refused:
                permissions_service.set_override(session, target, key, "granted", main)
            assert refused.value.details["reason"] == "main_admin_only"
            permissions_service.set_override(session, target, key, "revoked", main)
        session.commit()
        assert session.query(PermissionOverride).filter_by(user_id=sub).count() == 0


def test_presets_skip_the_scraper_ai():
    sub = _user(UserRole.SECONDARY, secondary=True)
    main = _user(UserRole.ADMIN, main=True)
    key = f"p{uuid.uuid4().hex[:8]}"
    with SessionLocal() as session:
        preset = permissions_service.create_custom_preset(
            session,
            key=key,
            label="Everything",
            description=None,
            grant=SCRAPER_AI + ["approve_website"],
            revoke=[],
            actor_id=main,
        )
        assert preset.definition["grant"] == ["approve_website"]
        # An older preset saved with the keys still applies, minus them.
        preset.definition = {"grant": SCRAPER_AI + ["approve_website"], "revoke": []}
        session.commit()
        target = session.get(User, sub)
        permissions_service.apply_preset(session, target, key, main)
        session.commit()
        stored = {r.permission for r in session.query(PermissionOverride).filter_by(user_id=sub)}
        assert stored == {"approve_website"}
        permissions_service.apply_preset(session, target, "titular", main)
        session.commit()
        stored = {r.permission for r in session.query(PermissionOverride).filter_by(user_id=sub)}
        assert not stored & MAIN_ADMIN_ONLY
        session.query(PermissionPreset).filter_by(key=key).delete()
        session.commit()


def test_catalogue_marks_them_for_the_role_page():
    entries = {e["key"]: e for e in catalogue()}
    for key in SCRAPER_AI:
        assert entries[key]["main_admin_only"] is True
        assert entries[key]["defaults"]["secondary_admin"] is False
    assert entries["approve_parser"]["main_admin_only"] is False


# ---------------------------------------------------------------------------
# Every endpoint refuses a sub-admin (even one with stored grants)
# ---------------------------------------------------------------------------


def test_scraper_ai_endpoints_refuse_a_sub_admin(fastapi_client):
    sub = _sub_admin_with_stored_grants()
    headers = _h(sub)
    calls = [
        ("post", "/api/admin/scraper/parsers/generate", {"url": "https://new-site.example/manga/x"}),
        ("get", "/api/v1/admin/scraper/ai-config", None),
        ("post", "/api/v1/admin/scraper/ai-config", {"apiKey": "sk-test", "model": "gpt-4o-mini", "enabled": True}),
        ("put", "/api/admin/system-providers", {"service": "scraper_ai", "config": {"provider": "openai", "apiKey": "sk-x"}}),
        ("post", "/api/admin/system-providers/scraper-ai/test", None),
        ("post", "/api/admin/parsers/new-site.example/generate", {"base_url": "https://new-site.example/"}),
    ]
    with mock.patch("backend_fastapi.app.tasks.scraper_tasks.run_source_task.delay") as queued, mock.patch(
        "backend_fastapi.app.tasks.scraper_tasks.generate_parser_task.delay"
    ) as generated:
        for method, path, body in calls:
            kwargs = {"headers": headers}
            if body is not None:
                kwargs["json"] = body
            response = getattr(fastapi_client, method)(path, **kwargs)
            assert response.status_code == 403, (method, path, response.status_code, response.text[:200])
    queued.assert_not_called()
    generated.assert_not_called()


def test_main_admin_can_still_use_custom_parser(fastapi_client):
    main = _user(UserRole.ADMIN, main=True)
    with mock.patch("backend_fastapi.app.tasks.scraper_tasks.run_source_task.delay") as queued:
        response = fastapi_client.post(
            "/api/admin/scraper/parsers/generate",
            headers=_h(main),
            json={"url": "https://new-site.example/manga/x"},
        )
    assert response.status_code == 202, response.text[:200]
    queued.assert_called_once()


def test_role_page_cannot_grant_it_and_sees_the_flag(fastapi_client):
    sub = _user(UserRole.SECONDARY, secondary=True)
    main = _user(UserRole.ADMIN, main=True)
    refused = fastapi_client.put(
        f"/api/admin/users/{sub}/permissions",
        headers=_h(main),
        json={"overrides": [{"permission": "trigger_scraper_ai", "state": "granted"}]},
    )
    assert refused.status_code == 403, refused.text[:200]
    listed = fastapi_client.get("/api/admin/permissions/catalogue", headers=_h(main))
    assert listed.status_code == 200
    flags = {e["key"]: e.get("main_admin_only") for e in listed.json()["permissions"]}
    assert flags["trigger_scraper_ai"] is True and flags["configure_scraper_ai"] is True


# ---------------------------------------------------------------------------
# Scrapes a sub-admin starts never call the AI
# ---------------------------------------------------------------------------


def test_may_use_scraper_ai():
    sub = _sub_admin_with_stored_grants()
    main = _user(UserRole.ADMIN, main=True)
    with SessionLocal() as session:
        assert source_pipeline.may_use_scraper_ai(session, session.get(User, main)) is True
        assert source_pipeline.may_use_scraper_ai(session, session.get(User, sub)) is False
        assert source_pipeline.may_use_scraper_ai(session, None) is False


def test_custom_parser_task_refuses_a_sub_admin_before_fetching():
    sub = _sub_admin_with_stored_grants()
    with SessionLocal() as session, mock.patch.object(source_pipeline, "resolve_parser") as resolve:
        result = source_pipeline.run_generate_parser(session, {"url": "https://x.example/manga/a"}, session.get(User, sub))
    assert result["ok"] is False and "main-admin only" in result["message"]
    resolve.assert_not_called()


def test_preview_by_a_sub_admin_runs_without_the_ai():
    sub = _sub_admin_with_stored_grants()
    main = _user(UserRole.ADMIN, main=True)
    for uid, expected in ((sub, False), (main, True)):
        with SessionLocal() as session, mock.patch.object(
            source_pipeline, "resolve_parser", return_value={"ok": False, "message": "no"}
        ) as resolve:
            source_pipeline.run_preview(session, {"url": "https://x.example/manga/a"}, session.get(User, uid))
        assert resolve.call_args.kwargs["allow_ai"] is expected


def test_candidates_never_ask_the_ai_when_not_allowed():
    scraper = SimpleNamespace()
    with SessionLocal() as session, mock.patch.object(
        scraper_ai_service, "is_configured", return_value=True
    ), mock.patch.object(scraper_ai_service, "generate_definition") as ask:
        assert list(source_pipeline._series_candidates(session, scraper, "https://x.example/s", "<p></p>", None, False)) == []
        assert list(source_pipeline._reader_candidates(session, scraper, {}, "https://x.example/c", "<p></p>", False)) == []
    ask.assert_not_called()


def test_in_scrape_fallback_skips_the_ai_when_not_allowed():
    with mock.patch.object(scraper_ai_service, "get_config", return_value={"api_url": "https://ai.example"}), mock.patch.object(
        scraper_ai_service, "generate_selectors"
    ) as ask:
        assert AIFallbackService.extract_selectors("<p>nothing</p>", "manga", use_ai=False) is None
    ask.assert_not_called()


def test_import_jobs_follow_the_requester():
    sub = _sub_admin_with_stored_grants()
    main = _user(UserRole.ADMIN, main=True)
    with SessionLocal() as session:
        service = ScraperWorkflowService(session)
        assert service._requester_may_use_ai(SimpleNamespace(requested_by=sub)) is False
        assert service._requester_may_use_ai(SimpleNamespace(requested_by=main)) is True
        # The system's own jobs (no requester) keep repairing with the AI.
        assert service._requester_may_use_ai(SimpleNamespace(requested_by=None)) is True


def test_a_sub_admin_saving_a_website_does_not_start_the_ai(fastapi_client):
    """Approving a website starts parser generation in the background; for a
    website a sub-admin approved, that run must not use the AI."""

    from backend_fastapi.app.models import ApprovedSourceDomain, Notification
    from backend_fastapi.app.services import parser_generation_service

    results = {}
    for role, main, secondary in ((UserRole.SECONDARY, False, True), (UserRole.ADMIN, True, False)):
        uid = _user(role, main=main, secondary=secondary)
        if secondary:
            with SessionLocal() as session:
                session.add(PermissionOverride(user_id=uid, permission="approve_website", state="granted"))
                session.commit()
        host = f"w{uuid.uuid4().hex[:6]}.example"
        with mock.patch.object(scraper_ai_service, "is_configured", return_value=True), mock.patch(
            "backend_fastapi.app.tasks.scraper_tasks.generate_parser_task.delay"
        ) as queued:
            response = fastapi_client.post(
                "/api/admin/approved-domains",
                headers=_h(uid),
                json={"url": f"https://{host}/manga/series", "label": "Site"},
            )
        assert response.status_code in (200, 201), response.text[:200]
        domain, base_url, trigger = queued.call_args.args[:3]
        with SessionLocal() as session:
            assert session.query(ApprovedSourceDomain).filter_by(domain=domain).one().approved_by == uid
            # Run the queued background job the way the worker would.
            with mock.patch.object(scraper_ai_service, "is_configured", return_value=True), mock.patch.object(
                parser_generation_service, "generate_and_test", return_value={"possible": False, "message": "x", "required_inputs": []}
            ) as ai:
                results[secondary] = parser_generation_service.attempt_generation(
                    session, domain=domain, base_url=base_url, trigger=trigger
                )
            results[(secondary, "ai")] = ai.called
            if secondary:
                note = session.query(Notification).filter(Notification.type == "parser.needed").all()
                assert any(domain in (n.title or "") for n in note)
    assert results[True] == {"status": "skipped_main_admin_only"} and results[(True, "ai")] is False
    assert results[(False, "ai")] is True
