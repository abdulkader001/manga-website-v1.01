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


def test_login_link_prints_a_working_one_time_link():
    from backend_fastapi.app.models import LoginToken
    from backend_fastapi.app.services.auth_service import hash_login_token

    result = CliRunner().invoke(
        cli_bootstrap.cli, ["login-link", "--email", "cli-login-link@example.com"]
    )
    assert result.exit_code == 0, result.output
    link = next(line for line in result.output.splitlines() if "/magic-link/" in line)
    token = link.rsplit("/magic-link/", 1)[1].strip()

    session = SessionLocal()
    try:
        record = (
            session.query(LoginToken)
            .filter(LoginToken.token_hash == hash_login_token(token))
            .one()
        )
        assert record.used_at is None
    finally:
        session.close()


def test_login_link_refuses_a_non_address():
    result = CliRunner().invoke(cli_bootstrap.cli, ["login-link", "--email", "nope"])
    assert result.exit_code != 0


def test_admin_hashes_prints_env_lines_that_verify():
    from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

    result = CliRunner().invoke(
        cli_bootstrap.cli,
        ["admin-hashes", "--email", "Owner@Example.com", "--password", "a long pass phrase"],
    )
    assert result.exit_code == 0, result.output
    lines = dict(
        line.split("=", 1) for line in result.output.splitlines() if line.startswith("MAIN_ADMIN_")
    )
    pw_hash = lines["MAIN_ADMIN_PASSWORD_HASH"].strip("'")
    mail_hash = lines["MAIN_ADMIN_EMAIL_HASH"].strip("'")
    Argon2id.verify_phc_encoded(b"a long pass phrase", pw_hash)
    Argon2id.verify_phc_encoded(b"owner@example.com", mail_hash)


def test_admin_hashes_refuses_a_short_password():
    result = CliRunner().invoke(
        cli_bootstrap.cli, ["admin-hashes", "--email", "a@example.com", "--password", "short"]
    )
    assert result.exit_code != 0


def test_reset_2fa_removes_the_authenticator():
    from backend_fastapi.app.services import admin_second_factor as sf

    email = "cli-reset-2fa@example.com"
    CliRunner().invoke(cli_bootstrap.cli, ["login-link", "--email", email])
    session = SessionLocal()
    try:
        user = cli_bootstrap._resolve_user(session, user_id=None, email=email)
        sf.start_enrolment(session, user)
        user.totp_enabled = True
        session.commit()
    finally:
        session.close()

    result = CliRunner().invoke(cli_bootstrap.cli, ["reset-2fa", "--email", email])
    assert result.exit_code == 0, result.output
    session = SessionLocal()
    try:
        user = cli_bootstrap._resolve_user(session, user_id=None, email=email)
        assert not user.totp_enabled and user.totp_secret_encrypted is None
    finally:
        session.close()
