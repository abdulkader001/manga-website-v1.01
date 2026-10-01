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

import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import structlog
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import vault_preload
from ..models import VaultSecret
from ..vault_keys import DOMAIN_DERIVED_KEYS, MANAGED_KEYS, SPECS, SecretSpec, with_domain
from .integration_key_vault import IntegrationKeyVault

logger = structlog.get_logger(__name__)

REFRESH_INTERVAL_SECONDS = 30
MAX_VALUE_LENGTH = 4096


# The allow-list lives in a dependency-free module so the startup loader
# (``vault_preload``) can use it before the rest of the app is imported.
_SPECS = SPECS

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
        upper = 65535 if key.endswith("_PORT") else 1_000_000_000
        if not value.isdigit() or not 0 < int(value) <= upper:
            raise VaultError(f"Value must be a whole number between 1 and {upper}.")
        return str(int(value))
    if spec.kind == "number":
        try:
            number = float(value)
        except ValueError:
            raise VaultError("Value must be a number.") from None
        if not 0 <= number <= 1e12:
            raise VaultError("Value must be between 0 and 1000000000000.")
        return str(int(number)) if number.is_integer() else str(number)
    if spec.kind == "bool":
        lowered = value.lower()
        if lowered in _TRUE:
            return "true"
        if lowered in _FALSE:
            return "false"
        raise VaultError("Value must be true or false.")
    if spec.kind == "domain":
        return normalize_domain(value)
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


_HOSTNAME = re.compile(
    r"^(?=.{4,253}$)(?!-)([a-z0-9-]{1,63}(?<!-)\.)+[a-z]{2,63}$"
)


def normalize_domain(raw: str) -> str:
    """A bare lower-case hostname ("example.com") from whatever was typed.

    Accepts a pasted address (https://Example.com/path) and strips scheme,
    path and port; refuses IPs, single-label names and anything that is not a
    plain public hostname, so a typo cannot point the whole site somewhere odd.
    """

    text = (raw or "").strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    text = text.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    text = text.rsplit("@", 1)[-1].split(":", 1)[0].strip(".")
    if not _HOSTNAME.match(text) or re.match(r"^\d+(\.\d+){3}$", text):
        raise VaultError("Enter a domain name such as example.com (no IP address, port or path).")
    if text.endswith((".local", ".localhost", ".internal", ".test", ".invalid", ".example")):
        raise VaultError("That is not a public domain name.")
    return text


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
# What .env provided for a key before the vault first overrode it. Values the
# startup loader already applied are taken over from it, so removing them
# later still restores the real .env value.
_boot_env: Dict[str, Optional[str]] = dict(vault_preload.ORIGINALS)
_boot_settings: Dict[str, Any] = {}
_applied: Dict[str, str] = dict(vault_preload.APPLIED)
_fingerprint: Optional[tuple] = None
_last_check = 0.0


def _settings_obj():
    from ..core.settings import get_settings

    return get_settings()


def _coerce(annotation, value: str):
    """Typed value for a Settings field; JSON text becomes a list when the field is one."""

    text = value.strip()
    if text.startswith("["):
        try:
            return TypeAdapter(annotation).validate_python(json.loads(text))
        except (ValueError, ValidationError):
            pass
    try:
        return TypeAdapter(annotation).validate_python(value)
    except ValidationError:
        if "list" in str(annotation).lower():
            return TypeAdapter(annotation).validate_python(
                [p.strip() for p in text.split(",") if p.strip()]
            )
        raise


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
            coerced = _coerce(field.annotation, value)
        except ValidationError:
            logger.warning("vault_value_type_mismatch", key=key)
            return
    setattr(settings, field_name, coerced)


def _restore_setting_from_env(settings, key: str, field, original: Optional[str]) -> None:
    if original is None:
        value = field.get_default(call_default_factory=True)
    else:
        try:
            value = _coerce(field.annotation, original)
        except ValidationError:
            return
    setattr(settings, key.lower(), value)


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
            field = type(settings).model_fields.get(key.lower())
            if field is not None:
                if key in _boot_settings:
                    setattr(settings, key.lower(), _boot_settings[key])
                else:
                    # Applied at startup, before Settings existed: rebuild the
                    # .env value (or the field default when .env had none).
                    _restore_setting_from_env(settings, key, field, original)
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
    return with_domain(values)  # SITE_DOMAIN fills in the site's addresses


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


def domain_status(db: Session) -> dict[str, Any]:
    """Current site domain and the addresses it produces (for the domain card)."""

    from ..vault_keys import derived_from_domain

    stored = current_value(db, "SITE_DOMAIN")
    env_url = env_value("FRONTEND_URL")
    return {
        "domain": stored,
        "source": "vault" if stored else ("env" if env_url else "unset"),
        "env_frontend_url": env_url,
        "effective_frontend_url": os.environ.get("FRONTEND_URL") or env_url,
        "derived": derived_from_domain(stored) if stored else {},
    }


def listing(db: Session) -> list[dict[str, Any]]:
    rows = {row.key: row for row in db.query(VaultSecret).all()}
    cipher = _cipher() if rows else None
    domain_set = "SITE_DOMAIN" in rows
    entries = []
    for spec in _SPECS:
        row = rows.get(spec.key)
        if row is not None:
            value = cipher.decrypt(row.value_encrypted)
            source = "vault"
        else:
            value = env_value(spec.key)
            source = "env" if value else "unset"
            if domain_set and spec.key in DOMAIN_DERIVED_KEYS:
                source = "domain"  # filled in from the website domain
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
    vault_preload.ORIGINALS.clear()
    vault_preload.APPLIED.clear()
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
