"""Google sign-in only matches an account by e-mail when Google verified it."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services import oauth_service
from backend_fastapi.app.services.auth_service import get_user_by_email


def test_unverified_google_address_cannot_take_over_an_account(fastapi_client):
    email = f"victim-{uuid.uuid4().hex}@example.com"
    with SessionLocal() as session:
        session.add(User(email=email, is_active=True, role=UserRole.USER, provider="magic_link"))
        session.commit()
        with pytest.raises(oauth_service.OAuthUserError):
            oauth_service.ensure_google_user(
                session, {"email": email, "sub": f"g-{uuid.uuid4().hex}", "email_verified": False}
            )
        victim = get_user_by_email(session, email)
        assert victim.google_sub is None
