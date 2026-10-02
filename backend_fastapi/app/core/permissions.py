"""Permission catalogue, role defaults, and never-grantable set (SRS 1F.6–1F.8).

Effective permission = role default (1F.5/1F.7) modified by that person's
explicit override (granted/revoked). Only the Permanent Administrator may change
overrides. Six capabilities (1F.8) are **never grantable** — they have no entry
in the catalogue at all and any attempt to grant them is refused.

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
    "view_providers": (Group.PROVIDERS, True, True),
    "configure_ocr": (Group.PROVIDERS, True, True),
    "configure_translation": (Group.PROVIDERS, True, True),
    "configure_ai": (Group.PROVIDERS, True, True),
    "configure_scraper_ai": (Group.PROVIDERS, True, False),
    "set_provider_priority": (Group.PROVIDERS, True, True),
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
    # User administration
    "view_user_list": (Group.USER_ADMIN, True, True),
    "view_user_detail": (Group.USER_ADMIN, True, True),
    "suspend_account": (Group.USER_ADMIN, True, True),
    "ban_account": (Group.USER_ADMIN, True, True),
    "restore_account": (Group.USER_ADMIN, True, True),
    "revoke_user_sessions": (Group.USER_ADMIN, True, True),
    # Role management
    "promote_secondary": (Group.ROLE_MGMT, True, False),
    "demote_secondary": (Group.ROLE_MGMT, True, False),
    # Platform configuration
    "view_limits": (Group.PLATFORM, True, True),
    "set_limits": (Group.PLATFORM, True, False),
    "set_session_policy": (Group.PLATFORM, True, False),
    "set_resource_policy": (Group.PLATFORM, True, False),
    "configure_branding": (Group.PLATFORM, True, False),
    "manage_ads": (Group.PLATFORM, True, False),
    # Observability
    "view_dashboard": (Group.OBSERVABILITY, True, True),
    "view_scraper_health": (Group.OBSERVABILITY, True, True),
    "view_scope_audit": (Group.OBSERVABILITY, True, True),
    "view_full_audit": (Group.OBSERVABILITY, True, False),
}


# Owner's rules: the Scraper AI (its API key, and creating parsers with it --
# the Series Management "Scraper AI API" and "Custom Parser" sections), API
# Management (OCR / translation / AI providers) and Role Management
# (appointing/removing sub-admins) belong to the main admin alone. The main admin holds these like every catalogue permission; a
# sub-admin can never hold them -- no toggle, preset or stored override grants
# them (enforced in ``permissions_service``).
MAIN_ADMIN_ONLY: frozenset[str] = frozenset(
    {
        "trigger_scraper_ai",
        "configure_scraper_ai",
        "view_providers",
        "configure_ocr",
        "configure_translation",
        "configure_ai",
        "set_provider_priority",
        "promote_secondary",
        "demote_secondary",
    }
)

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
    "view_websites": "See the approved source websites.",
    "approve_website": "Approve a new source website for scraping.",
    "modify_website": "Change an approved website's settings.",
    "remove_website": "Remove an approved website.",
    "trigger_scraper_ai": "Main admin only: create a parser for a website with the Scraper AI (Custom Parser).",
    "approve_parser": "Approve a generated parser.",
    "activate_parser": "Switch a parser on.",
    "rollback_parser": "Go back to an earlier parser version.",
    "view_providers": "Main admin only: see API Management (OCR / translation / AI providers).",
    "configure_ocr": "Main admin only: change OCR providers.",
    "configure_translation": "Main admin only: change translation providers.",
    "configure_ai": "Main admin only: change AI providers.",
    "configure_scraper_ai": "Main admin only: add or change the Scraper AI API key.",
    "set_provider_priority": "Main admin only: reorder providers.",
    "correct_translation": "Fix a wrong translation.",
    "force_regen_translation": "Throw away a cached translation and make it again.",
    "review_quality_flags": "Review translations flagged as poor.",
    "remove_comments": "Delete comments.",
    "block_user": "Block a user from commenting.",
    "timeout_user": "Temporarily stop a user from commenting.",
    "handle_reports": "See and resolve chapter reports.",
    "broadcast": "Write site announcements and pop-up messages.",
    "moderate_images": "Remove reported images.",
    "view_user_list": "Browse the user list.",
    "view_user_detail": "Open a user's account details.",
    "suspend_account": "Suspend an account.",
    "ban_account": "Ban an account.",
    "restore_account": "Restore a suspended or banned account.",
    "revoke_user_sessions": "Sign a user out everywhere.",
    "promote_secondary": "Main admin only: appoint sub-admins (Role Management).",
    "demote_secondary": "Main admin only: remove sub-admins (Role Management).",
    "view_limits": "See usage limits.",
    "set_limits": "Change usage limits.",
    "set_session_policy": "Change how long logins last.",
    "set_resource_policy": "Change resource policies.",
    "configure_branding": "Reserved: logo, footer and social links are main-admin only.",
    "manage_ads": "Create and edit ad slots.",
    "view_dashboard": "See the admin dashboard.",
    "view_scraper_health": "See scraper and source health.",
    "view_scope_audit": "See the audit log for their own actions.",
    "view_full_audit": "See the full audit log.",
}

ALL_PERMISSIONS: tuple[str, ...] = tuple(_CATALOGUE.keys())


def is_valid_permission(key: str) -> bool:
    return key in _CATALOGUE


def effective_role(user) -> UserRole:
    """Fold the legacy boolean admin flags into the strongest implied ``UserRole``.

    F-4/F-5: three "is this principal privileged" resolvers existed with
    three different input sets -- ``dependencies.auth``'s main-admin check
    read ``permanent``/``is_main_admin``/``role``, its secondary-or-higher
    check added ``is_secondary_admin``, while ``role_default`` (via
    ``has_permission``) read only ``role``. A ``User`` row carrying an admin
    *flag* without the matching *role* was an admin to the role-tier gates
    and a nobody to the permission catalogue -- authorised on
    ``require_admin_user`` routes, 403'd on ``require_permission`` routes for
    the same page. This is the single source of truth every "who is this
    principal" check should consult instead of reading ``user.role`` or the
    boolean flags directly.
    """

    if user is None:
        return UserRole.USER
    role = getattr(user, "role", None)

    # Permanent Admin and Admin are one merged, single-owner tier: nothing
    # downstream ever distinguishes the two return values (every consumer
    # checks ``effective_role(...) in {ADMIN, PERMANENT}``, or feeds into
    # ``role_default``, which grants both identical permissions). Nothing
    # newly assigns ``UserRole.ADMIN`` any more (the one-time Admin sign-in,
    # ``routers/admin_login.py``, grants PERMANENT) --
    # the ADMIN branch below exists solely so pre-existing ``role=ADMIN`` rows
    # keep resolving to the owner tier.
    if getattr(user, "permanent", False) or role == UserRole.PERMANENT:
        return UserRole.PERMANENT
    if getattr(user, "is_main_admin", False) or role == UserRole.ADMIN:
        return UserRole.ADMIN
    if getattr(user, "is_secondary_admin", False) or role == UserRole.SECONDARY:
        return UserRole.SECONDARY
    # Three roles: anything else -- including legacy "moderator" rows -- is a
    # regular user.
    return UserRole.USER


def role_default(key: str, role: UserRole) -> bool:
    """The 1F.7 default for ``key`` at ``role`` (Permanent Admin holds all)."""

    entry = _CATALOGUE.get(key)
    if entry is None:
        return False
    _group, _admin_d, secondary_d = entry
    if role in (UserRole.PERMANENT, UserRole.ADMIN):
        # Main/permanent-admin accounts hold every catalogue permission.
        return True
    if key in MAIN_ADMIN_ONLY:
        return False
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
        "description": "Users and accounts. No website approval (API Management is main-admin only).",
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
    for key, (group, admin_d, secondary_d) in _CATALOGUE.items():
        main_only = key in MAIN_ADMIN_ONLY
        out.append(
            {
                "key": key,
                "group": group.value,
                "description": DESCRIPTIONS.get(key, ""),
                # The Role Management page shows no toggle for these.
                "main_admin_only": main_only,
                "defaults": {
                    "permanent_admin": True,
                    "admin": admin_d,
                    "secondary_admin": False if main_only else secondary_d,
                },
            }
        )
    return out
