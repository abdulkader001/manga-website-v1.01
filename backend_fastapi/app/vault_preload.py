"""Load Secret Vault values into the process environment at startup.

Runs from ``backend_fastapi/app/__init__.py``, i.e. before any other
application module is imported -- so settings that modules read once at import
time (``OCR_MODE = os.getenv(...)``, the pydantic ``Settings`` object, Celery
config) see the vault value exactly as if it had been written in ``.env``.

Rules:

* Only keys in ``vault_keys.MANAGED_KEYS`` are ever written, so the database
  can never inject ``DATABASE_URL``, a signing key or a program path.
* Decryption uses ``INTEGRATIONS_SECRET`` (+ ``_PREVIOUS``), derived exactly as
  ``services.integration_key_vault.IntegrationKeyVault`` does.
* Best effort: no database URL, no key, no table yet (first migration), an
  unreachable database or an undecryptable row all just leave ``.env`` in
  charge. Nothing here may stop the process from starting.

Live edits made later are applied by ``services.secret_vault`` (every 30 s);
the original ``.env`` values are kept in :data:`ORIGINALS` so removing a vault
value can restore them.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import Dict, MutableMapping, Optional

from .vault_keys import MANAGED_KEYS

logger = logging.getLogger("backend_fastapi.vault_preload")

# key -> the value the environment had before the vault replaced it (None = unset)
ORIGINALS: Dict[str, Optional[str]] = {}
# key -> the vault value written at startup
APPLIED: Dict[str, str] = {}

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _from_env_file(name: str, env_file: Path) -> Optional[str]:
    try:
        from dotenv import dotenv_values

        return (dotenv_values(env_file) or {}).get(name) or None
    except Exception:
        return None


def _lookup(name: str, environ: MutableMapping[str, str], env_file: Path) -> Optional[str]:
    return environ.get(name) or _from_env_file(name, env_file)


def _fernet(secret: str, previous: list[str]):
    from cryptography.fernet import Fernet, MultiFernet

    def derive(value: str) -> Fernet:
        digest = hashlib.sha256(value.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))

    return MultiFernet([derive(secret), *(derive(p) for p in previous if p)])


def preload(
    environ: MutableMapping[str, str] = os.environ,
    *,
    env_file: Path = _ENV_FILE,
    database_url: Optional[str] = None,
) -> Dict[str, str]:
    """Copy decrypted vault values into ``environ``; returns what was applied."""

    db_url = database_url or _lookup("DATABASE_URL", environ, env_file)
    secret = _lookup("INTEGRATIONS_SECRET", environ, env_file)
    if not db_url or not secret:
        return {}
    previous = [
        p.strip()
        for p in (_lookup("INTEGRATIONS_SECRET_PREVIOUS", environ, env_file) or "").split(",")
        if p.strip()
    ]

    try:
        from cryptography.fernet import InvalidToken
        from sqlalchemy import create_engine, text
        from sqlalchemy.pool import NullPool

        connect_args = {"connect_timeout": 5} if db_url.startswith("postgresql") else {}
        engine = create_engine(db_url, poolclass=NullPool, connect_args=connect_args)
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("SELECT key, value_encrypted FROM vault_secrets")).all()
        finally:
            engine.dispose()
    except Exception as exc:  # no table yet, DB down, driver missing...
        logger.info("vault_preload_skipped: %s", type(exc).__name__)
        return {}

    cipher = _fernet(secret, previous)
    applied: Dict[str, str] = {}
    for key, token in rows:
        if key not in MANAGED_KEYS or not token:
            continue
        try:
            value = cipher.decrypt(str(token).encode("utf-8")).decode("utf-8")
        except InvalidToken:
            logger.warning("vault_preload_undecryptable key=%s", key)
            continue
        if key not in ORIGINALS:
            ORIGINALS[key] = environ.get(key)
        environ[key] = value
        APPLIED[key] = value
        applied[key] = value
    if applied:
        logger.info("vault_preload_applied keys=%s", ",".join(sorted(applied)))
    return applied


def preload_once() -> None:
    """Entry point used by the package ``__init__``; skipped under pytest so
    test runs never pick up a developer's local vault."""

    if getattr(preload_once, "_done", False):
        return
    preload_once._done = True  # type: ignore[attr-defined]
    if "pytest" in sys.modules or os.environ.get("VAULT_PRELOAD_DISABLED"):
        return
    try:
        preload()
    except Exception:  # pragma: no cover - must never block startup
        logger.exception("vault_preload_failed")


__all__ = ["APPLIED", "ORIGINALS", "preload", "preload_once"]
