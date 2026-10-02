#!/usr/bin/env python3
"""Make (or check) the .env line that says who the site owner is.

Needs only Python 3.9+ and the ``cryptography`` package -- no database, no
.env, no running site -- so it works on Windows, macOS and Linux directly, or
inside the backend Docker image.

The site keeps only a hash of your e-mail: ``MAIN_ADMIN_EMAIL_HASH``. The first
time you sign in with Google using that address (Google must say it is
verified), your account becomes the owner. There is no admin password.

Make the line (asks for your e-mail):

    python backend_fastapi/scripts/make_admin_hash.py                 # prints it
    python backend_fastapi/scripts/make_admin_hash.py --write .env    # puts it in .env

Check what is in .env against an e-mail ("Google sign-in does not make me
owner"):

    python backend_fastapi/scripts/make_admin_hash.py --check            # reads ./.env
    python backend_fastapi/scripts/make_admin_hash.py --check path/to/.env

The printed value starts with ``a2:`` and contains no ``$`` sign, so it can be
pasted into .env as it is: no quotes needed, and Docker Compose, PowerShell
and ``source .env`` leave it alone.
"""

from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

PREFIX = "a2:"
KEY = "MAIN_ADMIN_EMAIL_HASH"


def _argon2():
    try:
        from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
    except ImportError:
        Argon2id = None
    if Argon2id is None or not hasattr(Argon2id, "derive_phc_encoded"):
        sys.exit(
            "This needs a newer 'cryptography' package. Install it with:\n"
            '    python -m pip install --upgrade "cryptography>=45"\n'
            "(or run this inside the backend container -- see the guide)."
        )
    return Argon2id


def normalize_email(value: str) -> str:
    # Must match backend_fastapi/app/utils/email_crypto.normalize_email.
    return (value or "").strip().lower()


def make_hash(value: str) -> str:
    Argon2id = _argon2()
    kdf = Argon2id(salt=os.urandom(16), length=32, iterations=3, lanes=4, memory_cost=65536)
    phc = kdf.derive_phc_encoded(value.encode("utf-8"))
    return PREFIX + base64.urlsafe_b64encode(phc.encode("utf-8")).decode("ascii").rstrip("=")


def unwrap(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    if text.startswith(PREFIX):
        body = text[len(PREFIX):]
        text = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
    return text


def matches(secret: str, value: str) -> bool:
    from cryptography.exceptions import InvalidKey

    Argon2id = _argon2()
    try:
        Argon2id.verify_phc_encoded(secret.encode("utf-8"), unwrap(value))
        return True
    except InvalidKey:
        return False


def email_line(email: str) -> str:
    return f"{KEY}={make_hash(normalize_email(email))}"


def _ask_email() -> str:
    email = normalize_email(input("Admin e-mail: "))
    if "@" not in email:
        sys.exit("That is not an e-mail address.")
    return email


def write_line(path: Path, line: str) -> None:
    """Replace (or add) the MAIN_ADMIN_EMAIL_HASH line in an .env file, in place."""

    raw = path.read_bytes().decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in raw else "\n"
    wanted = {line.split("=", 1)[0]: line}
    out: list[str] = []
    done: set[str] = set()
    for row in raw.splitlines(keepends=True):
        body = row.rstrip("\r\n")
        key = re.sub(r"^\s*(export\s+)?", "", body).split("=", 1)[0].strip()
        if key in wanted and "=" in body:
            if key not in done:  # keep one line per key; later duplicates would win
                out.append(wanted[key] + (row[len(body):] or newline))
                done.add(key)
            continue
        out.append(row)
    for key, line in wanted.items():
        if key not in done:
            if out and not out[-1].endswith(("\n", "\r")):
                out[-1] += newline
            out.append(line + newline)
    with open(path, "w", encoding="utf-8", newline="") as handle:  # same file, same owner
        handle.write("".join(out))


def _make(write_to: str | None = None) -> None:
    _argon2()
    if write_to and not Path(write_to).is_file():
        sys.exit(f"No file at {Path(write_to).resolve()}. Create .env first (see the guide).")
    line = email_line(_ask_email())
    print()
    if write_to:
        write_line(Path(write_to), line)
        print(f"Done: the line is now in {write_to} (an old one is replaced).")
        print("Now restart the site so it reads .env again (see the guide).")
        return
    print("Put this line in .env (replace any old MAIN_ADMIN_EMAIL_HASH line).")
    print("Paste it exactly as shown -- no quotes needed:")
    print()
    print(line)
    print()
    print("Then restart the site so it reads .env again (see the guide).")


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == KEY:
            values[key.strip()] = value.strip()
    return values


def _check(env_path: str) -> None:
    path = Path(env_path)
    if not path.is_file():
        sys.exit(f"No file at {path.resolve()}. Run this from the project folder, or give the path.")
    value = _read_env(path).get(KEY, "")
    if not value:
        sys.exit(f"[X] {KEY} is missing or empty in {path}.")
    try:
        phc = unwrap(value)
    except Exception:
        phc = ""
    if not phc.startswith("$argon2id$"):
        sys.exit(
            f"[X] {KEY} is damaged (often a raw hash pasted without quotes, so every "
            "'$...' part was removed). Make a new line with this tool."
        )
    print(f"[ok] {KEY} looks valid.")

    email_ok = matches(_ask_email(), value)
    print(f"[{'ok' if email_ok else 'X'}] e-mail {'matches' if email_ok else 'does NOT match'}")
    if not email_ok:
        sys.exit(1)
    print(
        "\nThe file is right. If Google sign-in still does not make you the owner:\n"
        "  - restart the site so it reads this .env again (see the guide),\n"
        "  - sign in with Google using exactly this address (it must be verified), and\n"
        "  - the site must not already have an owner (admin-status says so)."
    )


def main(argv: list[str]) -> None:
    if argv and argv[0] in {"-h", "--help"}:
        print(__doc__)
        return
    if argv and argv[0] == "--check":
        _check(argv[1] if len(argv) > 1 else ".env")
        return
    if argv and argv[0] == "--write":
        _make(argv[1] if len(argv) > 1 else ".env")
        return
    if argv:
        sys.exit("Unknown option. Use --write [.env], --check [.env] or no options.")
    _make()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelled.")
