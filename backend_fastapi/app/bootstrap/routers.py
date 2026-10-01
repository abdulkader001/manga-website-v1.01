"""Router composition for the FastAPI application."""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI

from ..api.routers import (
    account_router,
    reader_router,
    scraper_admin_router,
    secret_vault_router,
    seo_router,
    site_admin_router,
    ad_slots_router,
    ads_router,
    admin_router,
    admin_2fa_router,
    admin_login_router,
    auth_router,
    backup_router,
    bookmarks_router,
    branding_router,
    cache_admin_router,
    comments_router,
    community_router,
    config_router,
    glossary_router,
    health_router,
    history_router,
    integrations_router,
    legacy_router,
    management_router,
    manga_router,
    system_stats_router,
    notifications_router,
    ocr_router,
    processing_router,
    provider_management_router,
    system_state_router,
    tasks_router,
    translation_router,
    user_settings_router,
)

from ..dependencies.site_access import require_site_access

# Reading routes follow the main admin's "sign-in required" switch; auth,
# config, health and admin routes never do.
_members_only = [Depends(require_site_access)]


def build_api_router() -> APIRouter:
    """Return a composed API router containing all feature routes."""

    api_router = APIRouter()
    # Before auth_router: its catch-all GET /auth/{provider} would shadow
    # /auth/microsoft, /auth/check-username, ...
    api_router.include_router(account_router)
    api_router.include_router(admin_router)
    api_router.include_router(admin_2fa_router)
    api_router.include_router(admin_login_router)
    api_router.include_router(ad_slots_router)
    api_router.include_router(ads_router)
    api_router.include_router(auth_router)
    api_router.include_router(backup_router)
    api_router.include_router(bookmarks_router, dependencies=_members_only)
    api_router.include_router(branding_router)
    api_router.include_router(cache_admin_router)
    api_router.include_router(history_router, dependencies=_members_only)
    api_router.include_router(config_router)
    api_router.include_router(integrations_router)
    api_router.include_router(health_router)
    api_router.include_router(system_stats_router)
    api_router.include_router(legacy_router, dependencies=_members_only)
    api_router.include_router(management_router)
    api_router.include_router(comments_router, dependencies=_members_only)
    api_router.include_router(community_router, dependencies=_members_only)
    api_router.include_router(manga_router, dependencies=_members_only)
    api_router.include_router(glossary_router, dependencies=_members_only)
    api_router.include_router(notifications_router)
    api_router.include_router(ocr_router)
    api_router.include_router(processing_router)
    api_router.include_router(provider_management_router)
    api_router.include_router(system_state_router)
    api_router.include_router(tasks_router)
    api_router.include_router(translation_router)
    api_router.include_router(user_settings_router)
    api_router.include_router(reader_router, dependencies=_members_only)
    api_router.include_router(site_admin_router)
    api_router.include_router(scraper_admin_router)
    api_router.include_router(secret_vault_router)
    return api_router


def register_api_routes(app: FastAPI) -> None:
    """Mount the API router under the versioned and compatibility prefixes.

    SRS 1B.4.1 requires all endpoints to live under ``/api/v1/``. We adopt the
    standard expand-and-contract migration: ``/api/v1`` is the canonical,
    documented surface (``include_in_schema=True``), while the historical ``/``
    and ``/api`` mounts remain as deprecated, undocumented aliases through the
    deprecation window so existing clients keep working. New clients target
    ``/api/v1``.
    """

    api_router = build_api_router()

    # Canonical versioned surface (documented in OpenAPI).
    app.include_router(api_router, prefix="/api/v1")

    # sitemap.xml / rss.xml live at the site root, outside the API prefix.
    app.include_router(seo_router, dependencies=_members_only)

    # Deprecated compatibility aliases (hidden from the schema).
    app.include_router(api_router, include_in_schema=False)
    app.include_router(api_router, prefix="/api", include_in_schema=False)
