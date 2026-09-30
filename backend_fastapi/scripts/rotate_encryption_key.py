#!/usr/bin/env python3
"""Re-encrypt stored secrets under the newest encryption keys (roadmap item 16).

Two keys are rotated:

- ``EMAIL_ENCRYPTION_KEY``: emails and OAuth tokens. Give it as
  ``NEW_KEY,OLD_KEY`` (comma separated, newest first).
- ``INTEGRATIONS_SECRET``: stored provider and user API keys. Put the old value
  in ``INTEGRATIONS_SECRET_PREVIOUS`` and the new one in ``INTEGRATIONS_SECRET``.

Every value is read with any known key and written back with the newest one, so
the script is idempotent and safe to stop and run again. Values that no known
key can read are left untouched and counted as ``unreadable``.

The steps are in ``deployment/key-rotation.md``.

Usage:
    python -m backend_fastapi.scripts.rotate_encryption_key [--dry-run] [--batch-size N]
"""

from __future__ import annotations

import argparse
import logging
import sys

from cryptography.fernet import InvalidToken
from sqlalchemy import text

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.services.integration_key_vault import IntegrationKeyVault
from backend_fastapi.app.utils.email_crypto import _load_email_cipher

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("rotate_encryption_key")

# (table, primary key, column, kind). "email" columns and OAuth tokens use the
# email key; "vault" columns use the integrations secret.
TARGETS: list[tuple[str, str, str, str]] = [
    ("users", "id", "email", "email"),
    ("users", "id", "access_token", "email"),
    ("users", "id", "refresh_token", "email"),
    ("users", "id", "totp_secret", "email"),
    ("login_tokens", "id", "email", "email"),
    ("ad_clicks", "id", "user_email", "email"),
    ("system_state", "id", "main_admin_email", "email"),
    ("provider_credentials", "id", "api_key", "vault"),
    ("system_provider_instances", "id", "api_key", "vault"),
    ("user_api_keys", "id", "api_key", "vault"),
]


def _rotate_email_value(cipher, value: str) -> str | None:
    """Re-encrypt one value; ``None`` when no known key can read it."""

    try:
        return cipher.rotate(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def rotate(batch_size: int = 500, dry_run: bool = False) -> dict[str, int]:
    email_cipher = _load_email_cipher()
    vault = IntegrationKeyVault.from_env()
    if email_cipher is None or vault is None:
        raise SystemExit(
            "EMAIL_ENCRYPTION_KEY and INTEGRATIONS_SECRET must both be set; "
            "refusing to run."
        )

    totals = {"rotated": 0, "unreadable": 0}
    session = SessionLocal()
    try:
        for table, pk, column, kind in TARGETS:
            last_id = 0
            while True:
                rows = session.execute(
                    text(
                        f"SELECT {pk}, {column} FROM {table} "  # noqa: S608 - fixed names
                        f"WHERE {pk} > :last AND {column} IS NOT NULL "
                        f"ORDER BY {pk} LIMIT :n"
                    ),
                    {"last": last_id, "n": batch_size},
                ).all()
                if not rows:
                    break
                for row_id, value in rows:
                    last_id = row_id
                    if kind == "email":
                        new_value = _rotate_email_value(email_cipher, value)
                    else:
                        new_value = vault.reencrypt(value)
                    if new_value is None:
                        totals["unreadable"] += 1
                        logger.warning(
                            "%s.%s id=%s cannot be read with any known key",
                            table,
                            column,
                            row_id,
                        )
                        continue
                    if not dry_run:
                        session.execute(
                            text(
                                f"UPDATE {table} SET {column} = :v "  # noqa: S608
                                f"WHERE {pk} = :id"
                            ),
                            {"v": new_value, "id": row_id},
                        )
                    totals["rotated"] += 1
                if not dry_run:
                    session.commit()
        logger.info("Key rotation complete: %s dry_run=%s", totals, dry_run)
        return totals
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    totals = rotate(batch_size=args.batch_size, dry_run=args.dry_run)
    return 1 if totals["unreadable"] else 0


if __name__ == "__main__":
    sys.exit(main())
