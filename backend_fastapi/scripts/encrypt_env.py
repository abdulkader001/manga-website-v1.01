#!/usr/bin/env python3
"""Utility for encrypting .env files using Fernet symmetric encryption."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cryptography.fernet import Fernet


def _load_or_generate_key(key_path: Path | None) -> bytes:
    if key_path and key_path.exists():
        return key_path.read_text(encoding="utf-8").strip().encode("utf-8")
    return Fernet.generate_key()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        "-i",
        default=".env",
        help="Path to the plaintext environment file (default: .env)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=".env.enc",
        help="Destination for the encrypted payload (default: .env.enc)",
    )
    parser.add_argument(
        "--key-file",
        "-k",
        default=None,
        help="Optional file path where the Fernet key should be read from or written to.",
    )
    parser.add_argument(
        "--print-key",
        action="store_true",
        help="Echo the Fernet key to stdout (use only for secure terminals).",
    )

    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        parser.error(f"Input file {input_path!s} does not exist")

    key_path = Path(args.key_file).expanduser() if args.key_file else None
    key = _load_or_generate_key(key_path)

    plaintext = input_path.read_bytes()
    encrypted = Fernet(key).encrypt(plaintext)

    output_path = Path(args.output)
    output_path.write_bytes(encrypted)

    if key_path:
        key_path.write_text(key.decode("utf-8"), encoding="utf-8")

    if args.print_key:
        print(key.decode("utf-8"))

    sys.stderr.write(
        "Encrypted environment written to {output}\n".format(output=output_path)
    )
    sys.stderr.write(
        "Store the Fernet key in a hardware token, secrets manager, or vault.\n"
    )

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
