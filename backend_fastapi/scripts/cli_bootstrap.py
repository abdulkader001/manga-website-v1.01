"""Command-line helpers for admin bootstrap workflows."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

import click

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User
from backend_fastapi.app.services import admin_bootstrap
from backend_fastapi.app.utils.email_crypto import hash_email, normalize_email

logger = logging.getLogger(__name__)


@contextmanager
def session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _resolve_user(session, *, user_id: Optional[int], email: Optional[str]) -> User:
    if user_id is not None:
        user = session.get(User, int(user_id))
        if user is None:
            raise click.ClickException(f"User with id={user_id} not found")
        return user
    if email:
        normalized = normalize_email(email)
        if not normalized:
            raise click.ClickException("Email address could not be normalized")
        email_hash = hash_email(normalized)
        if not email_hash:
            raise click.ClickException("Failed to hash normalized email")
        user = session.query(User).filter(User.email_hash == email_hash).first()
        if user is None:
            raise click.ClickException(f"User with email={normalized} not found")
        return user
    raise click.ClickException("Provide either --user-id or --email")


@click.group()
def cli() -> None:
    """Admin bootstrap utilities."""


@cli.command("issue-admin-token")
@click.option(
    "--user-id", type=int, default=None, help="Associate token with a specific user id"
)
@click.option(
    "--email", type=str, default=None, help="Associate token with a normalized email"
)
@click.option("--ttl", type=int, default=None, help="Override token TTL in seconds")
@click.option(
    "--operator", type=str, default="cli", help="Label recorded in audit logs"
)
def issue_admin_token(
    user_id: Optional[int], email: Optional[str], ttl: Optional[int], operator: str
) -> None:
    """Generate a one-time admin promotion token."""

    issued_to_user_id = None
    with session_scope() as session:
        if user_id is not None or email:
            user = _resolve_user(session, user_id=user_id, email=email)
            issued_to_user_id = user.id
            click.echo(f"Issuing token for user_id={user.id}")
        else:
            click.echo("Issuing token without user binding")

        token = admin_bootstrap.issue_admin_token(
            operator_user_id=None,
            operator_label=operator,
            issued_to_user_id=issued_to_user_id,
            ttl_seconds=ttl,
            session=session,
        )
        click.echo("Admin promotion token:")
        click.echo(token)


@cli.command("promote-user")
@click.option(
    "--token", type=str, required=True, help="Admin promotion token to redeem"
)
@click.option("--user-id", type=int, default=None, help="User id to promote")
@click.option("--email", type=str, default=None, help="User email to promote")
@click.option(
    "--source-ip", type=str, default="cli", help="Source IP recorded in audit log"
)
def promote_user(
    token: str, user_id: Optional[int], email: Optional[str], source_ip: str
) -> None:
    """Redeem an admin token for a specific user."""

    with session_scope() as session:
        user = _resolve_user(session, user_id=user_id, email=email)
        click.echo(f"Redeeming token for user_id={user.id}")
        try:
            admin_bootstrap.redeem_admin_token(
                user, token, source_ip=source_ip, session=session
            )
        except admin_bootstrap.AdminTokenError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo("User promoted to admin.")


if __name__ == "__main__":
    cli()
