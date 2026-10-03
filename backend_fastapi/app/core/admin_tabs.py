"""The admin-panel tabs, and which permissions belong to which tab.

Owner's rule (2026-10-02): the owner decides, person by person, which tabs of
the admin panel an Admin or sub-admin sees (Role Management -> Tab access). A
moderator for chapter reports and comments should not see the scraper or API
tabs, so the owner gives that person only the tabs they need.

A tab list is enforced where every permission is decided
(``permissions_service.has_permission``): a person whose list leaves a tab out
loses the permissions bound to that tab (``TabSpec.permissions``), so the tab is
hidden **and** its API refuses them. Permissions bound to no tab (comment
moderation from the reader, translation fixes, ...) are not affected, because
they are used from outside the admin panel. The tab list is only changed by the
owner and can't be delegated.

``functions`` (Site Functions) is the owner's own tab. It has no permission, so
it can't be given to anyone.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TabSpec:
    key: str
    label: str
    path: str
    # Permissions used by this tab's page and nowhere else.
    permissions: tuple[str, ...] = ()
    # Only the owner ever sees it; it can't be handed out.
    owner_only: bool = False
    # A site-owner power tab: a sub-admin can never hold it.
    owner_power: bool = False


_TABS: tuple[TabSpec, ...] = (
    TabSpec(
        "series", "Series Management", "/admin/series",
        (
            "submit_manga_url", "edit_series", "delete_series", "rescrape_series",
            "rollback_series", "set_rights_records", "set_takedown",
            "view_websites", "approve_website", "modify_website", "remove_website",
            "trigger_scraper_ai", "approve_parser", "activate_parser",
            "rollback_parser", "configure_scraper_ai",
        ),
    ),
    TabSpec("chapter-reports", "Chapter Reports", "/admin/chapter-reports", ("handle_reports",)),
    TabSpec(
        "users", "User Database", "/admin/users",
        (
            "view_user_list", "view_user_detail", "suspend_account", "ban_account",
            "restore_account", "revoke_user_sessions", "reveal_user_email",
        ),
    ),
    TabSpec("roles", "Role Management", "/admin/roles", ("manage_roles", "promote_secondary", "demote_secondary")),
    TabSpec("ads", "Ads & Placements", "/admin/ads", ("manage_ads",)),
    # System Health and the audit report both read the server's health data, so
    # ``view_system_health`` belongs to both tabs: a person keeps it while they
    # have either one.
    TabSpec("health", "System Health", "/admin/health", ("view_system_health", "view_scraper_health")),
    TabSpec(
        "audit-report", "Operations & Traffic Audit", "/admin/audit-report",
        ("view_system_health", "view_full_audit", "view_scope_audit"),
    ),
    TabSpec(
        "api-management", "API Management", "/admin/api-management",
        ("view_providers", "manage_providers"), owner_power=True,
    ),
    TabSpec(
        "settings", "Admin Settings", "/admin/settings",
        (
            "manage_admin_settings", "manage_cache", "purge_site_data", "set_limits",
            "set_session_policy", "set_resource_policy", "configure_branding",
            "manage_donations",
        ),
        owner_power=True,
    ),
    TabSpec("vault", "Secret Vault", "/admin/vault", ("manage_secret_vault",), owner_power=True),
    TabSpec("backups", "Storage & Backups", "/admin/backups", ("manage_backups",), owner_power=True),
    TabSpec("geolock", "Geolock", "/admin/geolock", ("manage_geolock",), owner_power=True),
    TabSpec("functions", "Site Functions", "/admin/functions", owner_only=True),
)

TABS: dict[str, TabSpec] = {t.key: t for t in _TABS}

# Tabs the owner can allow or hide for a person (everything but their own).
RESTRICTABLE: tuple[str, ...] = tuple(t.key for t in _TABS if not t.owner_only)

_TABS_OF_PERMISSION: dict[str, tuple[str, ...]] = {}
for _tab in _TABS:
    for _perm in _tab.permissions:
        _TABS_OF_PERMISSION[_perm] = _TABS_OF_PERMISSION.get(_perm, ()) + (_tab.key,)


def tabs_of(permission: str) -> tuple[str, ...]:
    """The tabs a permission belongs to (usually one), or ``()`` when it is used
    outside the panel and so no tab list touches it."""

    return _TABS_OF_PERMISSION.get(permission, ())


def clean_tabs(value, *, sub_admin: bool = False) -> list[str] | None:
    """Validate a tab list from the owner: ``None`` keeps "follow permissions".

    Unknown keys are refused by the route before this is called; here we drop
    duplicates and, for a sub-admin, the site-owner-power tabs they can never hold.
    """

    if value is None:
        return None
    out: list[str] = []
    for key in value:
        if key not in RESTRICTABLE or key in out:
            continue
        if sub_admin and TABS[key].owner_power:
            continue
        out.append(key)
    return out


def catalogue() -> list[dict]:
    return [
        {
            "key": t.key,
            "label": t.label,
            "path": t.path,
            "owner_only": t.owner_only,
            "owner_power": t.owner_power,
            "permissions": list(t.permissions),
        }
        for t in _TABS
    ]
