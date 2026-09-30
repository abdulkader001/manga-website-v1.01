"""Application settings loaded from environment variables."""

from __future__ import annotations

import json
import logging
import os
import structlog
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..utils.crypto_utils import allow_plaintext_fallback, ensure_encrypted_env_loaded
from ..utils.email_crypto import split_email_keys

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATH = _PROJECT_ROOT / ".env"

logger = structlog.get_logger("backend_fastapi.settings")


def _truthy_env(name: str) -> bool:
    """True when the named env var is set to an affirmative value."""

    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalise_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    normalised = str(value).strip()
    return normalised or None


def _mask_secret(value: str | None, *, reveal: int = 6) -> str:
    if not value:
        return "<unset>"
    if len(value) <= reveal:
        return "*" * len(value)
    suffix = value[-2:] if len(value) - reveal >= 2 else ""
    return f"{value[:reveal]}…{suffix}" if suffix else f"{value[:reveal]}…"


class Settings(BaseSettings):
    """Settings backed by environment variables for the FastAPI service."""

    model_config = SettingsConfigDict(
        env_file=_ENV_PATH if allow_plaintext_fallback() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    # Runtime / infrastructure
    app_env: str | None = None
    app_host: str | None = None
    app_port: int | None = None
    port: int | None = None
    frontend_url: str | None = None
    service_name: str | None = None
    app_version: str | None = None
    allowed_origins: str | None = None
    cors_allowed_origins: list[str] | None = None
    backend_origin: str | None = None
    backend_url: str | None = None
    api_base_url: str | None = None
    startup_warnings: str | None = None
    require_google_project_id: bool | None = None

    # Secrets
    secret_key: str = Field(
        ...,
        min_length=12,
        description="Application signing secret used for session security.",
    )
    jwt_secret_key: str = Field(
        ...,
        min_length=12,
        description="Secret used for signing JWT access tokens.",
    )
    magic_link_secret: str | None = None
    integrations_secret: str | None = None
    secret_phrase: str | None = None
    expected_phrase: str | None = None
    secret_phrase_file: str | None = None
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"
    email_encryption_key: str | None = None

    # Main-admin identity (C5): the Argon2id hash of the main admin's email is
    # supplied via env and MUST NOT be committed to source. Auto-promotion on
    # login is disabled by default and should only be enabled transiently for
    # first-time bootstrap, then turned off again.
    main_admin_email_hash: str | None = None
    main_admin_auto_promote_enabled: bool = False
    # Roadmap item 15: main admins must enrol a second factor (TOTP) before
    # they can use admin routes. Off by default so nobody is locked out.
    admin_2fa_required: bool = False

    # Email
    email_backend: str | None = None
    email_from_address: str | None = None
    email_magic_link_subject: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    smtp_use_ssl: bool | None = None
    smtp_timeout: int | None = None

    # Database
    database_url: str | None = None
    postgres_host: str | None = None
    postgres_port: int | None = None
    postgres_user: str | None = None
    postgres_password: str | None = None
    postgres_db: str | None = None

    # Redis / Celery
    redis_username: str | None = None
    redis_password: str | None = None
    redis_url: str | None = None
    # Item 30: when True, an unconfigured/unreachable Redis fails startup instead
    # of silently degrading (recommended in multi-worker production).
    redis_required: bool = False
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_worker_concurrency: int | None = None
    monitor_redis_url: str | None = None
    monitor_queue_name: str | None = None
    monitor_queue_warn_threshold: int | None = None
    monitor_queue_alert_threshold: int | None = None

    # Authentication / OAuth
    magic_link_redirect_url: str | None = None
    google_project_id: str | None = None
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_redirect_uri: str | None = None
    google_oauth_hosted_domain: str | None = None
    microsoft_oauth_client_id: str | None = None
    microsoft_oauth_client_secret: str | None = None
    microsoft_oauth_tenant: str = "common"
    microsoft_oauth_redirect_uri: str | None = None

    # Third-party integrations
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    sentry_dsn: str | None = None
    sentry_environment: str | None = None
    release: str | None = None
    image_cdn_base_url: str | None = None

    # Miscellaneous feature flags / toggles retained for compatibility
    force_https_redirects: bool = True
    rate_limit_per_day: str | None = None
    rate_limit_per_hour: str | None = None
    generic_rate_limit_requests: int | None = None
    generic_rate_limit_window: int | None = None
    profile_upload_dir: str | None = None
    profile_image_max_bytes: int | None = None
    branding_upload_dir: str | None = None
    branding_asset_dir: str | None = None
    branding_logo_max_bytes: int | None = None
    rescrape_rate_limit_count: int | None = None
    rescrape_rate_limit_window: int | None = None
    ocr_enabled: bool = False
    translation_enabled: bool = False
    default_ocr_engine: str | None = None
    ocr_mode: str | None = None
    remote_ocr_url: str | None = None
    ocr_service_max_file_bytes: int | None = None
    ocr_service_tesseract_cmd: str | None = None
    ocr_service_default_psm: str | None = None
    ocr_service_timeout: int | None = None
    ocr_max_dim: int | None = None
    ocr_langs: str | None = None
    ocr_url_allowlist: str | None = None
    default_translation_provider: str | None = None
    translation_provider: str | None = None
    translation_api_url: str | None = None
    translation_api_key: str | None = None
    default_translation_api_url: str | None = None
    default_translation_api_key: str | None = None
    translation_default_target_language: str | None = None
    translation_max_text_length: int | None = None
    libretranslate_url: str | None = None
    libretranslate_api_key: str | None = None
    alembic_check_on_startup: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the settings as a dictionary."""

        return self.model_dump()

    @model_validator(mode="after")
    def _validate_security(self) -> "Settings":
        """Validate critical security-related configuration."""

        # F-13: a production deploy with any test-mode flag set (TESTING,
        # CELERY_TASK_ALWAYS_EAGER, ...) would silently return live tokens,
        # disable rate limits, or bypass the broker. Refuse to start loudly
        # rather than serve requests with test-mode behaviour active.
        from .test_mode import assert_test_flags_safe, is_production

        assert_test_flags_safe()

        # F-84: `force_https_redirects` is the single switch that also decides
        # whether the session, refresh and CSRF cookies carry `Secure` (see
        # api/routers/auth.py and utils/csrf_middleware.py). With it off in
        # production the refresh token -- a long-lived credential -- is sent
        # over plaintext HTTP and is trivially harvested by any network
        # attacker, and HSTS is suppressed so the browser never insists on
        # TLS. Nothing refused to start, and `.env.example` shipped the dev
        # value, so the documented setup path produced exactly that.
        # Terminating TLS at a proxy is NOT a reason to disable this: the
        # ForwardedHeadersMiddleware reads X-Forwarded-Proto, which is what
        # keeps the redirect from looping behind such a proxy.
        if is_production() and not self.force_https_redirects:
            if not _truthy_env("ALLOW_INSECURE_COOKIES"):
                raise ValueError(
                    "FORCE_HTTPS_REDIRECTS is false in a production "
                    "environment: session/refresh/CSRF cookies would be issued "
                    "without the Secure flag and HSTS would be suppressed. Set "
                    "FORCE_HTTPS_REDIRECTS=true (correct behind a "
                    "TLS-terminating proxy too), or set "
                    "ALLOW_INSECURE_COOKIES=true to accept plaintext "
                    "credential transport."
                )
            logger.warning(
                "FORCE_HTTPS_REDIRECTS is disabled in production and "
                "ALLOW_INSECURE_COOKIES is set: auth cookies are being issued "
                "WITHOUT the Secure flag."
            )

        # Roadmap item 5: ALLOW_PLAINTEXT_SECRETS lets a host run with
        # plaintext secrets and unencrypted emails. It is a local-dev escape
        # hatch, so a production process must never start with it set.
        if is_production() and _truthy_env("ALLOW_PLAINTEXT_SECRETS"):
            raise ValueError(
                "ALLOW_PLAINTEXT_SECRETS is set in a production environment. "
                "Unset it and configure encrypted secrets and "
                "EMAIL_ENCRYPTION_KEY instead."
            )

        secret_key = (self.secret_key or "").strip()
        if len(secret_key) < 12:
            raise ValueError("SECRET_KEY must be at least 12 characters long")
        self.secret_key = secret_key

        jwt_secret_key = (self.jwt_secret_key or "").strip()
        if len(jwt_secret_key) < 12:
            raise ValueError("JWT_SECRET_KEY must be at least 12 characters long")
        self.jwt_secret_key = jwt_secret_key

        if self.access_token_expire_minutes is None:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES not configured properly")
        if self.access_token_expire_minutes <= 0:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be greater than zero")

        algorithm = (self.algorithm or "").strip() or "HS256"
        self.algorithm = algorithm

        # Blind Spot #8: never silently store plaintext PII. Outside of explicit
        # plaintext-dev mode, the email-encryption key must be configured or we
        # fail startup loudly rather than persisting unencrypted emails.
        if (
            not allow_plaintext_fallback()
            and not (self.email_encryption_key or "").strip()
        ):
            raise ValueError(
                "EMAIL_ENCRYPTION_KEY must be set (or ALLOW_PLAINTEXT_SECRETS "
                "enabled for local dev) — refusing to store plaintext emails."
            )

        # Roadmap item 16: with several keys configured (a rotation in
        # progress), the lookup hashes must not depend on which key is first.
        # Require an explicit EMAIL_HASH_SECRET outside local dev.
        if (
            not allow_plaintext_fallback()
            and len(split_email_keys(self.email_encryption_key)) > 1
            and not (os.getenv("EMAIL_HASH_SECRET") or "").strip()
        ):
            raise ValueError(
                "EMAIL_ENCRYPTION_KEY holds several keys (key rotation) but "
                "EMAIL_HASH_SECRET is not set. Pin EMAIL_HASH_SECRET to the "
                "original key first, or every email lookup would stop matching."
            )

        # M5 / Blind Spot #10: enforce schema-drift checks by default in
        # staging/production so drift fails fast at boot. Explicit configuration
        # via ALEMBIC_CHECK_ON_STARTUP always wins.
        if "ALEMBIC_CHECK_ON_STARTUP" not in os.environ:
            env = (self.app_env or "").strip().lower()
            if env in {"staging", "stage", "production", "prod"}:
                self.alembic_check_on_startup = True

        # C5 / item 30: main-admin auto-promotion is a privileged bootstrap
        # path. If it is enabled but no MAIN_ADMIN_EMAIL_HASH is configured, the
        # promotion would silently never fire — an operator who set the flag
        # believing bootstrap is armed gets nothing, with no signal. Fail loud
        # rather than degrade silently: either configure the hash, or turn the
        # flag off.
        if (
            self.main_admin_auto_promote_enabled
            and not (self.main_admin_email_hash or "").strip()
        ):
            raise ValueError(
                "MAIN_ADMIN_AUTO_PROMOTE_ENABLED is set but MAIN_ADMIN_EMAIL_HASH "
                "is missing — auto-promotion would silently never fire. Configure "
                "MAIN_ADMIN_EMAIL_HASH (an Argon2id hash of the main admin's "
                "email), or disable MAIN_ADMIN_AUTO_PROMOTE_ENABLED."
            )

        return self

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_cors_origins(
        cls, value: Any
    ) -> list[str] | None:  # noqa: D401 - inherited
        """Normalise CORS origins from JSON strings, comma separated values or lists."""

        if value in (None, ""):
            return None
        if isinstance(value, list):
            return [str(origin).strip() for origin in value if str(origin).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return [
                    origin.strip() for origin in stripped.split(",") if origin.strip()
                ]
            if isinstance(parsed, list):
                return [str(origin).strip() for origin in parsed if str(origin).strip()]
            return [str(parsed).strip()]
        return [str(value).strip()]

    @field_validator("email_encryption_key")
    @classmethod
    def _validate_email_encryption_key(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return value

        # Key rotation: several comma-separated keys are allowed, newest first.
        from ..utils.email_crypto import split_email_keys

        keys = split_email_keys(value)
        if not keys:
            raise ValueError("EMAIL_ENCRYPTION_KEY must be 32 url-safe base64 bytes")
        for key_bytes in keys:
            try:
                Fernet(key_bytes)
            except Exception as exc:  # pragma: no cover - defensive branch
                raise ValueError(
                    "EMAIL_ENCRYPTION_KEY must be 32 url-safe base64 bytes "
                    "(several keys may be separated by commas)"
                ) from exc
        return value

    @field_validator(
        "secret_key",
        "jwt_secret_key",
        "magic_link_secret",
        "integrations_secret",
        "google_project_id",
        "google_oauth_client_id",
        "google_oauth_client_secret",
        "google_oauth_redirect_uri",
        "microsoft_oauth_client_id",
        "microsoft_oauth_client_secret",
        "microsoft_oauth_redirect_uri",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        return _normalise_string(value)

    @field_validator("require_google_project_id", mode="before")
    @classmethod
    def _parse_google_requirement(cls, value: Any) -> bool | None:
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return value
        normalised = str(value).strip().lower()
        if not normalised:
            return None
        return normalised in {"1", "true", "yes", "on"}

    @model_validator(mode="after")
    def _validate_google_settings(self) -> "Settings":
        """Validate Google OAuth configuration when enabled."""

        require_google_project_id = self.require_google_project_id
        if require_google_project_id is None:
            require_google_project_id = bool(
                self.google_oauth_client_id and self.google_oauth_client_secret
            )

        if require_google_project_id and not self.google_project_id:
            raise ValueError(
                "GOOGLE_PROJECT_ID must be configured when Google OAuth is enabled"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()


ensure_encrypted_env_loaded()
settings = get_settings()


if logging.getLogger("backend_fastapi.settings").isEnabledFor(logging.INFO):
    logger.info("Loaded APP_ENV=%s", settings.app_env or "<unset>")
    logger.info("Loaded GOOGLE_PROJECT_ID=%s", settings.google_project_id or "<unset>")
    logger.info(
        "Loaded GOOGLE_OAUTH_CLIENT_ID=%s",
        _mask_secret(settings.google_oauth_client_id),
    )
    logger.info(
        "Loaded GOOGLE_OAUTH_CLIENT_SECRET=%s",
        _mask_secret(settings.google_oauth_client_secret),
    )
    logger.info(
        "Loaded GOOGLE_OAUTH_REDIRECT_URI=%s",
        settings.google_oauth_redirect_uri or "<unset>",
    )
