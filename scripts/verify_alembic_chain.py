"""Automatically verify and repair Alembic migration state."""

from __future__ import annotations

import ast
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = REPO_ROOT / "backend_fastapi" / "app" / "migrations" / "versions"
ALEMBIC_CONFIG = REPO_ROOT / "alembic.ini"


class AlembicError(RuntimeError):
    """Raised when the Alembic CLI fails."""


def _iter_revision_edges() -> Iterable[tuple[str, Sequence[str]]]:
    if not VERSIONS_DIR.exists():
        raise SystemExit(f"Missing Alembic versions directory: {VERSIONS_DIR}")

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        revision, parents = _parse_revision_file(path)
        if revision:
            yield revision, parents


def _parse_revision_file(path: Path) -> tuple[str | None, list[str]]:
    text = path.read_text(encoding="utf-8")
    module = ast.parse(text)
    revision: str | None = None
    parents: list[str] = []

    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "revision":
                revision = ast.literal_eval(node.value)
            elif target.id in {"down_revision", "down_revisions"}:
                value = ast.literal_eval(node.value)
                parents = _normalize_parents(value)
    return revision, parents


def _normalize_parents(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def _discover_heads() -> list[str]:
    children: set[str] = set()
    parents: set[str] = set()

    for revision, down_revisions in _iter_revision_edges():
        children.add(revision)
        parents.update(down_revisions)

    return sorted(children - parents)


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    if not ALEMBIC_CONFIG.exists():
        raise SystemExit(f"Missing Alembic configuration file: {ALEMBIC_CONFIG}")

    cmd = ("alembic", "-c", str(ALEMBIC_CONFIG), *args)
    print(f"→ {shlex.join(cmd)}")
    process = subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
    )

    if process.stdout:
        print(process.stdout.rstrip())
    if process.stderr:
        print(process.stderr.rstrip(), file=sys.stderr)

    if process.returncode != 0:
        raise AlembicError(
            f"Command {' '.join(cmd)} failed with exit code {process.returncode}."
        )
    return process


def main() -> None:
    print("🔍 Verifying Alembic migration chain...")
    heads = _discover_heads()
    if len(heads) == 0:
        raise SystemExit("No Alembic heads found; ensure migrations are present.")
    if len(heads) > 1:
        print("❌ Detected multiple Alembic head revisions:")
        for head in heads:
            print(f"  - {head}")
        raise SystemExit(1)

    head = heads[0]
    print(f"✅ Single head revision detected: {head}")

    try:
        _run_alembic("upgrade", "head")
    except AlembicError as exc:
        print("❌ Failed to apply Alembic migrations.")
        raise SystemExit(str(exc))

    try:
        current = _run_alembic("current")
    except AlembicError as exc:
        print("❌ Unable to determine current Alembic revision.")
        raise SystemExit(str(exc))

    stdout = current.stdout or ""
    if head not in stdout:
        print("❌ Database revision does not match migration head.")
        raise SystemExit(1)

    print("✅ Database schema is synchronized with Alembic head.")


if __name__ == "__main__":
    main()
