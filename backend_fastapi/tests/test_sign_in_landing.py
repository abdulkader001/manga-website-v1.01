"""plan.md P0-4: Google / Microsoft sign-in must land on a page the site has.

Both callbacks redirect to MAGIC_LINK_REDIRECT_URL. Its value came from
``.env.example``, GUIDE.md and the vault's domain switch as
``.../auth/magic-complete``, a path the React app did not route, so every
sign-in ended on the 404 page.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from backend_fastapi.app.vault_keys import derived_from_domain

ROOT = Path(__file__).resolve().parents[2]


def _spa_paths() -> set[str]:
    source = (ROOT / "src" / "app.js").read_text(encoding="utf-8")
    return set(re.findall(r'path="([^"]+)"', source))


def _env_example_value(name: str) -> str:
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{name} missing from .env.example")


def test_every_default_landing_address_is_a_page():
    paths = _spa_paths()
    for url in (
        derived_from_domain("manga.example.com")["MAGIC_LINK_REDIRECT_URL"],
        _env_example_value("MAGIC_LINK_REDIRECT_URL"),
    ):
        assert urlparse(url).path in paths, f"{url} has no page in src/app.js"


def test_the_old_landing_address_still_has_a_page():
    # Values already saved in a server's .env or vault keep working.
    assert "/auth/magic-complete" in _spa_paths()
