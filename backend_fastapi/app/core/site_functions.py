"""The website's main functions the owner can switch on and off.

Owner's rule (2026-10-02): one page (Admin -> Site Functions) lists every main
function of the website, and the owner switches each one on or off. The page is
for the owner **only**: there is no permission for it, so nobody can be given
access, not even an Admin.

A switch is only honest if the server enforces it, so every function here has an
enforcement point (``enforced_by``) that ``tests/test_site_functions.py`` checks:
the routes of that function answer ``FUNCTION_DISABLED`` while it is off, and the
page hides what it can't use (``src/hooks/useSiteFunctions.js``).

``store`` says where the value lives:

* ``table``: a row in ``site_functions`` (no row = the default below);
* ``login_required``: ``system_settings.login_required`` (the older
  "Sign-in required" switch, read by ``dependencies.site_access``);
* ``site_setting:<key>``: a key in the site settings JSON (maintenance mode and
  new registrations, read by the maintenance middleware and sign-in).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FunctionSpec:
    key: str
    label: str
    group: str
    description: str
    default: bool
    store: str = "table"
    enforced_by: str = ""
    # A short warning shown before the owner switches it off.
    warning: str = ""


G_ACCESS = "Sign-in and access"
G_READING = "Reading and community"
G_TRANSLATION = "Translation and OCR"
G_SITE = "Site content"
G_SCRAPING = "Scraping"
G_PRIVACY = "Privacy and security"

SIGN_IN_METHODS = ("sign_in_google", "sign_in_microsoft", "sign_in_magic_link")

_SPECS: tuple[FunctionSpec, ...] = (
    FunctionSpec(
        "sign_in_required",
        "Sign-in required for everyone",
        G_ACCESS,
        "Visitors must sign in before they can see anything. Off lets guests browse and read.",
        False,
        store="login_required",
        enforced_by="dependencies.site_access.require_site_access",
    ),
    FunctionSpec(
        "maintenance_mode",
        "Maintenance mode",
        G_ACCESS,
        "Everyone below sub-admin sees a maintenance notice. Sign-in and the admin area keep working.",
        False,
        store="site_setting:maintenance_mode",
        enforced_by="services.maintenance (middleware)",
    ),
    FunctionSpec(
        "new_registration",
        "New accounts",
        G_ACCESS,
        "Let new people create an account. Off: only existing accounts can sign in.",
        True,
        store="site_setting:allow_registration",
        enforced_by="services.auth_service / oauth (registration_open)",
    ),
    FunctionSpec(
        "sign_in_google",
        "Sign in with Google",
        G_ACCESS,
        "The Continue with Google button and its sign-in route.",
        True,
        enforced_by="api.routers.auth (google routes)",
        warning="At least one sign-in method must stay on.",
    ),
    FunctionSpec(
        "sign_in_microsoft",
        "Sign in with Microsoft",
        G_ACCESS,
        "The Continue with Microsoft button and its sign-in route.",
        True,
        enforced_by="api.routers.account (microsoft routes)",
        warning="At least one sign-in method must stay on.",
    ),
    FunctionSpec(
        "sign_in_magic_link",
        "Sign in with an e-mail link",
        G_ACCESS,
        "Asking for a sign-in link by e-mail. Links already sent still work until they expire.",
        True,
        enforced_by="api.routers.auth (request-magic-link)",
        warning="At least one sign-in method must stay on.",
    ),
    FunctionSpec(
        "comments",
        "Comments",
        G_READING,
        "Reading and writing comments on chapters and series.",
        True,
        enforced_by="router dependency (comments)",
    ),
    FunctionSpec(
        "community",
        "Community (emojis and realms)",
        G_READING,
        "Custom emojis, community realms and their pages.",
        True,
        enforced_by="router dependency (community)",
    ),
    FunctionSpec(
        "chapter_reports",
        "Chapter reports",
        G_READING,
        "Readers reporting a broken chapter or page.",
        True,
        enforced_by="api.routers.reader (report routes)",
    ),
    FunctionSpec(
        "notifications",
        "Notifications",
        G_READING,
        "The notification bell and the notification list.",
        True,
        enforced_by="router dependency (notifications)",
    ),
    FunctionSpec(
        "ocr",
        "OCR (reading text on pages)",
        G_TRANSLATION,
        "Reading the text on manga pages on the server.",
        True,
        enforced_by="router dependency (ocr, processing)",
    ),
    FunctionSpec(
        "translation",
        "Translation",
        G_TRANSLATION,
        "Translating text and page overlays through the API providers.",
        True,
        enforced_by="router dependency (translation)",
    ),
    FunctionSpec(
        "ads",
        "Ads",
        G_SITE,
        "Showing ad slots and placements to readers.",
        True,
        enforced_by="router dependency (ads)",
    ),
    FunctionSpec(
        "support_links",
        "Support and donation links",
        G_SITE,
        "The public support / donation links in the footer and support page.",
        True,
        enforced_by="router dependency (support)",
    ),
    FunctionSpec(
        "sitemap_feeds",
        "Sitemap and RSS",
        G_SITE,
        "sitemap.xml and the RSS feed.",
        True,
        enforced_by="router dependency (seo)",
    ),
    FunctionSpec(
        "ip_owner_only",
        "Visitor IP addresses are for the owner only",
        G_PRIVACY,
        "Only the owner can see IP addresses (audit log, user records). Everyone else sees them hidden.",
        True,
        enforced_by="services.admin_service.audit_entry_to_dict (viewer check)",
        warning="Off lets every Admin or sub-admin who can read the audit log see visitors' IP addresses.",
    ),
    FunctionSpec(
        "record_ips",
        "Record visitor IP addresses",
        G_PRIVACY,
        "Store the IP address with audit-log entries and ad clicks. Off: new entries keep no address at all.",
        True,
        enforced_by="utils.audit_logger.log_admin_action, api.routers.ads.track_click",
        warning="Off removes a trail you may need to investigate abuse. Rate limits still work (in memory only).",
    ),
    FunctionSpec(
        "scraper",
        "Scraping and importing",
        G_SCRAPING,
        "Importing series, re-scraping chapters, the Scraper AI and every scheduled scrape.",
        True,
        enforced_by="router dependency (scraper_admin, series import) and the scheduled tasks",
        warning="New chapters stop arriving while this is off.",
    ),
)

REGISTRY: dict[str, FunctionSpec] = {spec.key: spec for spec in _SPECS}
GROUPS: tuple[str, ...] = (G_ACCESS, G_READING, G_TRANSLATION, G_SITE, G_SCRAPING, G_PRIVACY)


def spec(key: str) -> FunctionSpec | None:
    return REGISTRY.get(key)


def is_valid(key: str) -> bool:
    return key in REGISTRY


def catalogue() -> list[dict]:
    return [
        {
            "key": s.key,
            "label": s.label,
            "group": s.group,
            "description": s.description,
            "default": s.default,
            "warning": s.warning,
        }
        for s in _SPECS
    ]
