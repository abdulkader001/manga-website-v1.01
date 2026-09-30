"""Regression tests for the startup Alembic drift guard.

The guard shipped inert. `AlembicSchemaStatus` derived both revision sets by
regex-matching ``\\b[0-9a-z]{6,}\\b`` over the Alembic CLI's combined output.
This project's revision ids look like ``20260903_token_revocation`` -- the
underscore is a word character, so no word boundary ever falls inside one and
the pattern matched *nothing* in a real revision id, while Alembic's own INFO
logging ("Context impl PostgresqlImpl.", "Will assume transactional DDL.")
matched happily. Both sets therefore resolved to ``None`` on every run,
``schema_drift`` was permanently ``None``, and the caller's ``if
status.schema_drift: ... else: "passed"`` reported success unconditionally --
including for a container booting against a database that was migrations
behind.

These tests pin the two properties that failure needed: revisions are read
through Alembic's API (not scraped), and "undetermined" is never reported as
"no drift".
"""

from __future__ import annotations

from pathlib import Path

from backend_fastapi.app.utils.alembic_check import (
    AlembicSchemaStatus,
    _resolve_alembic_config,
    _read_head_revisions,
    capture_alembic_status,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _status(**kwargs) -> AlembicSchemaStatus:
    base = {
        "config_path": Path("alembic.ini"),
        "config_missing": False,
        "errors": [],
    }
    base.update(kwargs)
    return AlembicSchemaStatus(**base)


# ---------------------------------------------------------------------------
# Drift evaluation is tri-state, and only one of the three means "healthy".
# ---------------------------------------------------------------------------


def test_matching_revisions_report_no_drift() -> None:
    status = _status(
        head_revisions={"20260903_token_revocation"},
        current_revisions={"20260903_token_revocation"},
    )
    assert status.schema_drift is False
    assert status.determinate is True


def test_database_behind_head_reports_drift() -> None:
    status = _status(
        head_revisions={"20260903_token_revocation"},
        current_revisions={"20260902_users_created_at_default"},
    )
    assert status.schema_drift is True
    assert status.determinate is True


def test_unreadable_revisions_are_inconclusive_not_healthy() -> None:
    """The bug: `None` must not be mistaken for "no drift"."""

    unknown_current = _status(
        head_revisions={"20260903_token_revocation"}, current_revisions=None
    )
    unknown_heads = _status(
        head_revisions=None, current_revisions={"20260903_token_revocation"}
    )
    for status in (unknown_current, unknown_heads):
        assert status.schema_drift is None
        # `not None` is falsey -- which is exactly how this reported "passed".
        assert status.determinate is False


def test_missing_config_is_inconclusive() -> None:
    status = _status(config_missing=True, head_revisions=None, current_revisions=None)
    assert status.schema_drift is None
    assert status.determinate is False


def test_empty_database_is_drift_not_unknown() -> None:
    """A never-migrated database is a *known* state: empty, and drifted."""

    status = _status(head_revisions={"20260903_token_revocation"}, current_revisions=set())
    assert status.schema_drift is True
    assert status.determinate is True
    # An empty set must survive serialisation as [], not collapse to None.
    assert status.to_dict()["current_revisions"] == []


# ---------------------------------------------------------------------------
# Revisions come from Alembic, so this project's naming scheme parses.
# ---------------------------------------------------------------------------


def test_head_revisions_are_read_from_the_migration_scripts() -> None:
    config = _resolve_alembic_config()
    assert config is not None, "repository alembic.ini should be discoverable"

    heads = _read_head_revisions(config)

    assert heads, "migration scripts declare at least one head"
    assert len(heads) == 1, f"migration chain should have a single head, got {heads}"
    # The underscored id the old regex could not match.
    assert all("_" in revision for revision in heads)


def test_config_resolution_prefers_the_repository_root() -> None:
    """`backend_fastapi/alembic.ini` lacks prepend_sys_path and breaks env.py."""

    resolved = _resolve_alembic_config()
    assert resolved == REPO_ROOT / "alembic.ini"


def test_capture_reports_an_error_rather_than_a_false_pass(monkeypatch) -> None:
    """If the heads cannot be read, the result is inconclusive, not healthy."""

    monkeypatch.setattr(
        "backend_fastapi.app.utils.alembic_check._read_head_revisions",
        lambda _config: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    status = capture_alembic_status()

    assert status.head_revisions is None
    assert status.schema_drift is None
    assert status.determinate is False
    assert any("boom" in error for error in status.errors)
