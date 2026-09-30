"""Regression test for the admin-bootstrap CLI script.

Live-verified during a manual runtime pass (2026-08-14): ``scripts/cli_bootstrap.py``
opened with ``from backend_fastapi.app.db import SessionLocal`` -- that module has
never existed; the package is ``backend_fastapi.app.core.db``. Every other call site
in the repository uses the correct path. This is the same bug class as F-11 (a stale
import left over from a directory move, invisible to static checks since it only
executes when the module is actually imported).

The blast radius is total: per ``docs/system-reference/01-authentication-and-sessions.md``,
this script is *the only caller of* ``admin_bootstrap.issue_admin_token`` anywhere in
the codebase -- there is deliberately no HTTP endpoint that mints the bootstrap token.
A fresh production deployment following the documented process (roadmap step 8,
"claim the admin account using the one-time token") could never produce a Permanent
Administrator: the CLI raised ``ModuleNotFoundError`` before any of its subcommands
ran. No test imported this module, so nothing caught it.
"""

from __future__ import annotations

from click.testing import CliRunner

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User
from backend_fastapi.scripts import cli_bootstrap


def _create_user(session, *, email: str) -> User:
    user = User(email=email, is_active=True, name="Bootstrap CLI User", provider="magic_link")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_cli_bootstrap_module_imports_cleanly():
    """The bare import must not raise -- this alone would have caught the bug."""

    assert cli_bootstrap.cli is not None


def test_issue_and_redeem_admin_token_end_to_end(monkeypatch):
    """The two subcommands this script exists for must actually run and work."""

    monkeypatch.setenv("ADMIN_PROMOTION_SECRET", "cli-bootstrap-regression-key")

    session = SessionLocal()
    try:
        user = _create_user(session, email="cli-bootstrap-target@example.com")
        user_id = user.id
    finally:
        session.close()

    runner = CliRunner()

    issue_result = runner.invoke(
        cli_bootstrap.cli, ["issue-admin-token", "--user-id", str(user_id)]
    )
    assert issue_result.exit_code == 0, issue_result.output
    lines = [line for line in issue_result.output.splitlines() if line.strip()]
    token = lines[-1].strip()
    assert token, issue_result.output

    promote_result = runner.invoke(
        cli_bootstrap.cli,
        ["promote-user", "--token", token, "--user-id", str(user_id)],
    )
    assert promote_result.exit_code == 0, promote_result.output
    assert "promoted" in promote_result.output.lower()

    session = SessionLocal()
    try:
        refreshed = session.get(User, user_id)
        assert refreshed.permanent is True
        assert refreshed.is_main_admin is True
    finally:
        session.close()
