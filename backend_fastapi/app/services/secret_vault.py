"""Secret vault: main-admin-managed overrides for allow-listed env variables.

Most integration settings (OAuth apps, SMTP, API keys) used to live only in
``.env``. The vault lets the main admin set them from the admin panel instead:

* Only keys in :data:`MANAGED_KEYS` can be stored. Bootstrap settings the app
  needs before it can reach the database or decrypt anything (``DATABASE_URL``,
  ``REDIS_URL``, ``SECRET_KEY``, ``INTEGRATIONS_SECRET``,
  ``MAIN_ADMIN_EMAIL_HASH``, ...) are deliberately absent and stay in ``.env``.
* Values are Fernet-encrypted under ``INTEGRATIONS_SECRET`` (the same key, and
  the same ``INTEGRATIONS_SECRET_PREVIOUS`` rotation path, as provider
  credentials).
* A stored value wins over ``.env``. It is applied to both ``os.environ`` and
  the ``settings`` singleton, because call sites read either one; no call site
  needs to know the vault exists. Removing the value restores what ``.env``
  had at boot.
* Each process (API worker or Celery worker) re-reads the table when its
  fingerprint changes, checked at most every :data:`REFRESH_INTERVAL_SECONDS`.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import structlog
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import VaultSecret
from .integration_key_vault import IntegrationKeyVault

logger = structlog.get_logger(__name__)

REFRESH_INTERVAL_SECONDS = 30
MAX_VALUE_LENGTH = 4096


@dataclass(frozen=True)
class SecretSpec:
    key: str
    group: str
    label: str
    secret: bool = False  # masked in listings; plaintext only via an explicit reveal
    kind: str = "text"  # text | url | int | bool | email
    restart_required: bool = False  # read once at startup rather than per use
    help: str = ""


_SPECS = (
    # Google sign-in
    SecretSpec("GOOGLE_OAUTH_CLIENT_ID", "Google sign-in", "Client ID"),
    SecretSpec("GOOGLE_OAUTH_CLIENT_SECRET", "Google sign-in", "Client secret", secret=True),
    SecretSpec("GOOGLE_OAUTH_REDIRECT_URI", "Google sign-in", "Redirect URI", kind="url"),
    SecretSpec(
        "GOOGLE_OAUTH_HOSTED_DOMAIN",
        "Google sign-in",
        "Hosted domain",
        help="Restrict Google sign-in to one Workspace domain. Leave unset for any account.",
    ),
    SecretSpec("GOOGLE_PROJECT_ID", "Google sign-in", "Project ID"),
    # Microsoft sign-in
    SecretSpec("MICROSOFT_OAUTH_CLIENT_ID", "Microsoft sign-in", "Client ID"),
    SecretSpec(
        "MICROSOFT_OAUTH_CLIENT_SECRET", "Microsoft sign-in", "Client secret", secret=True
    ),
    SecretSpec("MICROSOFT_OAUTH_REDIRECT_URI", "Microsoft sign-in", "Redirect URI", kind="url"),
    SecretSpec(
        "MICROSOFT_OAUTH_TENANT",
        "Microsoft sign-in",
        "Tenant",
        help="'common', 'organizations', 'consumers' or a tenant ID.",
    ),
    # Email & magic links
    SecretSpec(
        "EMAIL_BACKEND", "Email & magic links", "Email backend", help="'smtp' or 'console'."
    ),
    SecretSpec("EMAIL_FROM_ADDRESS", "Email & magic links", "From address", kind="email"),
    SecretSpec("EMAIL_MAGIC_LINK_SUBJECT", "Email & magic links", "Magic-link subject"),
    SecretSpec(
        "MAGIC_LINK_REDIRECT_URL", "Email & magic links", "Magic-link redirect URL", kind="url"
    ),
    SecretSpec("SMTP_HOST", "Email & magic links", "SMTP host"),
    SecretSpec("SMTP_PORT", "Email & magic links", "SMTP port", kind="int"),
    SecretSpec("SMTP_USERNAME", "Email & magic links", "SMTP username"),
    SecretSpec("SMTP_PASSWORD", "Email & magic links", "SMTP password", secret=True),
    SecretSpec("SMTP_USE_TLS", "Email & magic links", "Use STARTTLS", kind="bool"),
    SecretSpec("SMTP_USE_SSL", "Email & magic links", "Use SSL", kind="bool"),
    SecretSpec("SMTP_TIMEOUT", "Email & magic links", "SMTP timeout (s)", kind="int"),
    SecretSpec("SMTP_FROM_ADDRESS", "Email & magic links", "SMTP from address", kind="email"),
    # Translation & OCR
    SecretSpec("TRANSLATION_API_URL", "Translation & OCR", "Translation API URL", kind="url"),
    SecretSpec("TRANSLATION_API_KEY", "Translation & OCR", "Translation API key", secret=True),
    SecretSpec("LIBRETRANSLATE_URL", "Translation & OCR", "LibreTranslate URL", kind="url"),
    SecretSpec(
        "LIBRETRANSLATE_API_KEY", "Translation & OCR", "LibreTranslate API key", secret=True
    ),
    SecretSpec(
        "DEFAULT_TRANSLATION_API_URL", "Translation & OCR", "Fallback translation URL", kind="url"
    ),
    SecretSpec(
        "DEFAULT_TRANSLATION_API_KEY",
        "Translation & OCR",
        "Fallback translation key",
        secret=True,
    ),
    SecretSpec(
        "REMOTE_OCR_URL", "Translation & OCR", "Remote OCR URL", kind="url", restart_required=True
    ),
    # Third-party services
    SecretSpec("TENOR_API_KEY", "Third-party services", "Tenor API key", secret=True),
    SecretSpec("GIF_PROVIDER_API_KEY", "Third-party services", "GIF provider API key", secret=True),
    SecretSpec("IMAGE_CDN_BASE_URL", "Third-party services", "Image CDN base URL", kind="url"),
    # Error monitoring
    SecretSpec(
        "SENTRY_DSN", "Error monitoring", "Sentry DSN", secret=True, kind="url", restart_required=True
    ),
    SecretSpec(
        "SENTRY_ENVIRONMENT", "Error monitoring", "Sentry environment", restart_required=True
    ),
    SecretSpec(
        "ENABLE_SENTRY", "Error monitoring", "Enable Sentry", kind="bool", restart_required=True
    ),
)

MANAGED_KEYS: Dict[str, SecretSpec] = {spec.key: spec for spec in _SPECS}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class VaultError(ValueError):
    """Raised for a value the vault refuses to store."""


class VaultUnavailable(RuntimeError):
    """Raised when ``INTEGRATIONS_SECRET`` is missing, so nothing can be encrypted."""


def _cipher() -> IntegrationKeyVault:
    vault = IntegrationKeyVault.from_env()
    if vault is None:
        raise VaultUnavailable("INTEGRATIONS_SECRET is not set; the vault cannot encrypt values.")
    return vault


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def normalize_value(key: str, raw: Any) -> str:
    """Return the canonical string to store for ``key``, or raise ``VaultError``."""

    spec = MANAGED_KEYS.get(key)
    if spec is None:
        raise VaultError(f"{key} cannot be managed from the admin panel.")
    if not isinstance(raw, str):
        raise VaultError("Value must be a string.")
    value = raw.strip()
    if not value:
        raise VaultError("Value is empty. Use Remove to fall back to .env instead.")
    if len(value) > MAX_VALUE_LENGTH:
        raise VaultError(f"Value is longer than {MAX_VALUE_LENGTH} characters.")
    # Values end up in os.environ and in outbound headers; control characters
    # (newlines in particular) are never legitimate here.
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise VaultError("Value contains control characters or line breaks.")

    if spec.kind == "int":
        if not value.isdigit() or not 0 < int(value) <= 65535:
            raise VaultError("Value must be a whole number between 1 and 65535.")
        return str(int(value))
    if spec.kind == "bool":
        lowered = value.lower()
        if lowered in _TRUE:
            return "true"
        if lowered in _FALSE:
            return "false"
        raise VaultError("Value must be true or false.")
    if spec.kind == "url":
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise VaultError("Value must be a full http(s):// URL.")
    if spec.kind == "email":
        # Allow "Name <addr@host>" as well as a bare address.
        address = value.rsplit("<", 1)[-1].rstrip(">").strip()
        local, _, domain = address.partition("@")
        if not local or "." not in domain:
            raise VaultError("Value must be an email address.")
    return value


def mask(value: Optional[str], *, secret: bool) -> Optional[str]:
    if value is None:
        return None
    if not secret:
        return value
    if len(value) <= 8:
        return "•" * 8
    return "•" * 8 + value[-4:]


# ---------------------------------------------------------------------------
# Applying overrides to the running process
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_UNSET = object()
# What .env provided for a key before the vault first overrode it.
_boot_env: Dict[str, Optional[str]] = {}
_boot_settings: Dict[str, Any] = {}
_applied: Dict[str, str] = {}
_fingerprint: Optional[tuple] = None
_last_check = 0.0


def _settings_obj():
    from ..core.settings import get_settings

    return get_settings()


def _set_setting(key: str, value: Optional[str]) -> None:
    settings = _settings_obj()
    field_name = key.lower()
    field = type(settings).model_fields.get(field_name)
    if field is None:
        return
    if key not in _boot_settings:
        _boot_settings[key] = getattr(settings, field_name, None)
    if value is None:
        coerced = None
    else:
        try:
            coerced = TypeAdapter(field.annotation).validate_python(value)
        except ValidationError:
            logger.warning("vault_value_type_mismatch", key=key)
            return
    setattr(settings, field_name, coerced)


def _apply(values: Dict[str, str]) -> None:
    """Make ``values`` the live overrides, restoring .env for keys dropped since last time."""

    with _lock:
        for key in list(_applied):
            if key in values:
                continue
            original = _boot_env.get(key)
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
            settings = _settings_obj()
            if key in _boot_settings and key.lower() in type(settings).model_fields:
                setattr(settings, key.lower(), _boot_settings[key])
            del _applied[key]

        for key, value in values.items():
            if key not in MANAGED_KEYS or _applied.get(key) == value:
                continue
            if key not in _boot_env:
                _boot_env[key] = os.environ.get(key)
            os.environ[key] = value
            _set_setting(key, value)
            _applied[key] = value


def env_value(key: str) -> Optional[str]:
    """The value ``.env`` supplies for ``key``, ignoring any vault override."""

    with _lock:
        if key in _applied:
            value = _boot_env.get(key)
            fallback = _boot_settings.get(key)
        else:
            value = os.environ.get(key)
            fallback = getattr(_settings_obj(), key.lower(), None)
    if value:
        return value
    # pydantic may have read the key from the .env file without exporting it.
    if fallback is None or fallback == "" or isinstance(fallback, (dict, list)):
        return None
    if isinstance(fallback, bool):
        return "true" if fallback else "false"
    return str(fallback)


def is_overridden(key: str) -> bool:
    with _lock:
        return key in _applied


def _read_fingerprint(db: Session) -> tuple:
    count, latest = db.query(func.count(VaultSecret.id), func.max(VaultSecret.updated_at)).one()
    return (int(count or 0), latest)


def load_values(db: Session) -> Dict[str, str]:
    cipher = _cipher()
    values: Dict[str, str] = {}
    for row in db.query(VaultSecret).all():
        if row.key not in MANAGED_KEYS:
            continue
        plaintext = cipher.decrypt(row.value_encrypted)
        if plaintext is None:
            logger.error("vault_secret_undecryptable", key=row.key)
            continue
        values[row.key] = plaintext
    return values


def refresh(db: Session, *, force: bool = False) -> None:
    """Re-apply the stored overrides when the table changed (or ``force``)."""

    global _fingerprint, _last_check
    fingerprint = _read_fingerprint(db)
    _last_check = time.monotonic()
    if not force and fingerprint == _fingerprint:
        return
    if fingerprint[0] == 0 and not _applied:
        _fingerprint = fingerprint
        return
    try:
        values = load_values(db)
    except VaultUnavailable:
        logger.error("vault_unavailable_on_refresh")
        return
    _apply(values)
    _fingerprint = fingerprint
    logger.info("vault_overrides_applied", keys=sorted(values))


def refresh_if_stale(session_factory=None) -> None:
    """Cheap periodic check; safe to call from a request path or a worker hook."""

    if time.monotonic() - _last_check < REFRESH_INTERVAL_SECONDS:
        return
    if session_factory is None:
        from ..core.db import SessionLocal

        session_factory = SessionLocal
    db = session_factory()
    try:
        refresh(db)
    except Exception as exc:  # the vault must never take a request down
        logger.warning("vault_refresh_failed", error=type(exc).__name__)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def store(db: Session, key: str, raw_value: Any, *, actor_id: Optional[int]) -> str:
    value = normalize_value(key, raw_value)
    token = _cipher().encrypt(value)
    # Explicit microsecond timestamp: other processes notice a change through
    # max(updated_at), so two edits in the same second must still differ.
    now = datetime.utcnow()
    row = db.query(VaultSecret).filter(VaultSecret.key == key).one_or_none()
    if row is None:
        db.add(
            VaultSecret(key=key, value_encrypted=token, updated_by_id=actor_id, updated_at=now)
        )
    else:
        row.value_encrypted = token
        row.updated_by_id = actor_id
        row.updated_at = now
    db.commit()
    refresh(db, force=True)
    return value


def remove(db: Session, key: str) -> bool:
    if key not in MANAGED_KEYS:
        raise VaultError(f"{key} cannot be managed from the admin panel.")
    deleted = db.query(VaultSecret).filter(VaultSecret.key == key).delete()
    db.commit()
    refresh(db, force=True)
    return bool(deleted)


def current_value(db: Session, key: str) -> Optional[str]:
    """The effective plaintext value for ``key`` (vault first, then .env)."""

    row = db.query(VaultSecret).filter(VaultSecret.key == key).one_or_none()
    if row is not None:
        return _cipher().decrypt(row.value_encrypted)
    return env_value(key)


def listing(db: Session) -> list[dict[str, Any]]:
    rows = {row.key: row for row in db.query(VaultSecret).all()}
    cipher = _cipher() if rows else None
    entries = []
    for spec in _SPECS:
        row = rows.get(spec.key)
        if row is not None:
            value = cipher.decrypt(row.value_encrypted)
            source = "vault"
        else:
            value = env_value(spec.key)
            source = "env" if value else "unset"
        entries.append(
            {
                "key": spec.key,
                "group": spec.group,
                "label": spec.label,
                "kind": spec.kind,
                "secret": spec.secret,
                "restart_required": spec.restart_required,
                "help": spec.help,
                "source": source,
                "preview": mask(value, secret=spec.secret),
                "has_env_fallback": bool(env_value(spec.key)),
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
            }
        )
    return entries


def _reset_for_tests() -> None:
    """Drop all overrides and cached state (test helper)."""

    global _fingerprint, _last_check
    _apply({})
    _boot_env.clear()
    _boot_settings.clear()
    _fingerprint = None
    _last_check = 0.0


__all__ = [
    "MANAGED_KEYS",
    "SecretSpec",
    "VaultError",
    "VaultUnavailable",
    "current_value",
    "env_value",
    "listing",
    "load_values",
    "mask",
    "normalize_value",
    "refresh",
    "refresh_if_stale",
    "remove",
    "store",
]
