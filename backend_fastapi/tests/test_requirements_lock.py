"""The lockfile is what the image installs, so it has to stay honest.

`requirements.lock` was committed as pip-compile output and described in
`requirements.txt` as the reproducible-build mechanism -- but nothing
installed it. The Dockerfile and CI both used `requirements.txt`, which pins
only the direct dependencies, leaving every transitive package free to float
between builds of the same commit.

The Dockerfile now installs the lock. These tests stop the two files from
drifting apart, which is the failure mode that makes a lockfile worse than
none: a stale lock silently pins old versions of everything.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REQUIREMENTS = BACKEND / "requirements.txt"
LOCK = BACKEND / "requirements.lock"
DOCKERFILE = BACKEND / "Dockerfile"

_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]+\])?==([^\s;]+)")


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        match = _PIN.match(line)
        if match:
            name = match.group(1).lower().replace("_", "-")
            pins[name] = match.group(3)
    return pins


def test_lock_covers_every_direct_dependency() -> None:
    missing = sorted(set(_pins(REQUIREMENTS)) - set(_pins(LOCK)))
    assert not missing, (
        "requirements.txt pins packages absent from requirements.lock "
        f"({missing}); regenerate with: pip-compile --output-file=requirements.lock "
        "--strip-extras requirements.txt"
    )


def test_lock_agrees_with_the_direct_pins() -> None:
    requirements, lock = _pins(REQUIREMENTS), _pins(LOCK)
    drift = {
        name: (version, lock[name])
        for name, version in requirements.items()
        if name in lock and lock[name] != version
    }
    assert not drift, (
        "requirements.txt and requirements.lock disagree "
        f"(name: (requirements.txt, lock)) -> {drift}; regenerate the lock"
    )


def test_lock_pins_transitive_dependencies_too() -> None:
    """A lock that only repeats the direct pins buys nothing."""

    requirements, lock = _pins(REQUIREMENTS), _pins(LOCK)
    transitive = set(lock) - set(requirements)
    assert len(transitive) > len(requirements) // 2, (
        "requirements.lock looks like it is missing transitive dependencies: "
        f"{len(lock)} locked vs {len(requirements)} direct"
    )


def test_lock_pins_are_all_exact() -> None:
    """No range specifiers -- a range in a lockfile is not a lock."""

    loose = [
        line.strip()
        for raw in LOCK.read_text().splitlines()
        for line in [raw.split("#", 1)[0]]
        if line.strip()
        and not line.strip().startswith("-")
        and "==" not in line
    ]
    assert not loose, f"non-exact requirement lines in the lockfile: {loose}"


def test_the_image_installs_the_lock_not_the_bare_requirements() -> None:
    """The regression that made the lockfile decorative."""

    install_lines = [
        line
        for line in DOCKERFILE.read_text().splitlines()
        if "pip install" in line and "requirements" in line
    ]
    assert install_lines, "Dockerfile has no pip install step for requirements"
    for line in install_lines:
        assert "requirements.lock" in line, (
            "the backend image must install requirements.lock for reproducible "
            f"builds, got: {line.strip()}"
        )
