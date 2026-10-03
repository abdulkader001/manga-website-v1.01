"""Application routers."""

from .account import router as account_router
from .admin import router as admin_router
from .admin_2fa import router as admin_2fa_router
from .support import router as support_router
from .ad_slots import router as ad_slots_router
from .ads import router as ads_router
from .auth import router as auth_router
from .backup import router as backup_router
from .backups_admin import router as backups_admin_router
from .error_reports import public_router as error_reports_public_router
from .error_reports import router as error_reports_router
from .geolock_admin import public_router as geo_public_router
from .geolock_admin import router as geolock_admin_router
from .roles_succession import router as roles_succession_router
from .site_functions import router as site_functions_router
from .roles_tabs import router as roles_tabs_router
from .roles_admins import router as roles_admins_router
from .bookmarks import router as bookmarks_router
from .branding import router as branding_router
from .cache_admin import router as cache_admin_router
from .comments import router as comments_router
from .community import router as community_router
from .config import router as config_router
from .glossary import router as glossary_router
from .health import router as health_router
from .history import router as history_router
from .integrations import router as integrations_router
from .management import router as management_router
from .manga import router as manga_router
from .system_stats import router as system_stats_router
from .notifications import router as notifications_router
from .ocr import router as ocr_router
from .processing import router as processing_router
from .reader import router as reader_router
from .scraper_admin import router as scraper_admin_router
from .secret_vault import router as secret_vault_router
from .seo import router as seo_router
from .site_admin import router as site_admin_router
from .provider_management import router as provider_management_router
from .system_state import router as system_state_router
from .tasks import router as tasks_router
from .translation import router as translation_router
from .user_settings import router as user_settings_router

__all__ = [
    "account_router",
    "reader_router",
    "scraper_admin_router",
    "secret_vault_router",
    "seo_router",
    "site_admin_router",
    "admin_router",
    "admin_2fa_router",
    "site_functions_router",
    "roles_tabs_router",
    "support_router",
    "ad_slots_router",
    "ads_router",
    "auth_router",
    "backup_router",
    "backups_admin_router",
    "error_reports_public_router",
    "error_reports_router",
    "geo_public_router",
    "geolock_admin_router",
    "roles_succession_router",
    "roles_admins_router",
    "bookmarks_router",
    "branding_router",
    "cache_admin_router",
    "config_router",
    "comments_router",
    "community_router",
    "glossary_router",
    "health_router",
    "history_router",
    "integrations_router",
    "management_router",
    "manga_router",
    "system_stats_router",
    "notifications_router",
    "ocr_router",
    "processing_router",
    "provider_management_router",
    "system_state_router",
    "tasks_router",
    "translation_router",
    "user_settings_router",
]
