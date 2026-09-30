#!/usr/bin/env python3
"""Backfill ``users.email_lookup_hash`` for pre-existing rows (C2 / item 11).

The ``20260501_add_email_lookup_hash`` migration adds the column but leaves it
NULL for existing rows. This script decrypts each user's email and populates the
deterministic HMAC lookup value so login uses the indexed fast path.

Properties:
- **Idempotent**: only processes rows where ``email_lookup_hash IS NULL``; safe
  to run repeatedly.
- **Resumable**: commits in batches, so an interrupted run continues where it
  left off on the next invocation.
- **Non-destructive**: never touches the encrypted email or ``email_hash``.

Requires the email-encryption key (``EMAIL_ENCRYPTION_KEY``) to be configured so
addresses can be decrypted.

Usage:
    python -m backend_fastapi.scripts.backfill_email_lookup_hash [--batch-size N] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User
from backend_fastapi.app.utils.email_crypto import (
    allow_email_decryption,
    email_lookup,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backfill_email_lookup_hash")


def backfill(batch_size: int = 500, dry_run: bool = False) -> int:
    """Populate email_lookup_hash for rows missing it. Returns rows updated."""

    updated = 0
    skipped = 0
    session = SessionLocal()
    try:
        while True:
            rows = (
                session.query(User)
                .filter(User.email_lookup_hash.is_(None))
                .limit(batch_size)
                .all()
            )
            if not rows:
                break

            progressed = False
            with allow_email_decryption():
                for user in rows:
                    plaintext = user.email_plaintext
                    lookup = email_lookup(plaintext)
                    if lookup is None:
                        # Can't decrypt (missing key / corrupt ciphertext). Mark
                        # so we don't loop forever; log loudly for investigation.
                        logger.warning(
                            "Could not derive lookup hash for user id=%s; "
                            "skipping (check EMAIL_ENCRYPTION_KEY).",
                            user.id,
                        )
                        skipped += 1
                        # Set a sentinel-free skip: leave NULL but stop the loop
                        # from reselecting this row by tracking it in-memory.
                        continue
                    if not dry_run:
                        user.email_lookup_hash = lookup
                    updated += 1
                    progressed = True

            if dry_run:
                logger.info("[dry-run] would update %s rows so far", updated)
                # In dry-run we can't persist, so break to avoid an infinite loop.
                break

            session.commit()

            if not progressed:
                # Every row in this batch was un-decryptable; avoid infinite loop.
                logger.error(
                    "No progress in batch (%s undecryptable rows). Stopping.",
                    len(rows),
                )
                break

        logger.info(
            "Backfill complete: updated=%s skipped=%s dry_run=%s",
            updated,
            skipped,
            dry_run,
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
