"""Migration 20261016: Site Functions table and the per-person tab columns, both ways."""

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


def _columns(db: Path, table: str) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _tables(db: Path) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_upgrade_adds_the_table_and_columns_and_downgrade_removes_them(tmp_path):
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "20261015_login_required_default_on")
    assert "site_functions" not in _tables(db)
    assert not {"visible_admin_tabs", "powers_suspended"} & _columns(db, "users")

    _alembic(db, "upgrade", "20261016_site_functions_and_tab_access")
    assert "site_functions" in _tables(db)
    assert {"key", "enabled", "updated_by"} <= _columns(db, "site_functions")
    assert {"visible_admin_tabs", "powers_suspended"} <= _columns(db, "users")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (id, email, email_hash, email_identity_hash, role) "
            "VALUES (1, 'x@example.com', 'h', 'i', 'user')"
        )
        # An existing person starts with "follow my permissions" and powers on.
        assert conn.execute("SELECT visible_admin_tabs, powers_suspended FROM users").fetchone() == (None, 0)

    _alembic(db, "downgrade", "20261015_login_required_default_on")
    assert "site_functions" not in _tables(db)
    assert not {"visible_admin_tabs", "powers_suspended"} & _columns(db, "users")
