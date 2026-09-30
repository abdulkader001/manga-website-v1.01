"""Utility script to flag backward Alembic down_revision links.

This helper inspects all migration files under
``backend_fastapi/app/migrations/versions`` and warns whenever a revision
references a ``down_revision`` that lexicographically sorts after the
revision identifier itself.  The identifiers in this project follow a
timestamp prefix, so such a relationship almost always indicates that the
dependency chain is pointing "into the future" and should be corrected.

The script intentionally prints warnings instead of mutating any files so it
can be executed safely in CI or pre-deployment checks.  It provides the
relevant filename and the offending relationship so developers can adjust the
chain before running new migrations.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

VERSIONS_DIR = Path("backend_fastapi/app/migrations/versions")
REVISION_PATTERN = re.compile(r'revision\s*=\s*"([^"]+)"')
DOWN_REVISION_PATTERN = re.compile(r'down_revision\s*=\s*"([^"]+)"')

# Some historical migrations intentionally point to a "future" revision to preserve
# previously released database states.  They are enumerated here so the script can
# warn only on newly introduced issues.
ALLOWED_BACKLINKS = {
    ("a1b2c3d4e5f6", "20250909_sync_models"),
    (
        "20251224_add_updated_at_to_provider_credentials",
        "20251019_add_updated_at_to_users",
    ),
    ("d9d80c5ffdd8", "20251105_update_user_auth_schema"),
}


def main() -> None:
    if not VERSIONS_DIR.exists():
        raise SystemExit(f"Missing Alembic versions directory: {VERSIONS_DIR}")

    warnings: list[str] = []

    for filename in sorted(os.listdir(VERSIONS_DIR)):
        if not filename.endswith(".py"):
            continue

        path = VERSIONS_DIR / filename
        text = path.read_text(encoding="utf-8")

        revision_match = REVISION_PATTERN.search(text)
        down_revision_match = DOWN_REVISION_PATTERN.search(text)

        if not revision_match or not down_revision_match:
            continue

        revision = revision_match.group(1)
        down_revision = down_revision_match.group(1)

        revision_key = revision.split("_", 1)[0]
        down_revision_key = down_revision.split("_", 1)[0]

        if (
            down_revision_key > revision_key
            and (
                down_revision,
                revision,
            )
            not in ALLOWED_BACKLINKS
        ):
            warnings.append(
                f"⚠️  {filename}: backward link {down_revision} -> {revision}"
            )

    if warnings:
        for warning in warnings:
            print(warning)
    else:
        print("✅ Alembic down_revision links are in chronological order.")


if __name__ == "__main__":
    main()
