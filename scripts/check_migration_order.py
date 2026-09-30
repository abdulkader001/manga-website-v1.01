"""Utility to detect potentially misordered Alembic migrations."""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS_DIR = Path("backend_fastapi/app/migrations/versions")
REVISION_PATTERN = re.compile(
    r"revision\s*(?::[^=]+)?=\s*[\"'](?P<revision>[^\"']+)[\"']"
)
DOWN_REVISION_PATTERN = re.compile(
    r"down_revisions?\s*(?::[^=]+)?=\s*"
    r"(?:\[(?P<list>[^\]]*)\]|\((?P<tuple>[^)]*)\)|[\"'](?P<single>[^\"']+)[\"'])"
)
DATE_PREFIX = re.compile(r"^(?P<date>\d{8})")


def _parse_down_revisions(match: re.Match[str]) -> list[str]:
    if match.group("list"):
        raw = match.group("list")
    elif match.group("tuple"):
        raw = match.group("tuple")
    else:
        single = match.group("single")
        return [single] if single else []
    return [item.strip().strip("'\"") for item in raw.split(",") if item.strip()]


def _iter_migration_metadata():
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        text = path.read_text()
        revision_match = REVISION_PATTERN.search(text)
        down_revision_match = DOWN_REVISION_PATTERN.search(text)
        if revision_match and down_revision_match:
            yield path.name, revision_match.group("revision"), _parse_down_revisions(
                down_revision_match
            )


def main() -> None:
    issues_found = False
    for filename, revision, down_revisions in _iter_migration_metadata():
        rev_date = DATE_PREFIX.match(revision)
        if not rev_date:
            continue

        for down_revision in down_revisions:
            down_date = DATE_PREFIX.match(down_revision)
            if down_date and int(down_date.group("date")) > int(
                rev_date.group("date")
            ):
                print(
                    f"⚠️ {filename}: down_revision {down_revision} sorts after revision {revision} — check migration order!"
                )
                issues_found = True
    if not issues_found:
        print("✅ No reversed migrations detected.")


if __name__ == "__main__":
    if not VERSIONS_DIR.is_dir():
        raise SystemExit(f"Migration directory not found: {VERSIONS_DIR}")
    main()
