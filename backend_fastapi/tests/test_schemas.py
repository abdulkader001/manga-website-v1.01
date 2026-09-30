"""Unit tests covering core Pydantic schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend_fastapi.app.models import UserRole
from backend_fastapi.app.schemas import (
    LoginRequest,
    TokenPair,
    UserCreate,
    UserUpdate,
)


def test_login_request_requires_valid_email():
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="secret")


def test_token_pair_defaults_to_bearer_type():
    pair = TokenPair(access_token="token-a", refresh_token="token-b")
    assert pair.token_type == "bearer"


def test_user_create_defaults():
    created = UserCreate(email="user@example.com")
    assert created.role is UserRole.USER


def test_user_update_validates_language_length():
    update = UserUpdate(language="fr")
    assert update.language == "fr"

    with pytest.raises(ValidationError):
        UserUpdate(language="x" * 50)
