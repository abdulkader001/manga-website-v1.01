#!/usr/bin/env python3
"""Create a new .env from .env.example with fresh random secrets.

Standard-library Python only (3.9+). Run it from the project folder:

    python backend_fastapi/scripts/make_env.py            # for a server with a domain + HTTPS
    python backend_fastapi/scripts/make_env.py --local    # for trying it on this computer (http://localhost)

It fills SECRET_KEY, JWT_SECRET_KEY, MAGIC_LINK_SECRET, INTEGRATIONS_SECRET,
EMAIL_ENCRYPTION_KEY and the database/Redis passwords (also inside
DATABASE_URL, REDIS_URL and the two CELERY_ lines, so they always match).

It never touches an existing .env: changing these keys on a site that has
already run makes the stored data unreadable or the database refuse the
password. To start over, see the guide ("Start again from zero").
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fernet_key() -> str:
    # Same format as cryptography.fernet.Fernet.generate_key().
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def build(template: str, *, local: bool) -> str:
    pg = secrets.token_hex(16)
    redis = secrets.token_hex(16)
    text = template.replace("example-postgres-password", pg).replace("example-redis-password", redis)
    values = {
        "SECRET_KEY": secrets.token_hex(32),
        "JWT_SECRET_KEY": secrets.token_hex(32),
        "MAGIC_LINK_SECRET": secrets.token_hex(32),
        "INTEGRATIONS_SECRET": secrets.token_hex(32),
        "EMAIL_ENCRYPTION_KEY": fernet_key(),
    }
    if local:
        values.update(
            {"FORCE_HTTPS_REDIRECTS": "false", "APP_ENV": "development", "ENVIRONMENT": "development"}
        )
    for key, value in values.items():
        text, count = re.subn(rf"(?m)^{key}=.*$", f"{key}={value}", text, count=1)
        if not count:
            text += f"\n{key}={value}\n"
    return text


def main(argv: list[str]) -> None:
    if any(a in {"-h", "--help"} for a in argv):
        print(__doc__)
        return
    unknown = [a for a in argv if a != "--local"]
    if unknown:
        sys.exit(f"Unknown option {unknown[0]}. Use --local or nothing.")
    target = ROOT / ".env"
    if target.exists():
        sys.exit(
            f"{target} already exists, so nothing was changed.\n"
            "Changing the keys of a site that has already run breaks it. To start\n"
            "again from zero, follow the guide's 'Start again from zero' steps."
        )
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    # newline="\n": LF even on Windows, so Docker and Linux tools read it right.
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(build(template, local="--local" in argv))
    print(f"Created {target} with new random secrets.")
    if "--local" in argv:
        print("Local mode: the site runs on http://localhost:8080 (no HTTPS).")
    print("Back up this file somewhere safe: without it, stored e-mails and keys can't be read.")


if __name__ == "__main__":
    main(sys.argv[1:])
