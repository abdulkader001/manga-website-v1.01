#!/usr/bin/env python3
"""Make (or check) the two .env lines for the one-time Admin sign-in.

Needs only Python 3.9+ and the ``cryptography`` package -- no database, no
.env, no running site -- so it works on Windows, macOS and Linux directly, or
inside the backend Docker image.

Make the lines (asks for your e-mail and a password; leave the password empty
to have a strong one generated for you):

    python backend_fastapi/scripts/make_admin_hash.py                 # prints them
    python backend_fastapi/scripts/make_admin_hash.py --write .env    # puts them in .env

Check what is in .env against an e-mail and password ("my password doesn't
work"):

    python backend_fastapi/scripts/make_admin_hash.py --check            # reads ./.env
    python backend_fastapi/scripts/make_admin_hash.py --check path/to/.env

The printed values start with ``a2:`` and contain no ``$`` sign, so they can be
pasted into .env as they are: no quotes needed, and Docker Compose, PowerShell
and ``source .env`` leave them alone.
"""

from __future__ import annotations

import base64
import getpass
import os
import secrets
import re
import sys
from pathlib import Path

PREFIX = "a2:"
MIN_LENGTH = 12
KEYS = ("MAIN_ADMIN_EMAIL_HASH", "MAIN_ADMIN_PASSWORD_HASH")


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


def admin_lines(email: str, password: str) -> list[str]:
    return [
        f"MAIN_ADMIN_EMAIL_HASH={make_hash(normalize_email(email))}",
        f"MAIN_ADMIN_PASSWORD_HASH={make_hash(password.strip())}",
    ]


def _ask_email() -> str:
    email = normalize_email(input("Admin e-mail: "))
    if "@" not in email:
        sys.exit("That is not an e-mail address.")
    return email


def write_lines(path: Path, lines: list[str]) -> None:
    """Replace (or add) the MAIN_ADMIN_..._HASH lines in an .env file, in place."""

    raw = path.read_bytes().decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in raw else "\n"
    wanted = {line.split("=", 1)[0]: line for line in lines}
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
    email = _ask_email()
    password = getpass.getpass(
        f"One-time admin password ({MIN_LENGTH}+ characters, typing is hidden;\n"
        "  just press Enter to have one generated): "
    ).strip()
    generated = not password
    if generated:
        password = secrets.token_urlsafe(18)
    else:
        if len(password) < MIN_LENGTH:
            sys.exit(f"Use at least {MIN_LENGTH} characters (a few words is easiest).")
        if getpass.getpass("Type it again: ").strip() != password:
            sys.exit("The two passwords are different. Nothing was changed; run it again.")

    lines = admin_lines(email, password)
    print()
    if generated:
        print("Your one-time admin password (write it down now, it is not shown again):")
        print()
        print(f"    {password}")
        print()
    if write_to:
        write_lines(Path(write_to), lines)
        print(f"Done: both lines are now in {write_to} (old ones replaced).")
        print("Now restart the site so it reads .env again (see the guide).")
        return
    print("Put these two lines in .env (replace any old MAIN_ADMIN_..._HASH lines).")
    print("Paste them exactly as shown -- no quotes needed:")
    print()
    for line in lines:
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
        if key.strip() in KEYS:
            values[key.strip()] = value.strip()
    return values


def _check(env_path: str) -> None:
    path = Path(env_path)
    if not path.is_file():
        sys.exit(f"No file at {path.resolve()}. Run this from the project folder, or give the path.")
    values = _read_env(path)
    ok = True
    for key in KEYS:
        value = values.get(key, "")
        if not value:
            print(f"[X] {key} is missing or empty in {path}.")
            ok = False
            continue
        try:
            phc = unwrap(value)
        except Exception:
            phc = ""
        if not phc.startswith("$argon2id$"):
            print(
                f"[X] {key} is damaged (often a raw hash pasted without quotes, so every "
                "'$...' part was removed). Make new lines with this tool."
            )
            ok = False
        else:
            print(f"[ok] {key} looks valid.")
    if not ok:
        sys.exit(1)

    email = _ask_email()
    password = getpass.getpass("Password to test (hidden): ")
    email_ok = matches(email, values["MAIN_ADMIN_EMAIL_HASH"])
    password_ok = matches(password.strip(), values["MAIN_ADMIN_PASSWORD_HASH"]) or matches(
        password, values["MAIN_ADMIN_PASSWORD_HASH"]
    )
    print(f"[{'ok' if email_ok else 'X'}] e-mail {'matches' if email_ok else 'does NOT match'}")
    print(f"[{'ok' if password_ok else 'X'}] password {'matches' if password_ok else 'does NOT match'}")
    if email_ok and password_ok:
        print(
            "\nThe file is right. If /admin-login still refuses or shows 'Page not found':\n"
            "  - restart the site so it reads this .env again (see the guide), or\n"
            "  - the one-time password was already used: make new lines with this tool."
        )
    else:
        sys.exit(1)


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
