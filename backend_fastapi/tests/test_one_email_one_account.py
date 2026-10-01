"""One inbox, one account, for life."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services.auth_service import ensure_magic_link_user, get_user_by_email
from backend_fastapi.app.utils.email_crypto import canonical_email
from _support.db_reset import clear_users


@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("John.Doe@Gmail.com", "johndoe@gmail.com"),
        ("johndoe+manga@gmail.com", "johndoe@gmail.com"),
        ("j.o.h.n.d.o.e+x+y@googlemail.com", "johndoe@gmail.com"),
        ("jane+news@outlook.com", "jane@outlook.com"),
        # Dots matter outside Gmail: these can be two different people.
        ("j.doe@outlook.com", "j.doe@outlook.com"),
        ("  Someone@Example.COM ", "someone@example.com"),
    ],
)
def test_canonical_mailbox(raw, canonical):
    assert canonical_email(raw) == canonical


def test_every_spelling_of_a_gmail_inbox_reaches_the_same_account(fastapi_app):
    with SessionLocal() as session:
        clear_users(session)
        first = ensure_magic_link_user(session, "john.doe@gmail.com")
        for alias in ("johndoe@gmail.com", "JOHN.DOE+manga@googlemail.com", "j.ohndoe+1@gmail.com"):
            assert ensure_magic_link_user(session, alias).id == first.id
            assert get_user_by_email(session, alias).id == first.id
        assert session.query(User).count() == 1


def test_the_database_refuses_a_second_account_for_one_inbox(fastapi_app):
    with SessionLocal() as session:
        clear_users(session)
        session.add(User(email="jane@gmail.com", role=UserRole.USER, provider="magic_link"))
        session.commit()
        session.add(User(email="j.a.n.e+2@gmail.com", role=UserRole.USER, provider="google"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_an_accounts_email_can_never_be_changed(fastapi_app):
    with SessionLocal() as session:
        clear_users(session)
        user = User(email="keep@example.com", role=UserRole.USER, provider="magic_link")
        session.add(user)
        session.commit()
        user.email = "KEEP+same@example.com"  # same inbox: allowed (no change)
        with pytest.raises(ValueError):
            user.email = "other@example.com"


def test_a_deleted_account_keeps_its_email(fastapi_app):
    """Deleting an account deactivates it; the inbox can't open a new one."""

    with SessionLocal() as session:
        clear_users(session)
        user = ensure_magic_link_user(session, "gone@gmail.com")
        user.is_active = False
        session.commit()
        again = ensure_magic_link_user(session, "g.one@gmail.com")
        assert again.id == user.id and not again.is_active
        assert session.query(User).count() == 1


def test_different_people_stay_different(fastapi_app):
    with SessionLocal() as session:
        clear_users(session)
        a = ensure_magic_link_user(session, "j.doe@outlook.com")
        b = ensure_magic_link_user(session, "jdoe@outlook.com")
        assert a.id != b.id


def test_password_sign_in_is_gone(fastapi_client):
    resp = fastapi_client.post(
        "/api/v1/auth/login-password", json={"email": "a@example.com", "password": "x" * 12}
    )
    assert resp.status_code in (404, 405)
