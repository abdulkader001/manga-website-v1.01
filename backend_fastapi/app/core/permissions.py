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


# key -> (group, admin_default, secondary_default, moderator_default)
# The Permanent Administrator holds every catalogue permission by default.
_CATALOGUE: dict[str, tuple[Group, bool, bool, bool]] = {
    # Content and series
    "submit_manga_url": (Group.CONTENT, True, True, True),
    "edit_series": (Group.CONTENT, True, True, True),
    "delete_series": (Group.CONTENT, True, True, False),
    "rescrape_chapter": (Group.CONTENT, True, True, True),
    "rescrape_series": (Group.CONTENT, True, True, False),
    "rollback_series": (Group.CONTENT, True, False, False),
    "set_rights_records": (Group.CONTENT, True, True, True),
    # Websites and scrapers
    "view_websites": (Group.WEBSITES, True, True, True),
    "approve_website": (Group.WEBSITES, True, False, False),
    "modify_website": (Group.WEBSITES, True, False, False),
    "remove_website": (Group.WEBSITES, True, False, False),
    "trigger_scraper_ai": (Group.WEBSITES, True, False, False),
    "approve_parser": (Group.WEBSITES, True, False, False),
    "activate_parser": (Group.WEBSITES, True, False, False),
    "rollback_parser": (Group.WEBSITES, True, False, False),
    # Providers and APIs
    "view_providers": (Group.PROVIDERS, True, True, False),
    "configure_ocr": (Group.PROVIDERS, True, True, False),
    "configure_translation": (Group.PROVIDERS, True, True, False),
    "configure_ai": (Group.PROVIDERS, True, True, False),
    "configure_scraper_ai": (Group.PROVIDERS, True, False, False),
    "set_provider_priority": (Group.PROVIDERS, True, True, False),
    # Translation quality
    "correct_translation": (Group.TRANSLATION, True, True, True),
    "force_regen_translation": (Group.TRANSLATION, True, True, False),
    "review_quality_flags": (Group.TRANSLATION, True, True, True),
    # Community and moderation
    "remove_comments": (Group.COMMUNITY, True, True, True),
    "block_user": (Group.COMMUNITY, True, True, True),
    "timeout_user": (Group.COMMUNITY, True, True, True),
    "handle_reports": (Group.COMMUNITY, True, True, True),
    "moderate_images": (Group.COMMUNITY, True, True, True),
    # User administration
    "view_user_list": (Group.USER_ADMIN, True, True, False),
    "view_user_detail": (Group.USER_ADMIN, True, True, False),
    "suspend_account": (Group.USER_ADMIN, True, True, False),
    "ban_account": (Group.USER_ADMIN, True, True, False),
    "restore_account": (Group.USER_ADMIN, True, True, False),
    "revoke_user_sessions": (Group.USER_ADMIN, True, True, False),
    # Role management
    "promote_moderator": (Group.ROLE_MGMT, True, True, False),
    "demote_own_moderators": (Group.ROLE_MGMT, True, True, False),
    "demote_any_moderator": (Group.ROLE_MGMT, True, False, False),
    "promote_secondary": (Group.ROLE_MGMT, True, False, False),
    "demote_secondary": (Group.ROLE_MGMT, True, False, False),
    # Platform configuration
    "view_limits": (Group.PLATFORM, True, True, False),
    "set_limits": (Group.PLATFORM, True, False, False),
    "set_session_policy": (Group.PLATFORM, True, False, False),
    "set_resource_policy": (Group.PLATFORM, True, False, False),
    "configure_branding": (Group.PLATFORM, True, False, False),
    # Observability
    "view_dashboard": (Group.OBSERVABILITY, True, True, True),
    "view_scraper_health": (Group.OBSERVABILITY, True, True, False),
    "view_scope_audit": (Group.OBSERVABILITY, True, True, False),
    "view_full_audit": (Group.OBSERVABILITY, True, False, False),
}


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
    # newly assigns ``UserRole.ADMIN`` any more (see
    # ``auth_service._apply_main_admin_role`` and
    # ``admin_bootstrap.redeem_admin_token``, which both grant PERMANENT) --
    # the ADMIN branch below exists solely so pre-existing ``role=ADMIN`` rows
    # keep resolving to the owner tier.
    if getattr(user, "permanent", False) or role == UserRole.PERMANENT:
        return UserRole.PERMANENT
    if getattr(user, "is_main_admin", False) or role == UserRole.ADMIN:
        return UserRole.ADMIN
    if getattr(user, "is_secondary_admin", False) or role == UserRole.SECONDARY:
        return UserRole.SECONDARY
    if role is not None:
        return role
    return UserRole.USER


def role_default(key: str, role: UserRole) -> bool:
    """The 1F.7 default for ``key`` at ``role`` (Permanent Admin holds all)."""

    entry = _CATALOGUE.get(key)
    if entry is None:
        return False
    _group, admin_d, secondary_d, moderator_d = entry
    if role in (UserRole.PERMANENT, UserRole.ADMIN):
        # Main/permanent-admin accounts hold every catalogue permission.
        return True
    if role == UserRole.SECONDARY:
        return secondary_d
    moderator_role = getattr(UserRole, "MODERATOR", None)
    if moderator_role is not None and role == moderator_role:
        return moderator_d
    # Registered users / guests hold no catalogue (admin) permissions.
    return False


# SRS 1F.9.3 — built-in presets. Each is expressed as explicit grant/revoke
# lists; applying a preset resets the person to role defaults, then sets these
# explicit overrides (which remain individually adjustable afterwards).
BUILTIN_PRESETS: dict[str, dict] = {
    "community_moderator": {
        "label": "Community Moderator",
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
        "label": "Content Moderator",
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
        "label": "Translation Moderator",
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
        "label": "Operations Admin",
        "description": "Providers, limits, users. No website approval.",
        "grant": [
            "view_providers",
            "configure_ocr",
            "configure_translation",
            "configure_ai",
            "set_provider_priority",
            "view_user_list",
            "view_user_detail",
            "suspend_account",
            "restore_account",
        ],
        "revoke": ["approve_website", "modify_website", "remove_website"],
    },
    "titular": {
        "label": "Titular",
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
    for key, (group, admin_d, secondary_d, moderator_d) in _CATALOGUE.items():
        out.append(
            {
                "key": key,
                "group": group.value,
                "defaults": {
                    "permanent_admin": True,
                    "admin": admin_d,
                    "secondary_admin": secondary_d,
                    "moderator": moderator_d,
                },
            }
        )
    return out
