"""Are all the routes connected properly? (owner's request, 2026-10-02)

Reads the real backend route table and the React source and checks that they
agree, so a mismatch fails here instead of showing up as a dead page:

* every API call the frontend makes has a backend route;
* every ``/admin`` route is behind an admin gate, and every staff-only route
  names the power it needs (the few exceptions are listed and explained);
* every admin tab has a page, a route guard and a permission that agree with
  the backend tab registry, and the page's main API call needs that permission;
* the owner-only pages (Site Functions, Tab access) have no permission at all;
* readers' content routes sit behind "Sign-in required", and the list of
  routes anyone can call without signing in is exactly the one below.
"""

from __future__ import annotations

import pytest

from backend_fastapi.app.core import admin_tabs
from backend_fastapi.app.core.permissions import ALL_PERMISSIONS
from _support import frontend_scan as fs
from _support.route_table import route_table

TABLE = route_table()
ADMIN_GATES = {"require_admin_user", "require_main_admin_user"}


def _find(method: str, path: str):
    return [r for r in TABLE if method in r.methods and fs.segments_match(fs.normalise(path), fs.normalise(r.path))]


# ------------------------------------------------------- frontend <-> backend


def test_every_frontend_call_has_a_backend_route():
    helpers = fs.helper_map()
    missing = []
    for file in fs.source_files():
        for method, path in fs.page_calls(file.read_text(), helpers):
            if not _find(method, path):
                missing.append(f"{method} {path}  ({file.relative_to(fs.SRC)})")
    assert not missing, "the frontend calls routes the backend does not have:\n" + "\n".join(sorted(set(missing)))


def test_the_helper_map_reads_the_api_client():
    helpers = fs.helper_map()
    assert helpers["admin.permissions.mine"] == [("GET", "/admin/permissions/me")]
    assert ("PUT", "/admin/site-functions/{}") in helpers["admin.siteFunctions.set"]
    assert ("PUT", "/admin/roles/tab-access/{}") in helpers["admin.tabAccess.set"]
    assert len(helpers) > 100


# ------------------------------------------------------------ admin gates

# Staff-only on purpose: an admin's own session, own audit rows, own authenticator.
STAFF_ONLY = {
    ("GET", "/admin/status"),
    ("GET", "/admin/notifications"),
    ("GET", "/admin/audit/logs"),  # scoped to the viewer's own rows unless view_full_audit
    ("GET", "/admin/audit/logs/search"),
}
OWN_SESSION = {
    "/admin/permissions/me",  # answers a person whose powers are off, to say so
    "/admin/2fa/status", "/admin/2fa/setup", "/admin/2fa/enable", "/admin/2fa/verify", "/admin/2fa/disable",
}


def test_every_admin_route_is_behind_an_admin_gate():
    bare = [
        f"{','.join(r.methods)} {r.path}"
        for r in TABLE
        if r.path.startswith("/admin")
        and not r.powers
        and not (ADMIN_GATES & set(r.gates))
        and r.path not in OWN_SESSION
        and r.path != "/admin/scraper/tasks/{task_id}"  # a task's own requester (checked in the handler)
    ]
    assert not bare, "admin routes with no admin gate:\n" + "\n".join(bare)


def test_staff_only_routes_are_only_the_listed_ones():
    loose = {
        (r.methods[0], r.path)
        for r in TABLE
        if not r.powers and "require_admin_user" in r.gates
    }
    assert loose <= STAFF_ONLY, f"routes any staff member can call, with no power named: {sorted(loose - STAFF_ONLY)}"


def test_every_named_power_exists():
    named = {p for r in TABLE for p in r.powers}
    assert named <= set(ALL_PERMISSIONS), named - set(ALL_PERMISSIONS)


def test_owner_only_routes_name_no_permission():
    owner_only = [r for r in TABLE if r.path.startswith(("/admin/site-functions", "/admin/roles/tab-access"))]
    assert owner_only
    for r in owner_only:
        assert not r.powers, r.path
        assert "require_main_admin_user" in r.gates, r.path


# ---------------------------------------------------------------- admin tabs

# Each tab's page reads this route first; its permission must be the tab's.
PRIMARY_CALL = {
    "series": ("GET", "/admin/series"),
    "chapter-reports": ("GET", "/reports/chapters"),
    "users": ("GET", "/admin/users"),
    "roles": ("GET", "/admin/permissions/catalogue"),
    "ads": ("GET", "/admin/ads"),
    "health": ("GET", "/health"),
    "audit-report": ("GET", "/admin/audit-report"),
    "error-report": ("GET", "/admin/error-reports"),
    "api-management": ("GET", "/admin/api-registry"),
    "settings": ("GET", "/admin/settings"),
    "vault": ("GET", "/admin/vault"),
    "backups": ("GET", "/admin/backups"),
    "geolock": ("GET", "/admin/geolock"),
}


def _links():
    return {link["key"]: link for link in fs.feature_links()}


def test_the_tab_registry_and_the_admin_hub_list_the_same_tabs():
    assert set(_links()) == set(admin_tabs.TABS)
    for key, link in _links().items():
        assert link["to"] == admin_tabs.TABS[key].path, key


def test_each_tile_permission_belongs_to_its_tab():
    for key, link in _links().items():
        tab = admin_tabs.TABS[key]
        if tab.owner_only:
            assert link["permission"] is None and link["minRole"] == "owner", key
            continue
        assert link["minRole"] == "secondary", key
        assert link["permission"] in tab.permissions, f"{key}: tile needs {link['permission']}, tab binds {tab.permissions}"


def test_each_route_guard_matches_its_tile():
    links = _links()
    by_path = {link["to"]: link for link in links.values()}
    routes = {r["path"]: r for r in fs.admin_routes()}
    for path, link in by_path.items():
        route = routes.get(path)
        assert route is not None, f"{path} has no route in src/app.js"
        if link["permission"] is None:
            assert route["main_admin_only"], f"{path} must be owner only"
        else:
            assert not route["main_admin_only"], f"{path}: owner-only route for a tile that follows a permission"
            assert route["permission"] == link["permission"], f"{path}: route guard {route['permission']} != tile {link['permission']}"
    # The ad-slot editor is part of the ads tab.
    assert routes["/admin/ad-slots"]["permission"] == by_path["/admin/ads"]["permission"]


def test_each_tab_page_exists_and_its_main_call_needs_the_tabs_permission():
    for key, (method, path) in PRIMARY_CALL.items():
        tab = admin_tabs.TABS[key]
        routes = _find(method, path)
        assert routes, f"{key}: {method} {path} is not a backend route"
        needed = set(routes[0].powers)
        assert needed, f"{key}: {method} {path} names no power"
        assert needed <= set(tab.permissions), f"{key}: page reads {path} which needs {needed}, tab binds {tab.permissions}"
        assert _links()[key]["permission"] in needed or _links()[key]["permission"] in tab.permissions


def test_every_tab_page_file_exists():
    for route in fs.admin_routes():
        assert route["file"] is not None, f"{route['path']}: no page file for {route['component']}"


def test_no_permission_is_bound_to_a_tab_that_does_not_exist():
    for tab in admin_tabs.TABS.values():
        for key in tab.permissions:
            assert key in ALL_PERMISSIONS


# ------------------------------------------------------------ who needs to sign in

# Everything a guest may call. A new entry here is a decision, not an accident.
PUBLIC = {
    ("GET", "/auth/microsoft"), ("GET", "/auth/microsoft/callback"),
    ("POST", "/auth/refresh"), ("POST", "/auth/request-magic-link"), ("POST", "/auth/magic/request"),
    ("GET", "/auth/magic-link/{token}"), ("GET", "/auth/magic/verify"), ("POST", "/auth/logout"),
    ("GET", "/auth/options"), ("GET", "/auth/google"), ("GET", "/auth/google/callback"),
    ("GET", "/auth/callback"), ("GET", "/auth/{provider}"),
    ("GET", "/branding"), ("GET", "/branding/assets/{filename}"), ("GET", "/footer"),
    ("GET", "/config/providers"), ("GET", "/config/site-functions"), ("GET", "/config/site-access"),
    ("GET", "/version"), ("GET", "/system/state"), ("GET", "/system/health"),
    ("GET", "/user/overlay-fonts"), ("GET", "/social-links"), ("GET", "/geo/status"),
    # Readers' browsers report their script errors to Admin -> Error Report,
    # guests included; rate-limited, and nothing identifying is stored.
    ("POST", "/errors/report"),
}
SIGNED_IN = {"get_current_user", "get_optional_user", "require_admin_user", "require_main_admin_user", "require_processing_user"}


def test_the_routes_a_guest_can_call_are_exactly_the_listed_ones():
    open_routes = {
        (r.methods[0], r.path)
        for r in TABLE
        if not r.powers and not (SIGNED_IN & set(r.gates)) and "require_site_access" not in r.gates
    }
    assert open_routes == PUBLIC, (
        f"unexpected open routes: {sorted(open_routes - PUBLIC)}; gone: {sorted(PUBLIC - open_routes)}"
    )


@pytest.mark.parametrize("module", ["manga", "reader", "comments", "community", "bookmarks", "history", "glossary", "ads"])
def test_reading_routes_sit_behind_sign_in_required(module):
    routes = [r for r in TABLE if r.module == module]
    assert routes, module
    for r in routes:
        assert "require_site_access" in r.gates or r.path.startswith("/admin"), f"{r.methods} {r.path}"
