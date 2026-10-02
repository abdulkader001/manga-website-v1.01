"""Server-side admin commands.

Run from the project folder, e.g. ``python -m backend_fastapi.scripts.cli_bootstrap
admin-status`` (inside Docker: ``docker compose exec backend python -m ...``).
Having a shell on the server is the proof of ownership for all of them.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import click

logger = logging.getLogger(__name__)


@contextmanager
def session_scope() -> Iterator:
    # Imported here so `admin-hashes` works before the database or .env exist.
    from backend_fastapi.app.core.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _resolve_user(session, email: str):
    from backend_fastapi.app.models import User
    from backend_fastapi.app.utils.email_crypto import hash_email, normalize_email

    normalized = normalize_email(email)
    if not normalized:
        raise click.ClickException("Give a valid e-mail address")
    user = session.query(User).filter(User.email_hash == hash_email(normalized)).first()
    if user is None:
        raise click.ClickException(f"No account with e-mail {normalized}")
    return user


@click.group()
def cli() -> None:
    """Admin server commands."""


@cli.command("admin-hashes")
def admin_hashes() -> None:
    """Print the two .env lines for the one-time Admin sign-in (/admin-login).

    Same as `python backend_fastapi/scripts/make_admin_hash.py`.
    """

    from backend_fastapi.scripts import make_admin_hash

    make_admin_hash.main([])


@cli.command("admin-status")
def admin_status() -> None:
    """Is the one-time Admin sign-in page open, used up, or broken?"""

    from backend_fastapi.app.core.admin_identity import (
        get_main_admin_email_hash,
        get_main_admin_password_hash,
    )
    from backend_fastapi.app.api.routers.admin_login import setup_page_open, password_used

    email_hash = get_main_admin_email_hash()
    password_hash = get_main_admin_password_hash()
    for name, value in (
        ("MAIN_ADMIN_EMAIL_HASH", email_hash),
        ("MAIN_ADMIN_PASSWORD_HASH", password_hash),
    ):
        if not value:
            click.echo(f"{name}: not set (the server does not see it -- restart after editing .env)")
        elif not value.startswith("$argon2id$"):
            click.echo(f"{name}: DAMAGED -- make new lines with admin-hashes")
        else:
            click.echo(f"{name}: set")
    with session_scope() as session:
        used = password_used(session)
        open_ = setup_page_open(session)
    if open_:
        click.echo("/admin-login: OPEN -- the one-time password has not been used yet.")
    elif used:
        click.echo("/admin-login: CLOSED -- the one-time password was used (page shows 'not found').")
    else:
        click.echo("/admin-login: CLOSED -- not set up (page shows 'not found').")


@cli.command("login-link")
@click.option("--email", type=str, required=True, help="Account to sign in as")
def login_link(email: str) -> None:
    """Print a one-time sign-in link, without sending any e-mail.

    For when Google/Microsoft sign-in or e-mail delivery is not set up (or
    broken). It is a normal session: admin pages still ask for the
    authenticator code. Single use; expires like a normal magic link.
    """

    from backend_fastapi.app.core.settings import get_settings
    from backend_fastapi.app.services.auth_service import (
        create_magic_login_token,
        ensure_magic_link_user,
    )
    from backend_fastapi.app.utils.email_crypto import normalize_email

    normalized = normalize_email(email)
    if not normalized or "@" not in normalized:
        raise click.ClickException("Give a valid e-mail address")
    base = (get_settings().frontend_url or "").rstrip("/")
    with session_scope() as session:
        user = ensure_magic_link_user(session, normalized)
        record, token = create_magic_login_token(session, user)
        expires = record.expires_at
    click.echo("One-time sign-in link (open it in your browser):")
    click.echo(f"{base}/magic-link/{token}" if base else f"/magic-link/{token}")
    click.echo(f"Valid until {expires:%Y-%m-%d %H:%M} UTC, single use.")


@cli.command("reset-2fa")
@click.option("--email", type=str, required=True, help="Admin whose authenticator was lost")
def reset_2fa(email: str) -> None:
    """Remove an account's authenticator (lost phone)."""

    from backend_fastapi.app.services import admin_second_factor

    with session_scope() as session:
        user = _resolve_user(session, email)
        admin_second_factor.disable(session, user)
    click.echo(
        "Authenticator removed. Make a new one-time password (admin-hashes), put it in "
        ".env, restart, and sign in at /admin-login to set up the new phone."
    )


@cli.command("geolock-off")
def geolock_off() -> None:
    """Switch Geolock off (e.g. you blocked the country you are in)."""

    from backend_fastapi.app.services import secret_vault

    with session_scope() as session:
        secret_vault.store(session, "GEOLOCK_ENABLED", "false", actor_id=None)
    click.echo("Geolock is off. Every country can open the site again (within 30 seconds).")


if __name__ == "__main__":
    cli()
