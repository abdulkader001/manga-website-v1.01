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


def test_admin_hashes_prints_dollar_free_env_lines_that_verify(monkeypatch):
    from backend_fastapi.scripts import make_admin_hash

    answers = iter(["a long pass phrase", "a long pass phrase"])
    monkeypatch.setattr(make_admin_hash.getpass, "getpass", lambda prompt="": next(answers))
    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-hashes"], input="Owner@Example.com\n")
    assert result.exit_code == 0, result.output
    lines = dict(
        line.split("=", 1) for line in result.output.splitlines() if line.startswith("MAIN_ADMIN_")
    )
    assert all("$" not in v and v.startswith("a2:") for v in lines.values())
    assert make_admin_hash.matches("a long pass phrase", lines["MAIN_ADMIN_PASSWORD_HASH"])
    assert make_admin_hash.matches("owner@example.com", lines["MAIN_ADMIN_EMAIL_HASH"])


def test_admin_hashes_refuses_a_short_password(monkeypatch):
    from backend_fastapi.scripts import make_admin_hash

    monkeypatch.setattr(make_admin_hash.getpass, "getpass", lambda prompt="": "short")
    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-hashes"], input="a@example.com\n")
    assert result.exit_code != 0
    assert "MAIN_ADMIN_PASSWORD_HASH" not in result.output


def test_hash_tool_runs_without_the_app(tmp_path):
    """Plain `python make_admin_hash.py --check`: no database, no .env, no app imports."""

    import subprocess
    import sys
    from pathlib import Path

    from backend_fastapi.scripts import make_admin_hash

    env_file = tmp_path / ".env"
    env_file.write_text("\n".join(make_admin_hash.admin_lines("me@example.com", "a long pass phrase")))
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
    # getpass falls back to stdin without a terminal; stdin is exhausted, so it
    # stops at the password prompt -- but only after both lines were validated.
    assert "MAIN_ADMIN_EMAIL_HASH looks valid" in run.stdout, run.stdout + run.stderr
    assert "MAIN_ADMIN_PASSWORD_HASH looks valid" in run.stdout


def test_admin_status_reports_open_then_closed(fastapi_app, monkeypatch):
    from backend_fastapi.app.core.settings import settings
    from backend_fastapi.scripts import make_admin_hash

    lines = dict(x.split("=", 1) for x in make_admin_hash.admin_lines("st@example.com", "a long pass phrase"))
    monkeypatch.setattr(settings, "main_admin_email_hash", lines["MAIN_ADMIN_EMAIL_HASH"], raising=False)
    monkeypatch.setattr(settings, "main_admin_password_hash", lines["MAIN_ADMIN_PASSWORD_HASH"], raising=False)
    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-status"])
    assert result.exit_code == 0, result.output
    assert "OPEN" in result.output
    monkeypatch.setattr(settings, "main_admin_password_hash", None, raising=False)
    result = CliRunner().invoke(cli_bootstrap.cli, ["admin-status"])
    assert "CLOSED -- not set up" in result.output


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


def test_write_puts_the_lines_into_env_keeping_windows_line_endings(tmp_path):
    from backend_fastapi.scripts import make_admin_hash

    env = tmp_path / ".env"
    env.write_bytes(b"A=1\r\nMAIN_ADMIN_EMAIL_HASH='$old'\r\nB=2\r\nMAIN_ADMIN_EMAIL_HASH=dupe\r\n")
    lines = make_admin_hash.admin_lines("me@example.com", "a long pass phrase")
    make_admin_hash.write_lines(env, lines)
    data = env.read_bytes().decode()
    assert data.count("MAIN_ADMIN_EMAIL_HASH=") == 1
    assert data.count("MAIN_ADMIN_PASSWORD_HASH=") == 1
    assert "$old" not in data and "\n" not in data.replace("\r\n", "")
    assert data.startswith("A=1\r\n") and "B=2\r\n" in data
