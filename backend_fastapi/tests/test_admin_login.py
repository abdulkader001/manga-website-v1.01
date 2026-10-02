"""One-time Admin sign-in: e-mail + server password + authenticator, then gone."""

from __future__ import annotations

import os
import uuid

import pytest
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.core.settings import settings
from backend_fastapi.app.models import SystemSettings, User
from backend_fastapi.app.services import admin_second_factor as sf
from backend_fastapi.app.services.auth_service import get_user_by_email
from backend_fastapi.app.utils.endpoint_limiter import async_endpoint_limiter
from backend_fastapi.scripts.make_admin_hash import PREFIX

PASSWORD = "correct horse battery staple"
URL = "/api/v1/auth/admin/login"


def _phc(value: str) -> str:
    kdf = Argon2id(salt=os.urandom(16), length=32, iterations=1, lanes=1, memory_cost=8)
    return kdf.derive_phc_encoded(value.encode("utf-8"))


def wrap(phc: str) -> str:
    import base64

    return PREFIX + base64.urlsafe_b64encode(phc.encode()).decode().rstrip("=")


@pytest.fixture(autouse=True)
def _forget_used_passwords():
    yield
    # The "a one-time password was used here" marker must not leak into
    # other test files (it makes the authenticator mandatory for main admins).
    with SessionLocal() as session:
        session.query(SystemSettings).update({SystemSettings.admin_setup_password_used: None})
        session.commit()


@pytest.fixture
def admin_email(monkeypatch):
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(settings, "main_admin_email_hash", _phc(email), raising=False)
    monkeypatch.setattr(settings, "main_admin_password_hash", _phc(PASSWORD), raising=False)
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


def test_page_is_open_only_while_set_up(fastapi_client, admin_email, monkeypatch):
    resp = fastapi_client.get("/api/v1/auth/admin/status")
    assert resp.status_code == 200 and resp.json() == {"open": True}
    # No password hash in .env: the page does not exist.
    monkeypatch.setattr(settings, "main_admin_password_hash", None, raising=False)
    assert fastapi_client.get("/api/v1/auth/admin/status").status_code == 404
    resp = fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    assert resp.status_code == 404


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

    # The password was single-use: it is void now, even with a valid code.
    again = fastapi_client.post(
        URL, json={"email": admin_email, "password": PASSWORD, "code": _code(admin_email, 1)}
    )
    assert again.status_code == 404
    # ...and the page is gone: same answer as an address that never existed.
    assert fastapi_client.get("/api/v1/auth/admin/status").status_code == 404


def test_a_new_one_time_password_from_the_server_works_once_again(
    fastapi_client, admin_email, monkeypatch
):
    fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD, "code": _code(admin_email)})

    # Recovery: the owner runs admin-hashes again and puts the new hash in .env.
    monkeypatch.setattr(settings, "main_admin_password_hash", _phc("brand new one-time pass"), raising=False)
    assert fastapi_client.get("/api/v1/auth/admin/status").json() == {"open": True}
    # Authenticator already enrolled: the new password still needs the code.
    step = fastapi_client.post(URL, json={"email": admin_email, "password": "brand new one-time pass"})
    assert step.json() == {"step": "code"}
    done = fastapi_client.post(
        URL,
        json={"email": admin_email, "password": "brand new one-time pass", "code": _code(admin_email, 1)},
    )
    assert done.json() == {"step": "done"}
    reuse = fastapi_client.post(URL, json={"email": admin_email, "password": "brand new one-time pass"})
    assert reuse.status_code == 404


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


def test_removing_the_used_hash_from_env_keeps_admin_features_locked(
    fastapi_client, admin_email, monkeypatch
):
    fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD, "code": _code(admin_email)})
    # The owner deletes both lines from .env after the first sign-in.
    monkeypatch.setattr(settings, "main_admin_password_hash", None, raising=False)
    monkeypatch.setattr(settings, "main_admin_email_hash", None, raising=False)
    stolen = {"Authorization": f"Bearer {create_access_token(str(_user(admin_email).id))}"}
    resp = fastapi_client.get("/api/v1/admin/config/access", headers=stolen)
    assert resp.json()["error"]["details"]["reason"] == "step_up_required"
    resp = fastapi_client.post("/api/v1/admin/2fa/setup", headers=stolen, json={})
    assert resp.json()["error"]["details"]["reason"] == "managed_by_admin_sign_in"


@pytest.mark.parametrize(
    "fmt",
    [
        lambda phc: phc,
        lambda phc: f"'{phc}'",  # quotes kept by `docker run --env-file`
        lambda phc: wrap(phc),  # what make_admin_hash.py prints
        lambda phc: f'"{wrap(phc)}"',
    ],
)
def test_hash_line_formats_all_work(fastapi_client, monkeypatch, fmt):
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(settings, "main_admin_email_hash", fmt(_phc(email)), raising=False)
    monkeypatch.setattr(settings, "main_admin_password_hash", fmt(_phc(PASSWORD)), raising=False)
    # Upper-case e-mail and a stray space/newline from copy-paste are fine.
    resp = fastapi_client.post(URL, json={"email": email.upper(), "password": f" {PASSWORD}\n"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["step"] == "enrol"


def test_make_admin_hash_lines_are_dollar_free_and_accepted(monkeypatch):
    from backend_fastapi.app.core import admin_identity
    from backend_fastapi.scripts import make_admin_hash

    lines = make_admin_hash.admin_lines("Owner@Example.com ", PASSWORD)
    assert all("$" not in line and "'" not in line for line in lines)
    values = dict(line.split("=", 1) for line in lines)
    monkeypatch.setattr(settings, "main_admin_email_hash", values["MAIN_ADMIN_EMAIL_HASH"], raising=False)
    monkeypatch.setattr(settings, "main_admin_password_hash", values["MAIN_ADMIN_PASSWORD_HASH"], raising=False)
    assert admin_identity.is_configured_main_admin_email("owner@example.com")
    assert admin_identity.verify_main_admin_password(PASSWORD)
    assert not admin_identity.verify_main_admin_password(PASSWORD + "x")


def test_a_mangled_hash_turns_the_page_off_instead_of_crashing(fastapi_client, monkeypatch):
    # What Compose leaves of a raw hash pasted without quotes.
    monkeypatch.setattr(settings, "main_admin_email_hash", "=19=65536,t=3,p=4", raising=False)
    monkeypatch.setattr(settings, "main_admin_password_hash", "a2:%%%", raising=False)
    assert fastapi_client.post(URL, json={"email": "a@b.c", "password": PASSWORD}).status_code in {401, 404}


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


def test_owner_email_is_sent_to_the_admin_page_only_while_it_is_open(fastapi_client, admin_email, monkeypatch):
    request = lambda email: fastapi_client.post("/api/v1/auth/request-magic-link", json={"email": email})  # noqa: E731

    # Open: the owner's e-mail goes to /admin-login, no link, no account.
    assert request(admin_email).json()["message"] == "admin_setup"
    assert _user(admin_email) is None
    # Anyone else gets the normal confirmation (and a link).
    other = request(f"reader-{uuid.uuid4().hex[:8]}@example.com").json()
    assert other["message"] == "magic_link_sent"

    # Used: the same e-mail is an ordinary reader sign-in and the page is gone.
    fastapi_client.post(URL, json={"email": admin_email, "password": PASSWORD})
    with SessionLocal() as session:
        row = session.query(SystemSettings).first()
        from backend_fastapi.app.api.routers.admin_login import _fingerprint

        row.admin_setup_password_used = _fingerprint()
        session.commit()
    assert fastapi_client.get("/api/v1/auth/admin/status").status_code == 404
    assert request(admin_email).json()["message"] == "magic_link_sent"
