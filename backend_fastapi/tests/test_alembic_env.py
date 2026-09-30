"""Regression tests for app/migrations/env.py's URL handling.

Alembic's Config previously round-tripped the resolved database URL through
``config.set_main_option``, which stores the value in a ``ConfigParser``
that applies %-style interpolation on read. A literal ``%`` in the URL (for
example a URL-encoded character in the password, such as ``%40`` for ``@``
or ``%25`` for a literal ``%``) is not valid interpolation syntax and made
Alembic crash before it ever reached the database. env.py now passes the
resolved URL directly to SQLAlchemy instead, so it must never go through
that ConfigParser round-trip.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _run_alembic_upgrade(database_url: str, *, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_alembic_upgrade_survives_percent_in_database_url(tmp_path: Path) -> None:
    """A DATABASE_URL containing a literal '%' must not crash Alembic.

    ``%f`` is not valid ConfigParser interpolation syntax ('%' must be
    followed by '%' or '('), so this reproduces the exact failure mode a
    URL-encoded '%' in a database password would trigger if the URL were
    ever passed through ``config.set_main_option``.
    """

    db_path = tmp_path / "db%file.sqlite3"
    database_url = f"sqlite:///{db_path}"

    result = _run_alembic_upgrade(database_url, cwd=REPO_ROOT)

    assert result.returncode == 0, (
        f"alembic upgrade head failed with a '%' in DATABASE_URL:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert db_path.exists()

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    # The system_settings migration (added by this change) must have run,
    # proving the full migration chain completed rather than failing early.
    assert "system_settings" in tables
    assert "alembic_version" in tables


def test_alembic_fails_loudly_without_database_url(tmp_path: Path) -> None:
    """Alembic must refuse to run rather than silently falling back."""

    env = dict(os.environ)
    env.pop("DATABASE_URL", None)

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr
