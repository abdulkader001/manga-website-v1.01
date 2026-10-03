"""Migrations 20261015 (sign-in required on by default) and 20261017 (back to off)."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(db: Path, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}", "PYTHONPATH": str(BACKEND.parent)}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True, capture_output=True
    )


def _value(db: Path):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT login_required FROM system_settings").fetchone()


def test_existing_site_is_switched_on_and_new_rows_start_on(tmp_path):
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "20261014_four_roles")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO system_settings (id, login_required) VALUES (1, 0)")
    assert _value(db) == (0,)

    _alembic(db, "upgrade", "20261015_login_required_default_on")
    assert _value(db) == (1,)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM system_settings")
        conn.execute("INSERT INTO system_settings (id) VALUES (1)")
    assert _value(db) == (1,)  # the column default is now "on"


def test_downgrade_puts_the_default_back(tmp_path):
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "20261015_login_required_default_on")
    _alembic(db, "downgrade", "20261014_four_roles")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO system_settings (id) VALUES (1)")
    assert _value(db) == (0,)


# Migration 20261017: the owner changed their mind; the site starts open again.


def test_20261017_switches_the_existing_site_off_and_new_rows_start_off(tmp_path):
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "20261016_site_functions_and_tab_access")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO system_settings (id) VALUES (1)")
    assert _value(db) == (1,)  # 20261015 made "on" the default

    _alembic(db, "upgrade", "20261017_login_required_default_off")
    assert _value(db) == (0,)
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM system_settings")
        conn.execute("INSERT INTO system_settings (id) VALUES (1)")
    assert _value(db) == (0,)  # the column default is now "off"


def test_20261017_downgrade_puts_the_on_default_back(tmp_path):
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "20261017_login_required_default_off")
    _alembic(db, "downgrade", "20261016_site_functions_and_tab_access")
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO system_settings (id) VALUES (1)")
    assert _value(db) == (1,)
