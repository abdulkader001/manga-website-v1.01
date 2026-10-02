"""Permission catalogue, role defaults, and never-grantable set (SRS 1F.6–1F.8).

Four roles, strongest first (owner's rules, 2026-10-02):

* **Owner** (``PERMANENT``, one person, never changed or touched by anyone)
  holds every catalogue permission.
* **Admin** (``CO_ADMIN``, at most ``MAX_ADMINS``) holds almost everything by
  default -- all but Admin Settings, the cache and "delete all manga"
  (``ADMIN_OFF_BY_DEFAULT``). Only the owner changes an Admin's toggles; an
  Admin has power over sub-admins and users only.
* **Sub-admin** (``SECONDARY``) holds the sub-admin defaults, adjustable by an
  Admin or the owner, never above what the owner's ceiling allows
  (``system_settings.sub_admin_blocked_permissions``).
* **User** holds none.

Effective permission = role default modified by that person's explicit
override (granted/revoked). The site-owner powers (``OWNER_POWERS``) can only be
held by an Admin (or the owner) who also has an authenticator, and are used
only after a fresh code (``permissions_service``, ``dependencies.powers``).
Six capabilities (1F.8) are **never grantable** -- they have no entry in the
catalogue at all.

Resolution order (SRS 1F.10): never-grantable check -> explicit override ->
role default.
"""

from __future__ import annotations

from enum import Enum

from ..models import UserRole


class Group(str, Enum):
    CONTENT = "Content and series"
    WEBSITES = "Websites and scrapers"
    PROVIDERS = "Providers and APIs"
    TRANSLATION = "Translation quality"
    COMMUNITY = "Community and moderation"
    USER_ADMIN = "User administration"
    ROLE_MGMT = "Role management"
    PLATFORM = "Platform configuration"
    OWNER = "Site owner powers"
    OBSERVABILITY = "Observability"


# key -> (group, admin_default, sub_admin_default)
# Three roles only: the main admin holds every catalogue permission, a
# sub-admin holds their defaults (individually adjustable), and a regular
# user holds none.
_CATALOGUE: dict[str, tuple[Group, bool, bool]] = {
    # Content and series
    "submit_manga_url": (Group.CONTENT, True, True),
    "edit_series": (Group.CONTENT, True, True),
    "delete_series": (Group.CONTENT, True, True),
    "rescrape_chapter": (Group.CONTENT, True, True),
    "rescrape_series": (Group.CONTENT, True, True),
    "rollback_series": (Group.CONTENT, True, False),
    "set_rights_records": (Group.CONTENT, True, True),
    "set_takedown": (Group.CONTENT, True, False),
    # Websites and scrapers
    "view_websites": (Group.WEBSITES, True, True),
    "approve_website": (Group.WEBSITES, True, False),
    "modify_website": (Group.WEBSITES, True, False),
    "remove_website": (Group.WEBSITES, True, False),
    "trigger_scraper_ai": (Group.WEBSITES, True, False),
    "approve_parser": (Group.WEBSITES, True, False),
    "activate_parser": (Group.WEBSITES, True, False),
    "rollback_parser": (Group.WEBSITES, True, False),
    # Providers and APIs
    "view_providers": (Group.PROVIDERS, True, False),
    "manage_providers": (Group.PROVIDERS, True, False),
    "configure_scraper_ai": (Group.PROVIDERS, True, False),
    # Translation quality
    "correct_translation": (Group.TRANSLATION, True, True),
    "force_regen_translation": (Group.TRANSLATION, True, True),
    "review_quality_flags": (Group.TRANSLATION, True, True),
    # Community and moderation
    "remove_comments": (Group.COMMUNITY, True, True),
    "block_user": (Group.COMMUNITY, True, True),
    "timeout_user": (Group.COMMUNITY, True, True),
    "handle_reports": (Group.COMMUNITY, True, True),
    "broadcast": (Group.COMMUNITY, True, True),
    "moderate_images": (Group.COMMUNITY, True, True),
    "manage_community": (Group.COMMUNITY, True, False),
    # User administration
    "view_user_list": (Group.USER_ADMIN, True, True),
    "view_user_detail": (Group.USER_ADMIN, True, True),
    "suspend_account": (Group.USER_ADMIN, True, True),
    "ban_account": (Group.USER_ADMIN, True, True),
    "restore_account": (Group.USER_ADMIN, True, True),
    "revoke_user_sessions": (Group.USER_ADMIN, True, True),
    "reveal_user_email": (Group.USER_ADMIN, True, False),
    # Role management
    "manage_roles": (Group.ROLE_MGMT, True, False),
    "promote_secondary": (Group.ROLE_MGMT, True, False),
    "demote_secondary": (Group.ROLE_MGMT, True, False),
    # Platform configuration
    "view_limits": (Group.PLATFORM, True, True),
    "set_limits": (Group.PLATFORM, True, False),
    "set_session_policy": (Group.PLATFORM, True, False),
    "set_resource_policy": (Group.PLATFORM, True, False),
    "configure_branding": (Group.PLATFORM, True, False),
    "manage_ads": (Group.PLATFORM, True, False),
    # Site owner powers
    "manage_admin_settings": (Group.OWNER, True, False),
    "manage_cache": (Group.OWNER, True, False),
    "purge_site_data": (Group.OWNER, True, False),
    "manage_secret_vault": (Group.OWNER, True, False),
    "manage_donations": (Group.OWNER, True, False),
    "manage_backups": (Group.OWNER, True, False),
    "manage_geolock": (Group.OWNER, True, False),
    # Observability
    "view_dashboard": (Group.OBSERVABILITY, True, True),
    "view_scraper_health": (Group.OBSERVABILITY, True, True),
    "view_scope_audit": (Group.OBSERVABILITY, True, True),
    "view_full_audit": (Group.OBSERVABILITY, True, False),
    "view_system_health": (Group.OBSERVABILITY, True, False),
}


# Site-owner powers (owner's rules, 2026-10-02). An Admin holds most of them by
# default (all but ``ADMIN_OFF_BY_DEFAULT``); the owner can switch any of them
# off, or on, per Admin. Guardrails (enforced in ``permissions_service`` and
# the role routes):
#   * only the owner switches them for an Admin, each time they are switched
#     *on* with the owner's authenticator code;
#   * a sub-admin can never hold one, however it is set;
#   * the holder must have an authenticator, and uses them only after a
#     fresh code (the admin step-up);
#   * never part of a preset; nobody changes their own permissions; an Admin
#     can't change another Admin.
OWNER_POWERS: frozenset[str] = frozenset(
    {
        "manage_secret_vault",
        "manage_admin_settings",
        "manage_cache",
        "purge_site_data",
        "view_providers",
        "manage_providers",
        "configure_scraper_ai",
        "trigger_scraper_ai",
        "manage_roles",
        "promote_secondary",
        "demote_secondary",
        "configure_branding",
        "manage_donations",
        "manage_backups",
        "manage_geolock",
        "reveal_user_email",
    }
)
MAX_ADMINS = 2

# What an Admin does NOT hold until the owner switches it on: Admin Settings
# (with its cache tools) and "delete all manga / purge all images".
ADMIN_OFF_BY_DEFAULT: frozenset[str] = frozenset(
    {"manage_admin_settings", "manage_cache", "purge_site_data"}
)

# The pool of sub-admin seats Admins share. The owner splits it between the
# Admins (an equal share unless set), and no one's share can push the total
# above it. The owner's own appointments don't use it.
SUB_ADMIN_POOL = 50

# SRS 1F.8 — no toggle exists for these; absent from the catalogue entirely.
NEVER_GRANTABLE: frozenset[str] = frozenset(
    {
        "modify_permanent_admin",
        "assign_permanent_admin",
        "view_user_credentials",
        "translate_rights_blocked",
        "edit_audit_log",
        "alter_rank",
    }
)

# Plain-language meaning of each toggle, shown on the Role Management page.
DESCRIPTIONS: dict[str, str] = {
    "submit_manga_url": "Import a new series from a source site.",
    "edit_series": "Edit series details, schedules, page layout and delete single pages.",
    "delete_series": "Delete a whole series.",
    "rescrape_chapter": "Re-scrape one chapter (reader Re-Scrape button and report fixes).",
    "rescrape_series": "Re-scrape every chapter of a series.",
    "rollback_series": "Roll a series back to an earlier scrape.",
    "set_rights_records": "Record who owns the rights to a series and whether it may be translated.",
    "set_takedown": "Take a series down (or put it back) after a rights complaint.",
    "view_websites": "See the approved source websites.",
    "approve_website": "Approve a new source website for scraping.",
    "modify_website": "Change an approved website's settings.",
    "remove_website": "Remove an approved website.",
    "trigger_scraper_ai": "Create parsers for websites with the Scraper AI (Custom Parser).",
    "approve_parser": "Approve a generated parser.",
    "activate_parser": "Switch a parser on.",
    "rollback_parser": "Go back to an earlier parser version.",
    "view_providers": "See API Management (OCR / translation / AI providers).",
    "manage_providers": "Add, change, test, reorder and delete OCR / translation / AI providers and their keys.",
    "configure_scraper_ai": "Add or change the Scraper AI API key.",
    "correct_translation": "Fix a wrong translation.",
    "force_regen_translation": "Throw away a cached translation and make it again.",
    "review_quality_flags": "Review translations flagged as poor.",
    "remove_comments": "Delete comments.",
    "block_user": "Block a user from commenting.",
    "timeout_user": "Temporarily stop a user from commenting.",
    "handle_reports": "See and resolve chapter reports.",
    "broadcast": "Write site announcements and pop-up messages.",
    "moderate_images": "Remove reported images.",
    "manage_community": "Custom emojis and community realms.",
    "view_user_list": "Browse the user list.",
    "view_user_detail": "Open a user's account details.",
    "suspend_account": "Suspend an account.",
    "ban_account": "Ban an account.",
    "restore_account": "Restore a suspended or banned account.",
    "revoke_user_sessions": "Sign a user out everywhere.",
    "reveal_user_email": "See the real e-mail address of sub-admins and users (never an Admin's or the owner's).",
    "manage_roles": "Role Management: change sub-admins' everyday powers (never site-owner powers, never their own, never another Admin's).",
    "promote_secondary": "Appoint sub-admins (an Admin's seats are limited by the owner).",
    "demote_secondary": "Remove sub-admins.",
    "view_limits": "See usage limits.",
    "set_limits": "Change usage limits.",
    "set_session_policy": "Change how long logins last.",
    "set_resource_policy": "Change resource policies.",
    "configure_branding": "Logo, site name, footer and social links.",
    "manage_ads": "Create and edit ad slots and ad networks.",
    "manage_admin_settings": "Admin Settings: site settings, sign-in required switch, maintenance, image mirroring.",
    "manage_cache": "See, refresh, reprioritise and clear the site cache.",
    "purge_site_data": "Danger: delete all manga and purge all images.",
    "manage_secret_vault": "Secret Vault: the site's secret settings and domain.",
    "manage_donations": "Donation links and crypto addresses.",
    "manage_backups": "Storage & Backups: connect storage, make, download and restore backups.",
    "manage_geolock": "Geolock: choose countries that can't open the site.",
    "view_dashboard": "See the admin dashboard.",
    "view_scraper_health": "See scraper and source health.",
    "view_scope_audit": "See the audit log for their own actions.",
    "view_full_audit": "See the full audit log.",
    "view_system_health": "System health, diagnostics, server stats and the security report.",
}

ALL_PERMISSIONS: tuple[str, ...] = tuple(_CATALOGUE.keys())


def is_valid_permission(key: str) -> bool:
    return key in _CATALOGUE


# The owner tier: ``PERMANENT`` and the legacy ``ADMIN`` alias resolve alike.
OWNER_ROLES = frozenset({UserRole.PERMANENT, UserRole.ADMIN})

_RANK = {
    UserRole.PERMANENT: 3,
    UserRole.ADMIN: 3,
    UserRole.CO_ADMIN: 2,
    UserRole.SECONDARY: 1,
    UserRole.USER: 0,
}


def effective_role(user) -> UserRole:
    """Fold the legacy boolean admin flags into the strongest implied ``UserRole``.

    F-4/F-5: three "is this principal privileged" resolvers existed with
    three different input sets. This is the single source of truth every "who
    is this principal" check consults instead of reading ``user.role`` or the
    boolean flags directly.

    The owner tier is one merged tier: ``permanent``, ``is_main_admin`` and
    both ``PERMANENT`` and the legacy ``ADMIN`` role resolve to it (nothing
    downstream distinguishes the two return values). The Admin tier is
    ``CO_ADMIN``. A legacy ``is_secondary_admin`` flag alone is a sub-admin.
    """

    if user is None:
        return UserRole.USER
    role = getattr(user, "role", None)

    if getattr(user, "permanent", False) or role == UserRole.PERMANENT:
        return UserRole.PERMANENT
    if getattr(user, "is_main_admin", False) or role == UserRole.ADMIN:
        return UserRole.ADMIN
    if role == UserRole.CO_ADMIN:
        return UserRole.CO_ADMIN
    if getattr(user, "is_secondary_admin", False) or role == UserRole.SECONDARY:
        return UserRole.SECONDARY
    # Anything else -- including legacy "moderator" rows -- is a regular user.
    return UserRole.USER


def rank(user) -> int:
    """3 owner, 2 Admin, 1 sub-admin, 0 user. Power over a person needs a
    strictly higher rank, and nobody outranks the owner."""

    return _RANK[effective_role(user)]


def is_owner(user) -> bool:
    return effective_role(user) in OWNER_ROLES


def is_admin_tier(user) -> bool:
    """True for an Admin (not the owner)."""

    return effective_role(user) == UserRole.CO_ADMIN


def role_label(user) -> str:
    return {3: "owner", 2: "admin", 1: "sub_admin", 0: "user"}[rank(user)]


def role_default(key: str, role: UserRole) -> bool:
    """The 1F.7 default for ``key`` at ``role`` (the owner holds all)."""

    entry = _CATALOGUE.get(key)
    if entry is None:
        return False
    _group, _admin_d, secondary_d = entry
    if role in OWNER_ROLES:
        return True
    if role == UserRole.CO_ADMIN:
        return key not in ADMIN_OFF_BY_DEFAULT
    if key in OWNER_POWERS:
        return False  # a sub-admin never holds a site-owner power
    if role == UserRole.SECONDARY:
        return secondary_d
    # Registered users / guests hold no catalogue (admin) permissions.
    return False


# SRS 1F.9.3 — built-in presets: ready-made permission shapes for a
# sub-admin (the only role with adjustable permissions). Each is expressed as explicit grant/revoke
# lists; applying a preset resets the person to role defaults, then sets these
# explicit overrides (which remain individually adjustable afterwards).
BUILTIN_PRESETS: dict[str, dict] = {
    "community_moderator": {
        "label": "Sub-admin: Community",
        "description": "Comments, blocks, timeouts, reports. No content or scraping.",
        "grant": [
            "remove_comments",
            "block_user",
            "timeout_user",
            "handle_reports",
            "moderate_images",
        ],
        "revoke": [
            "submit_manga_url",
            "edit_series",
            "rescrape_chapter",
            "set_rights_records",
            "correct_translation",
            "review_quality_flags",
        ],
    },
    "content_moderator": {
        "label": "Sub-admin: Content",
        "description": "Manga URLs, series edits, chapter rescrape, translation fixes.",
        "grant": [
            "submit_manga_url",
            "edit_series",
            "rescrape_chapter",
            "correct_translation",
            "review_quality_flags",
            "set_rights_records",
        ],
        "revoke": [
            "remove_comments",
            "block_user",
            "timeout_user",
            "handle_reports",
            "moderate_images",
        ],
    },
    "translation_moderator": {
        "label": "Sub-admin: Translation",
        "description": "Translation corrections and quality review only.",
        "grant": ["correct_translation", "review_quality_flags"],
        "revoke": [
            "submit_manga_url",
            "edit_series",
            "rescrape_chapter",
            "set_rights_records",
            "remove_comments",
            "block_user",
            "timeout_user",
            "handle_reports",
            "moderate_images",
        ],
    },
    "operations_admin": {
        "label": "Sub-admin: Operations",
        "description": "Users and accounts. No website approval.",
        "grant": [
            "view_user_list",
            "view_user_detail",
            "suspend_account",
            "restore_account",
        ],
        "revoke": ["approve_website", "modify_website", "remove_website"],
    },
    "titular": {
        "label": "Sub-admin: Titular",
        "description": "A recognition role with almost no operational power.",
        "grant": [],
        # Near-empty: revoke every catalogue permission.
        "revoke": list(_CATALOGUE.keys()),
    },
}


def builtin_presets() -> list[dict]:
    out = []
    for key, p in BUILTIN_PRESETS.items():
        out.append(
            {
                "key": key,
                "label": p["label"],
                "description": p["description"],
                "grant": p["grant"],
                "revoke": p["revoke"],
                "builtin": True,
            }
        )
    return out


def catalogue() -> list[dict]:
    """The full catalogue grouped for the toggle page (SRS 1F.9.2)."""

    out: list[dict] = []
    for key, (group, _admin_d, secondary_d) in _CATALOGUE.items():
        owner_power = key in OWNER_POWERS
        out.append(
            {
                "key": key,
                "group": group.value,
                "description": DESCRIPTIONS.get(key, ""),
                # Only the owner grants these, with an authenticator code.
                "owner_power": owner_power,
                "defaults": {
                    "permanent_admin": True,
                    "admin": key not in ADMIN_OFF_BY_DEFAULT,
                    "secondary_admin": False if owner_power else secondary_d,
                },
            }
        )
    return out
