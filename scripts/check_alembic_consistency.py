"""Inspect Alembic revisions for divergent heads and backwards links."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

VERSIONS_DIR = Path("backend_fastapi/app/migrations/versions")
REVISION_RE = re.compile(r"revision\s*(?::[^=]+)?=\s*[\"'](?P<rev>[^\"']+)[\"']")
DOWN_REVISION_RE = re.compile(
    r"down_revisions?\s*(?::[^=]+)?=\s*"
    r"(?:\[(?P<list>[^\]]*)\]|\((?P<tuple>[^)]*)\)|[\"'](?P<single>[^\"']+)[\"'])"
)


def _iter_revision_pairs() -> Iterable[tuple[str, list[str]]]:
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision_match = REVISION_RE.search(text)
        down_revision_match = DOWN_REVISION_RE.search(text)
        if not revision_match:
            continue
        revision = revision_match.group("rev")
        if not down_revision_match:
            yield revision, []
            continue
        if down_revision_match.group("list"):
            raw = down_revision_match.group("list")
            parts = [
                item.strip().strip("'\"") for item in raw.split(",") if item.strip()
            ]
        elif down_revision_match.group("tuple"):
            raw = down_revision_match.group("tuple")
            parts = [
                item.strip().strip("'\"") for item in raw.split(",") if item.strip()
            ]
        else:
            parts = (
                [down_revision_match.group("single")]
                if down_revision_match.group("single")
                else []
            )
        yield revision, parts


def _build_reverse_edges() -> dict[str, list[str]]:
    graph: defaultdict[str, list[str]] = defaultdict(list)
    for revision, parents in _iter_revision_pairs():
        if not parents:
            graph[""].append(revision)
            continue
        for parent in parents:
            graph[parent].append(revision)
    return graph


def main() -> None:
    if not VERSIONS_DIR.exists():
        raise SystemExit(f"Missing Alembic versions directory: {VERSIONS_DIR}")

    graph = _build_reverse_edges()

    print("Revision Graph:")
    for parent, children in sorted(graph.items()):
        label = parent or "<base>"
        print(f"  {label} -> {', '.join(sorted(children))}")

    parents = set(graph.keys())
    children = {child for siblings in graph.values() for child in siblings}
    heads = sorted(children - parents)
    if len(heads) > 1:
        print("\n⚠️ Detected multiple head revisions:")
        for head in heads:
            print(f"  {head}")

    dangling = [
        parent for parent, children in graph.items() if parent and len(children) > 1
    ]
    if dangling:
        print("\n⚠️ Parents with multiple child revisions (potential splits):")
        for parent in dangling:
            print(f"  {parent}: {', '.join(sorted(graph[parent]))}")


if __name__ == "__main__":
    main()
