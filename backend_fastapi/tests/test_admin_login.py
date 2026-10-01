"""Admin sign-in: e-mail + server password + authenticator, no Google/e-mail."""

from __future__ import annotations

import os
import uuid

import pytest
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.core.settings import settings
from backend_fastapi.app.models import User
from backend_fastapi.app.services import admin_second_factor as sf
from backend_fastapi.app.services.auth_service import get_user_by_email
from backend_fastapi.app.utils.endpoint_limiter import async_endpoint_limiter

PASSWORD = "correct horse battery staple"
URL = "/api/v1/auth/admin/login"


def _phc(value: str) -> str:
    kdf = Argon2id(salt=os.urandom(16), length=32, iterations=1, lanes=1, memory_cost=8)
    return kdf.derive_phc_encoded(value.encode("utf-8"))


@pytest.fixture
def admin_email(monkeypatch):
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(settings, "main_admin_email_hash", _phc(email), raising=False)
    monkeypatch.setattr(settings, "main_admin_password_hash", _phc(PASSWORD), raising=False)
    monkeypatch.setattr(settings, "main_admin_auto_promote_enabled", False, raising=False)
    # Each test starts with a fresh guess budget.
    for attr in ("_buckets", "_store", "_hits"):
        store = getattr(async_endpoint_limiter, attr, None)
        if hasattr(store, "clear"):
            store.clear()
    return email


def _user(email):
    with SessionLocal() as session:
        user = get_user_by_email(session, email)
        session.expunge_all()
        return user


def _code(email, offset=0):
    with SessionLocal() as session:
        secret = sf._stored_secret(get_user_by_email(session, email))
    return sf._code_for_step(secret, sf._current_step() + offset)


def _cookies(resp):
    return {
        value.split("=", 1)[0]
        for name, value in resp.headers
        if name.lower() == "set-cookie"
    }


def test_status_says_whether_it_is_set_up(fastapi_client, admin_email, monkeypatch):
    assert fastapi_client.get("/api/v1/auth/admin/status").json() == {"enabled": True}
    monkeypatch.setattr(settings, "main_admin_password_hash", None, raising=False)
    assert fastapi_client.get("/api/v1/auth/admin/status").json() == {"enabled": False}
    resp = fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    assert resp.status_code == 403


def test_wrong_email_or_password_gets_the_same_answer(fastapi_client, admin_email):
    bad_pw = fastapi_client.post(URL, json={"email": admin_email, "password": "nope"})
    bad_mail = fastapi_client.post(URL, json={"email": "thief@example.com", "password": PASSWORD})
    assert bad_pw.status_code == bad_mail.status_code == 401
    assert bad_pw.json()["error"]["message"] == bad_mail.json()["error"]["message"]
    # No account was created or promoted along the way.
    assert _user("thief@example.com") is None


def test_first_sign_in_enrols_the_authenticator_then_makes_the_main_admin(
    fastapi_client, admin_email
):
    first = fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["step"] == "enrol" and body["secret"] and body["otpauth_uri"].startswith("otpauth://")
    assert "access_token_cookie" not in _cookies(first)  # no session before the code

    wrong = fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD, "code": "000000"})
    assert wrong.status_code == 401

    done = fastapi_client.post(
        URL, json={"email": admin_email, "password": PASSWORD, "code": _code(admin_email)}
    )
    assert done.status_code == 200, done.text
    assert done.json() == {"step": "done"}
    assert {"access_token_cookie", "refresh_token_cookie", sf.STEP_UP_COOKIE} <= _cookies(done)
    user = _user(admin_email)
    assert user.is_main_admin and user.totp_enabled

    # Next time: password alone is not enough, it asks for the code.
    again = fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    assert again.json() == {"step": "code"}
    ok = fastapi_client.post(
        URL, json={"email": admin_email, "password": PASSWORD, "code": _code(admin_email, 1)}
    )
    assert ok.json() == {"step": "done"}


def test_a_stolen_inbox_session_cannot_reach_admin_features(fastapi_client, admin_email):
    # The thief signed in through Google/magic link as the admin's account.
    fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD, "code": _code(admin_email)})
    stolen = {"Authorization": f"Bearer {create_access_token(str(_user(admin_email).id))}"}

    # Admin routes ask for the authenticator code...
    resp = fastapi_client.get("/api/v1/admin/config/access", headers=stolen)
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["reason"] == "step_up_required"
    # ...and the authenticator can't be replaced or removed from that session.
    for path, body in (("/api/v1/admin/2fa/setup", None), ("/api/v1/admin/2fa/disable", {"code": "123456"})):
        resp = fastapi_client.post(path, headers=stolen, json=body or {})
        assert resp.status_code == 403
        assert resp.json()["error"]["details"]["reason"] == "managed_by_admin_sign_in"


def test_unenrolled_main_admin_is_held_back_once_admin_sign_in_is_set_up(
    fastapi_client, admin_email
):
    with SessionLocal() as session:
        user = User(
            email=admin_email, is_active=True, provider="magic_link",
            is_main_admin=True, is_secondary_admin=True,
        )
        from backend_fastapi.app.models import UserRole

        user.role = UserRole.PERMANENT
        session.add(user)
        session.commit()
        uid = user.id
    headers = {"Authorization": f"Bearer {create_access_token(str(uid))}"}
    resp = fastapi_client.get("/api/v1/admin/config/access", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["reason"] == "enrolment_required"
