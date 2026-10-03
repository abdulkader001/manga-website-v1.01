"""The server-side admin commands (scripts/cli_bootstrap.py).

The module must import cleanly (it once failed on a stale import and nobody
noticed), and ``admin-hashes`` must work with no database or .env at all.
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


def test_login_link_prints_a_working_one_time_link(fastapi_app):
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


def test_admin_hashes_prints_a_dollar_free_env_line_that_verifies():
    from backend_fastapi.scripts import make_admin_hash

    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-hashes"], input="Owner@Example.com\n")
    assert result.exit_code == 0, result.output
    lines = dict(
        line.split("=", 1) for line in result.output.splitlines() if line.startswith("MAIN_ADMIN_")
    )
    # Only the e-mail hash: there is no admin password any more.
    assert list(lines) == ["MAIN_ADMIN_EMAIL_HASH"]
    assert "$" not in lines["MAIN_ADMIN_EMAIL_HASH"] and lines["MAIN_ADMIN_EMAIL_HASH"].startswith("a2:")
    assert make_admin_hash.matches("owner@example.com", lines["MAIN_ADMIN_EMAIL_HASH"])


def test_admin_hashes_refuses_a_non_address():
    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-hashes"], input="not-an-address\n")
    assert result.exit_code != 0
    assert "MAIN_ADMIN_EMAIL_HASH=" not in result.output


def test_hash_tool_runs_without_the_app(tmp_path):
    """Plain `python make_admin_hash.py --check`: no database, no .env, no app imports."""

    import subprocess
    import sys
    from pathlib import Path

    from backend_fastapi.scripts import make_admin_hash

    env_file = tmp_path / ".env"
    env_file.write_text(make_admin_hash.email_line("me@example.com") + "\n")
    script = Path(make_admin_hash.__file__)
    run = subprocess.run(
        [sys.executable, str(script), "--check", str(env_file)],
        input="me@example.com\n",
        capture_output=True,
        text=True,
        env={"PATH": "", "PYTHONPATH": ""},
        cwd=tmp_path,
        timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "MAIN_ADMIN_EMAIL_HASH looks valid" in run.stdout, run.stdout + run.stderr
    assert "e-mail matches" in run.stdout


def test_admin_status_reports_the_owner_seat(fastapi_app, monkeypatch):
    from backend_fastapi.app.core.settings import settings
    from backend_fastapi.scripts import make_admin_hash
    from _support.db_reset import clear_users

    with SessionLocal() as session:
        clear_users(session)
    line = make_admin_hash.email_line("st@example.com")
    monkeypatch.setattr(settings, "main_admin_email_hash", line.split("=", 1)[1], raising=False)
    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-status"])
    assert result.exit_code == 0, result.output
    assert "MAIN_ADMIN_EMAIL_HASH: set" in result.output
    assert "Owner: not claimed yet" in result.output
    monkeypatch.setattr(settings, "main_admin_email_hash", None, raising=False)
    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-status"])
    assert "MAIN_ADMIN_EMAIL_HASH: not set" in result.output


def test_reset_2fa_removes_the_authenticator(fastapi_app):
    from backend_fastapi.app.services import admin_second_factor as sf

    email = "cli-reset-2fa@example.com"
    CliRunner().invoke(cli_bootstrap.cli, ["login-link", "--email", email])
    session = SessionLocal()
    try:
        user = cli_bootstrap._resolve_user(session, email)
        sf.start_enrolment(session, user)
        user.totp_enabled = True
        session.commit()
    finally:
        session.close()

    result = CliRunner().invoke(cli_bootstrap.cli, ["reset-2fa", "--email", email])
    assert result.exit_code == 0, result.output
    session = SessionLocal()
    try:
        user = cli_bootstrap._resolve_user(session, email)
        assert not user.totp_enabled and user.totp_secret_encrypted is None
    finally:
        session.close()


def test_write_puts_the_line_into_env_keeping_windows_line_endings(tmp_path):
    from backend_fastapi.scripts import make_admin_hash

    env = tmp_path / ".env"
    env.write_bytes(
        b"A=1\r\nMAIN_ADMIN_EMAIL_HASH='$old'\r\nMAIN_ADMIN_PASSWORD_HASH=old\r\nB=2\r\nMAIN_ADMIN_EMAIL_HASH=dupe\r\n"
    )
    make_admin_hash.write_line(env, make_admin_hash.email_line("me@example.com"))
    data = env.read_bytes().decode()
    assert data.count("MAIN_ADMIN_EMAIL_HASH=") == 1
    assert "$old" not in data and "\n" not in data.replace("\r\n", "")
    assert data.startswith("A=1\r\n") and "B=2\r\n" in data


def test_functions_reset_puts_every_function_back_to_its_default(fastapi_app):
    from backend_fastapi.app.core import site_functions as registry
    from backend_fastapi.app.services import site_functions

    with SessionLocal() as session:
        site_functions.set_enabled(session, "comments", False, None)
        site_functions.set_enabled(session, "ads", False, None)
    result = CliRunner().invoke(cli_bootstrap.cli, ["functions-reset"])
    assert result.exit_code == 0, result.output
    with SessionLocal() as session:
        states = site_functions.states(session)
        assert all(states[k] == registry.REGISTRY[k].default for k in registry.REGISTRY)
        # The shared test site is open to guests (tests/conftest.py).
        site_functions.set_enabled(session, "sign_in_required", False, None)
