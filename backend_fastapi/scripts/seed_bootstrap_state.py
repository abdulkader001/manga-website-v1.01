#!/usr/bin/env python3
"""Create the singleton system_state row after migrations (run by the migrate job)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("seed_bootstrap_state")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    # Append, not insert(0): this must not take priority over installed
    # packages. A same-named directory at the repo root (e.g. the test-only
    # httpx/ stub in backend_fastapi/tests/conftest.py) would otherwise
    # shadow the real installed dependency of the same name for this process.
    sys.path.append(str(ROOT))


def main() -> None:
    from backend_fastapi.app.services.system_state import (
        ensure_system_state_initialized,
    )

    logger.info("Ensuring system_state singleton row exists")
    ensure_system_state_initialized()
    logger.info("System state ready")


if __name__ == "__main__":
    main()
