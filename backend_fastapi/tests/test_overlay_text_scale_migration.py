"""Migration 20261012: pixel sizes become the 1-100 slider, both ways."""

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


def test_sizes_are_converted_and_restored(tmp_path):
    db = tmp_path / "m.db"
    _alembic(db, "upgrade", "20261011_admin_password_single_use")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO user_processing_settings (user_id, overlay_font_size) VALUES (1, 20), (2, 40), (3, 10)"
        )

    _alembic(db, "upgrade", "20261012_overlay_text_scale")
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT user_id, overlay_font_size, overlay_match_bubble, overlay_outline_color"
            " FROM user_processing_settings ORDER BY user_id"
        ).fetchall()
        # Same on-screen size as before: 20 px -> 28.5 * 0.7 = 19.95 px.
        assert rows == [(1, 28.5, 1, None), (2, 57.0, 1, None), (3, 14.5, 1, None)]
        conn.execute("UPDATE user_processing_settings SET overlay_font_size = 100 WHERE user_id = 3")

    _alembic(db, "downgrade", "20261011_admin_password_single_use")
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT user_id, overlay_font_size FROM user_processing_settings ORDER BY user_id"
        ).fetchall()
        # Lossy: 70 px does not exist in the old 10-40 range and is clamped.
        assert rows == [(1, 20), (2, 40), (3, 40)]
        columns = {r[1] for r in conn.execute("PRAGMA table_info(user_processing_settings)")}
        assert not {"overlay_outline_color", "overlay_match_bubble"} & columns
