"""Which settings the Secret Vault may hold.

Deliberately dependency-free (stdlib only): ``vault_preload`` imports it before
any other application module runs.

Everything not listed here stays in ``.env`` -- by design, not omission:

* how to reach the database and Redis (``DATABASE_URL``, ``POSTGRES_*``,
  ``REDIS_URL``, ``CELERY_BROKER_URL`` ...) -- needed before the vault can be
  read at all;
* the site's own address and its security boundary (``FRONTEND_URL``,
  ``BACKEND_URL``, CORS origins, ``FORCE_HTTPS_REDIRECTS``,
  ``TRUSTED_PROXY_CIDRS``, ``HSTS_*``, ``EXPOSE_API_DOCS``);
* keys and admin identity (``INTEGRATIONS_SECRET`` -- the vault's own key --
  ``SECRET_KEY``, ``JWT_SECRET_KEY``, ``MAGIC_LINK_SECRET``,
  ``EMAIL_ENCRYPTION_KEY``, ``EMAIL_HASH_SECRET``, ``MAIN_ADMIN_EMAIL_HASH``,
  ``ADMIN_2FA_REQUIRED``, ``ADMIN_PROMOTION_*``);
* anything that is a program or file path the server executes or writes to
  (``OCR_SERVICE_TESSERACT_CMD``, upload/backup directories), so a database
  write can never become code execution;
* process/container plumbing (ports, Gunicorn/Celery worker counts, CA
  bundles, ``REACT_APP_*`` build-time values).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class SecretSpec:
    key: str
    group: str
    label: str
    secret: bool = False  # masked in listings; plaintext only via an explicit reveal
    kind: str = "text"  # text | url | int | bool | email | number
    restart_required: bool = False  # read once at startup rather than per use
    help: str = ""


_G_GOOGLE = "Google sign-in"
_G_MS = "Microsoft sign-in"
_G_EMAIL = "Email & magic links"
_G_TR = "Translation & OCR"
_G_3P = "Third-party services"
_G_MON = "Error monitoring"
_G_LIMITS = "Limits & performance"
_G_IMG = "Images, uploads & storage"
_G_SEC = "Sign-in sessions & scanning"

SPECS = (
    # Google sign-in
    SecretSpec("GOOGLE_OAUTH_CLIENT_ID", _G_GOOGLE, "Client ID"),
    SecretSpec("GOOGLE_OAUTH_CLIENT_SECRET", _G_GOOGLE, "Client secret", secret=True),
    SecretSpec("GOOGLE_OAUTH_REDIRECT_URI", _G_GOOGLE, "Redirect URI", kind="url"),
    SecretSpec(
        "GOOGLE_OAUTH_HOSTED_DOMAIN",
        _G_GOOGLE,
        "Hosted domain",
        help="Restrict Google sign-in to one Workspace domain. Leave unset for any account.",
    ),
    SecretSpec("GOOGLE_PROJECT_ID", _G_GOOGLE, "Project ID"),
    # Microsoft sign-in
    SecretSpec("MICROSOFT_OAUTH_CLIENT_ID", _G_MS, "Client ID"),
    SecretSpec("MICROSOFT_OAUTH_CLIENT_SECRET", _G_MS, "Client secret", secret=True),
    SecretSpec("MICROSOFT_OAUTH_REDIRECT_URI", _G_MS, "Redirect URI", kind="url"),
    SecretSpec(
        "MICROSOFT_OAUTH_TENANT",
        _G_MS,
        "Tenant",
        help="'common', 'organizations', 'consumers' or a tenant ID.",
    ),
    # Email & magic links
    SecretSpec("EMAIL_BACKEND", _G_EMAIL, "Email backend", help="'smtp' or 'console'."),
    SecretSpec("EMAIL_FROM_ADDRESS", _G_EMAIL, "From address", kind="email"),
    SecretSpec("EMAIL_MAGIC_LINK_SUBJECT", _G_EMAIL, "Magic-link subject"),
    SecretSpec("MAGIC_LINK_REDIRECT_URL", _G_EMAIL, "Magic-link redirect URL", kind="url"),
    SecretSpec("SMTP_HOST", _G_EMAIL, "SMTP host"),
    SecretSpec("SMTP_PORT", _G_EMAIL, "SMTP port", kind="int"),
    SecretSpec("SMTP_USERNAME", _G_EMAIL, "SMTP username"),
    SecretSpec("SMTP_PASSWORD", _G_EMAIL, "SMTP password", secret=True),
    SecretSpec("SMTP_USE_TLS", _G_EMAIL, "Use STARTTLS", kind="bool"),
    SecretSpec("SMTP_USE_SSL", _G_EMAIL, "Use SSL", kind="bool"),
    SecretSpec("SMTP_TIMEOUT", _G_EMAIL, "SMTP timeout (s)", kind="int"),
    SecretSpec("SMTP_FROM_ADDRESS", _G_EMAIL, "SMTP from address", kind="email"),
    SecretSpec(
        "DISPOSABLE_EMAIL_DOMAINS",
        _G_EMAIL,
        "Extra blocked email domains",
        help="Comma-separated, added to the built-in disposable-email list.",
    ),
    # Translation & OCR
    SecretSpec(
        "OCR_ENABLED",
        _G_TR,
        "Server OCR enabled",
        kind="bool",
        restart_required=True,
        help="Turns on the built-in Tesseract engine for readers without their own OCR API.",
    ),
    SecretSpec("TRANSLATION_ENABLED", _G_TR, "Server translation enabled", kind="bool", restart_required=True),
    SecretSpec(
        "OCR_MODE", _G_TR, "OCR mode", restart_required=True, help="'local' (built-in Tesseract) or 'remote'."
    ),
    SecretSpec("DEFAULT_OCR_ENGINE", _G_TR, "Default OCR engine", restart_required=True),
    SecretSpec(
        "OCR_LANGS",
        _G_TR,
        "OCR languages (legacy tools)",
        restart_required=True,
        help="Tesseract languages for the standalone OCR tools, e.g. kor+jpn+chi_sim+eng. "
        "The reader picks per series automatically.",
    ),
    SecretSpec("OCR_MAX_DIM", _G_TR, "OCR max image size (px)", kind="int", restart_required=True),
    SecretSpec("OCR_SHRINK_IMAGES", _G_TR, "Shrink large images before OCR", kind="bool", restart_required=True),
    SecretSpec("OCR_SERVICE_TIMEOUT", _G_TR, "OCR timeout (s)", kind="int", restart_required=True),
    SecretSpec("OCR_SERVICE_DEFAULT_PSM", _G_TR, "Tesseract page mode (PSM)", kind="int", restart_required=True),
    SecretSpec(
        "OCR_SERVICE_MAX_FILE_BYTES", _G_TR, "OCR max upload (bytes)", kind="number", restart_required=True
    ),
    SecretSpec("REMOTE_OCR_URL", _G_TR, "Remote OCR URL", kind="url", restart_required=True),
    SecretSpec(
        "OCR_URL_ALLOWLIST",
        _G_TR,
        "OCR image host allow-list",
        help="Comma-separated hosts the OCR tools may fetch images from.",
    ),
    SecretSpec("TRANSLATION_PROVIDER", _G_TR, "Translation provider"),
    SecretSpec("DEFAULT_TRANSLATION_PROVIDER", _G_TR, "Fallback translation provider"),
    SecretSpec("TRANSLATION_API_URL", _G_TR, "Translation API URL", kind="url"),
    SecretSpec("TRANSLATION_API_KEY", _G_TR, "Translation API key", secret=True),
    SecretSpec("LIBRETRANSLATE_URL", _G_TR, "LibreTranslate URL", kind="url"),
    SecretSpec("LIBRETRANSLATE_API_KEY", _G_TR, "LibreTranslate API key", secret=True),
    SecretSpec("DEFAULT_TRANSLATION_API_URL", _G_TR, "Fallback translation URL", kind="url"),
    SecretSpec("DEFAULT_TRANSLATION_API_KEY", _G_TR, "Fallback translation key", secret=True),
    SecretSpec(
        "TRANSLATION_DEFAULT_TARGET_LANGUAGE", _G_TR, "Default target language", restart_required=True
    ),
    SecretSpec(
        "TRANSLATION_MAX_TEXT_LENGTH", _G_TR, "Max text per translation", kind="int", restart_required=True
    ),
    SecretSpec(
        "TRANSLATION_MAX_CONCURRENCY", _G_TR, "Parallel translation calls", kind="int", restart_required=True
    ),
    # Third-party services
    SecretSpec("TENOR_API_KEY", _G_3P, "Tenor API key", secret=True),
    SecretSpec("GIF_PROVIDER_API_KEY", _G_3P, "GIF provider API key", secret=True),
    SecretSpec("IMAGE_CDN_BASE_URL", _G_3P, "Image CDN base URL", kind="url"),
    # Error monitoring
    SecretSpec("SENTRY_DSN", _G_MON, "Sentry DSN", secret=True, kind="url", restart_required=True),
    SecretSpec("SENTRY_ENVIRONMENT", _G_MON, "Sentry environment", restart_required=True),
    SecretSpec("ENABLE_SENTRY", _G_MON, "Enable Sentry", kind="bool", restart_required=True),
    # Limits & performance
    SecretSpec(
        "GENERIC_RATE_LIMIT_REQUESTS", _G_LIMITS, "API requests per window (per visitor)", kind="int",
        restart_required=True,
    ),
    SecretSpec("GENERIC_RATE_LIMIT_WINDOW", _G_LIMITS, "Rate-limit window (s)", kind="int", restart_required=True),
    SecretSpec(
        "RATE_LIMIT_MAX_BLOCK_SECONDS", _G_LIMITS, "Longest block for repeat offenders (s)", kind="int",
        restart_required=True,
    ),
    SecretSpec(
        "RATE_LIMIT_STRIKE_DECAY_SECONDS", _G_LIMITS, "Forget offences after (s)", kind="int",
        restart_required=True,
    ),
    SecretSpec("RESCRAPE_RATE_LIMIT_COUNT", _G_LIMITS, "Re-scrapes allowed per window", kind="int"),
    SecretSpec("RESCRAPE_RATE_LIMIT_WINDOW", _G_LIMITS, "Re-scrape window (s)", kind="int"),
    SecretSpec("REQUEST_TIMEOUT_SECONDS", _G_LIMITS, "Request timeout (s)", kind="number", restart_required=True),
    SecretSpec(
        "LONG_REQUEST_TIMEOUT_SECONDS", _G_LIMITS, "Long request timeout (s)", kind="number",
        restart_required=True,
    ),
    SecretSpec("FASTAPI_MAX_CONCURRENCY", _G_LIMITS, "Max parallel requests", kind="int", restart_required=True),
    SecretSpec(
        "SSRF_FETCH_MAX_BYTES", _G_LIMITS, "Max size of fetched pages (bytes)", kind="number",
        restart_required=True,
    ),
    # Images, uploads & storage
    SecretSpec("PAGE_MAX_WIDTH", _G_IMG, "Stored page width (px)", kind="int"),
    SecretSpec("MIRROR_PAGE_IMAGES", _G_IMG, "Store chapter pictures on this server", kind="bool"),
    SecretSpec("STORAGE_ALERT_PERCENT", _G_IMG, "Disk-full warning at (%)", kind="number"),
    SecretSpec("STORAGE_ALERT_BYTES", _G_IMG, "Storage warning above (bytes)", kind="number"),
    SecretSpec("PROFILE_IMAGE_MAX_BYTES", _G_IMG, "Max avatar upload (bytes)", kind="number"),
    SecretSpec("BRANDING_LOGO_MAX_BYTES", _G_IMG, "Max logo upload (bytes)", kind="number"),
    # Sessions & scanning
    SecretSpec(
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        _G_SEC,
        "Login token lifetime (min)",
        kind="int",
        help="How long a login token lasts before it is silently refreshed.",
    ),
    SecretSpec("CLAMAV_HOST", _G_SEC, "ClamAV host", help="Virus scanning of uploads. Leave unset to disable."),
    SecretSpec("CLAMAV_PORT", _G_SEC, "ClamAV port", kind="int"),
)

MANAGED_KEYS: Dict[str, SecretSpec] = {spec.key: spec for spec in SPECS}

__all__ = ["MANAGED_KEYS", "SPECS", "SecretSpec"]
