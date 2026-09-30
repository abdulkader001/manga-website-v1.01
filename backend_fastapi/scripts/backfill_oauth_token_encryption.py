#!/usr/bin/env python3
"""Encrypt any pre-existing plaintext OAuth tokens at rest (Blind Spot #16).

After the ``20260502_encrypt_oauth_tokens`` migration widens the columns, this
script encrypts any rows whose access_token/refresh_token are still stored in
plaintext.

Properties:
- **Idempotent**: a value that is already Fernet-encrypted decrypts cleanly and
  is left untouched; only plaintext values are re-written as ciphertext.
- **Resumable**: commits in batches.
- Requires the email/secret encryption key to be configured.

Usage:
    python -m backend_fastapi.scripts.backfill_oauth_token_encryption [--batch-size N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User
from backend_fastapi.app.utils.email_crypto import (
    _load_email_cipher,
    encrypt_secret,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_oauth_token_encryption")


def _is_plaintext(cipher, value: str | None) -> bool:
    """True when ``value`` is present but not already Fernet ciphertext."""

    if not value:
        return False
    from cryptography.fernet import InvalidToken

    try:
        cipher.decrypt(value.encode("utf-8"))
        return False  # decrypts -> already encrypted
    except InvalidToken:
        return True


def backfill(batch_size: int = 500, dry_run: bool = False) -> int:
    cipher = _load_email_cipher()
    if cipher is None:
        logger.error("No encryption key configured; refusing to run.")
        return 0

    updated = 0
    session = SessionLocal()
    try:
        offset = 0
        while True:
            rows = (
                session.query(User)
                .order_by(User.id.asc())
                .offset(offset)
                .limit(batch_size)
                .all()
            )
            if not rows:
                break
            for user in rows:
                for column in ("access_token_encrypted", "refresh_token_encrypted"):
                    raw = getattr(user, column)
                    if _is_plaintext(cipher, raw):
                        if not dry_run:
                            setattr(user, column, encrypt_secret(raw))
                        updated += 1
            if not dry_run:
                session.commit()
            offset += batch_size

        logger.info(
            "OAuth token backfill complete: updated=%s dry_run=%s", updated, dry_run
        )
        return updated
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    backfill(batch_size=args.batch_size, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
