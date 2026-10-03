"""Admin -> Site Functions: the owner's on/off switches (owner only, enforced)."""

from __future__ import annotations

import pytest

from backend_fastapi.app.core import site_functions as registry
from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services import site_functions as functions
from _support import staff

URL = "/api/v1/admin/site-functions"


@pytest.fixture(scope="module", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def _defaults_afterwards():
    staff.reset_staff()
    yield
    with SessionLocal() as session:
        functions.reset_all(session)
        # The shared test site is open to guests (tests/conftest.py).
        functions.set_enabled(session, "sign_in_required", False, None)
    staff.reset_staff()


def _location(resp) -> str:
    """The Location header (the stub client returns headers as pairs)."""

    headers = resp.headers.items() if hasattr(resp.headers, "items") else resp.headers
    return next((v for k, v in headers if k.lower() == "location"), "")


def _off(client, owner, key):
    resp = client.put(f"{URL}/{key}", json={"enabled": False}, headers=staff.headers(owner))
    assert resp.status_code == 200, resp.text
    return resp


def _on(client, owner, key):
    resp = client.put(f"{URL}/{key}", json={"enabled": True}, headers=staff.headers(owner))
    assert resp.status_code == 200, resp.text


# ------------------------------------------------------------------ owner only


def test_only_the_owner_can_see_or_change_it(fastapi_client):
    admin = staff.admin()
    # Even an Admin holding every power the owner can give has no way in.
    with SessionLocal() as session:
        from backend_fastapi.app.services import permissions_service as ps

        target = session.get(User, admin)
        for key in ("manage_admin_settings", "manage_roles"):
            ps.set_override(session, target, key, "granted", None, by_owner=True)
        session.commit()
    for who in (admin, staff.sub_admin(), staff.reader()):
        h = staff.headers(who)
        assert fastapi_client.get(URL, headers=h).status_code == 403
        assert fastapi_client.put(f"{URL}/comments", json={"enabled": False}, headers=h).status_code == 403
    assert fastapi_client.get(URL).status_code in (401, 403)
    assert fastapi_client.get(URL, headers=staff.headers(staff.owner())).status_code == 200


def test_no_permission_opens_it():
    from backend_fastapi.app.core.permissions import ALL_PERMISSIONS

    assert not any("function" in key for key in ALL_PERMISSIONS)


def test_every_function_is_listed_with_its_state(fastapi_client):
    owner = staff.owner()
    body = fastapi_client.get(URL, headers=staff.headers(owner)).json()
    assert {f["key"] for f in body["functions"]} == set(registry.REGISTRY)
    assert set(body["groups"]) >= {f["group"] for f in body["functions"]}
    defaults = {f["key"]: f["enabled"] for f in body["functions"]}
    assert defaults["comments"] is True and defaults["maintenance_mode"] is False


def test_unknown_function_is_404(fastapi_client):
    owner = staff.owner()
    resp = fastapi_client.put(f"{URL}/nope", json={"enabled": False}, headers=staff.headers(owner))
    assert resp.status_code == 404


def test_the_public_config_reports_on_or_off_only(fastapi_client):
    owner = staff.owner()
    _off(fastapi_client, owner, "comments")
    body = fastapi_client.get("/api/v1/config/site-functions").json()
    assert body["functions"]["comments"] is False
    assert set(body) == {"functions"} and set(body["functions"]) == set(registry.REGISTRY)


# ------------------------------------------------------------- the switch bites

# function -> (method, path, needs_login)
ROUTES = {
    "comments": ("GET", "/api/v1/comments/config", False),
    "community": ("GET", "/api/v1/community/emojis", False),
    "notifications": ("GET", "/api/v1/notifications/unread-count", True),
    "ads": ("GET", "/api/v1/ads/config", False),
    "support_links": ("GET", "/api/v1/support", False),
    "ocr": ("POST", "/api/v1/ocr/image", True),
    "translation": ("POST", "/api/v1/translation/text", True),
    "chapter_reports": ("POST", "/api/v1/chapters/1/report", True),
    "scraper": ("POST", "/api/v1/admin/series/1/rescrape", True),
}


@pytest.mark.parametrize("key", sorted(ROUTES))
def test_a_function_that_is_off_refuses_its_routes(fastapi_client, key):
    method, path, needs_login = ROUTES[key]
    owner = staff.owner()
    h = staff.headers(staff.reader()) if needs_login else {}

    def call():
        return fastapi_client.request(method, path, headers=h, json={} if method == "POST" else None)

    before = call()
    assert before.status_code != 403 or before.json()["error"]["code"] != "FUNCTION_DISABLED"

    _off(fastapi_client, owner, key)
    off = call()
    assert off.status_code == 403, off.text
    assert off.json()["error"]["code"] == "FUNCTION_DISABLED"
    assert off.json()["error"]["details"]["function"] == key

    _on(fastapi_client, owner, key)
    again = call()
    assert again.status_code != 403 or again.json()["error"]["code"] != "FUNCTION_DISABLED"


def test_sitemap_and_feeds_follow_their_switch(fastapi_client):
    owner = staff.owner()
    assert fastapi_client.get("/sitemap.xml").status_code == 200
    _off(fastapi_client, owner, "sitemap_feeds")
    off = fastapi_client.get("/sitemap.xml")
    assert off.status_code == 403 and off.json()["error"]["code"] == "FUNCTION_DISABLED"
    assert fastapi_client.get("/rss.xml").status_code == 403


def test_the_scheduled_scrape_skips_while_scraping_is_off(fastapi_client):
    from backend_fastapi.app.tasks import scraper_tasks

    owner = staff.owner()
    _off(fastapi_client, owner, "scraper")
    assert scraper_tasks.run_scheduled_scrape()["status"] == "skipped"
    assert scraper_tasks.run_scheduled_chapter_checks()["status"] == "skipped"
    _on(fastapi_client, owner, "scraper")
    assert scraper_tasks.run_scheduled_scrape()["status"] == "ok"


# --------------------------------------------------------------- sign-in methods


def test_sign_in_methods_can_be_switched_off_but_not_all(fastapi_client):
    owner = staff.owner()
    _off(fastapi_client, owner, "sign_in_google")
    _off(fastapi_client, owner, "sign_in_microsoft")
    last = fastapi_client.put(
        f"{URL}/sign_in_magic_link", json={"enabled": False}, headers=staff.headers(owner)
    )
    assert last.status_code == 403
    assert last.json()["error"]["details"]["reason"] == "last_sign_in_method"
    states = fastapi_client.get("/api/v1/config/site-functions").json()["functions"]
    assert states["sign_in_magic_link"] is True


def test_a_disabled_sign_in_method_is_refused_and_hidden(fastapi_client):
    owner = staff.owner()
    _off(fastapi_client, owner, "sign_in_google")
    _off(fastapi_client, owner, "sign_in_microsoft")
    google = fastapi_client.get("/api/v1/auth/google", follow_redirects=False)
    assert "provider_disabled" in _location(google)
    microsoft = fastapi_client.get("/api/v1/auth/microsoft", follow_redirects=False)
    assert "provider_disabled" in _location(microsoft)
    options = fastapi_client.get("/api/v1/auth/options").json()
    assert options["providers"] == ["magic_link"]

    _on(fastapi_client, owner, "sign_in_google")
    _off(fastapi_client, owner, "sign_in_magic_link")
    resp = fastapi_client.post("/api/v1/auth/request-magic-link", json={"email": "x@example.com"})
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "FUNCTION_DISABLED"
    assert "magic_link" not in fastapi_client.get("/api/v1/auth/options").json()["providers"]


# -------------------------------------------------- the functions kept elsewhere


def test_sign_in_required_here_is_the_same_switch_as_before(fastapi_client):
    owner = staff.owner()
    _off(fastapi_client, owner, "sign_in_required")
    assert fastapi_client.get("/api/v1/config/site-access").json() == {"loginRequired": False}
    _on(fastapi_client, owner, "sign_in_required")
    assert fastapi_client.get("/api/v1/config/site-access").json() == {"loginRequired": True}
    # Leave the shared test site open to guests, as the other tests expect.
    _off(fastapi_client, owner, "sign_in_required")


def test_maintenance_and_registration_are_owner_only_even_in_admin_settings(fastapi_client):
    from backend_fastapi.app.services import permissions_service as ps
    from backend_fastapi.app.services import site_content_service as content

    admin = staff.admin()
    with SessionLocal() as session:
        ps.set_override(session, session.get(User, admin), "manage_admin_settings", "granted", None, by_owner=True)
        session.commit()
    resp = fastapi_client.post(
        "/api/v1/admin/settings",
        json={"maintenance_mode": True, "allow_registration": False, "default_reader_mode": "scroll"},
        headers=staff.headers(admin),
    )
    assert resp.status_code == 200, resp.text
    with SessionLocal() as session:
        settings = content.get_site_settings(session)
    assert settings["maintenance_mode"] is False and settings["allow_registration"] is True

    owner = staff.owner()
    _off(fastapi_client, owner, "new_registration")
    with SessionLocal() as session:
        assert content.get_site_settings(session)["allow_registration"] is False
    _on(fastapi_client, owner, "new_registration")


def test_the_owner_only_sign_in_switch_is_not_an_admin_settings_power(fastapi_client):
    admin = staff.admin()
    h = staff.headers(admin)
    assert fastapi_client.put("/api/v1/admin/config/access", json={"login_required": True}, headers=h).status_code == 403
    assert fastapi_client.get("/api/v1/admin/config/access", headers=h).status_code == 403


# --------------------------------------------------------------------- registry


def test_every_function_says_where_it_is_enforced():
    for spec in registry.REGISTRY.values():
        assert spec.enforced_by, spec.key
        assert spec.label and spec.description and spec.group in registry.GROUPS


def test_reset_all_puts_every_function_back_to_its_default(fastapi_client):
    owner = staff.owner()
    for key in ("comments", "ads", "scraper"):
        _off(fastapi_client, owner, key)
    with SessionLocal() as session:
        functions.reset_all(session)
        states = functions.states(session)
    assert all(states[k] == registry.REGISTRY[k].default for k in registry.REGISTRY)


def test_a_typo_in_a_route_guard_fails_at_import():
    from backend_fastapi.app.dependencies.site_functions import require_function

    with pytest.raises(KeyError):
        require_function("comentz")


def test_every_table_function_guards_at_least_one_route():
    """A switch with nothing behind it would be a lie."""

    from _support.route_table import route_table

    guarded = {
        g.removeprefix("require_function_")
        for r in route_table()
        for g in r.gates
        if g.startswith("require_function_")
    }
    # Checked inside their handlers, or mounted outside the API router (sitemap
    # and feeds): each has its own test (here or in test_ip_privacy.py).
    in_code = {"sign_in_google", "sign_in_microsoft", "sitemap_feeds", "ip_owner_only", "record_ips"}
    linked = {k for k, s in registry.REGISTRY.items() if s.store != "table"}
    for key in registry.REGISTRY:
        if key in linked or key in in_code:
            continue
        assert key in guarded, f"{key} switches nothing"


def test_the_site_admin_uses_the_owner_role_only():
    assert UserRole.CO_ADMIN != UserRole.ADMIN
