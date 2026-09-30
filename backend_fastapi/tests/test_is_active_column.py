"""Regression test ensuring the users.is_active column exists and defaults to true."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from backend_fastapi.app.models import UserRole
from backend_fastapi.app.utils.email_crypto import (
    encrypt_email,
    hash_email,
    normalize_email,
)


def _resolve_database_url() -> str:
    direct_url = os.getenv("DATABASE_URL")
    if direct_url:
        return direct_url

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "postgres")
    host = os.getenv("POSTGRES_HOST", "manga-stack-db")
    port = os.getenv("POSTGRES_PORT", "5432")

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"


@pytest.mark.usefixtures("fastapi_app")
def test_users_has_is_active_column() -> None:
    engine = sa.create_engine(_resolve_database_url(), future=True)
    inspector = sa.inspect(engine)

    assert inspector.has_table("users"), "users table is missing"
    column_names = {column["name"] for column in inspector.get_columns("users")}
    assert "is_active" in column_names, "users.is_active column is missing"

    test_email = "is_active_test@example.com"
    test_google_sub = "codex_dummy_sub"

    normalized_email = normalize_email(test_email)
    assert normalized_email is not None, "normalization should not fail for test email"

    encrypted_email = encrypt_email(normalized_email) or normalized_email
    email_hash = hash_email(normalized_email)
    assert email_hash is not None, "email hashing should not return None"

    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM users WHERE email_hash = :email_hash OR google_sub = :google_sub"
            ),
            {"email_hash": email_hash, "google_sub": test_google_sub},
        )

        conn.execute(
            text(
                """
                INSERT INTO users (email, email_hash, role, provider, username, name, google_sub)
                VALUES (:email, :email_hash, :role, :provider, :username, :name, :google_sub)
                ON CONFLICT (email) DO UPDATE SET google_sub = EXCLUDED.google_sub
                """
            ),
            {
                "email": encrypted_email,
                "email_hash": email_hash,
                # SQLAlchemy's Enum(UserRole) persists the member *name*
                # ("USER"), not its value ("user"). SQLite stores the column
                # as free-text so either spelling was accepted there;
                # PostgreSQL's real enum type rejects anything that is not a
                # declared label.
                "role": UserRole.USER.name,
                "provider": "google",
                "username": "isactivetest",
                "name": "Is Active Test",
                "google_sub": test_google_sub,
            },
        )

        row = conn.execute(
            text("SELECT is_active FROM users WHERE email_hash = :email_hash"),
            {"email_hash": email_hash},
        ).fetchone()

    assert row is not None, "test user not created or selected"
    assert bool(row[0]) is True, "is_active default should be True"

    engine.dispose()
