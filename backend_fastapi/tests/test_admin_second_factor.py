"""Admin second factor (roadmap item 15)."""

from __future__ import annotations

import time
import uuid

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services import admin_second_factor as sf


def _admin(main: bool = True) -> tuple[int, dict[str, str]]:
    with SessionLocal() as session:
        user = User(
            email=f"tf-{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=UserRole.ADMIN if main else UserRole.SECONDARY,
            is_main_admin=main,
            is_secondary_admin=not main,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        uid = user.id
    return uid, {"Authorization": f"Bearer {create_access_token(str(uid))}"}


def _code(uid: int, offset: int = 0) -> str:
    with SessionLocal() as session:
        secret = sf._stored_secret(session.get(User, uid))
    return sf._code_for_step(secret, sf._current_step() + offset)


def _step_up(resp) -> str:
    """The step-up cookie value from a response (the test client keeps no jar)."""

    # The stub client returns headers as a list of (name, value) pairs.
    for name, value in resp.headers:
        if name.lower() == "set-cookie" and value.startswith(f"{sf.STEP_UP_COOKIE}="):
            return value.split("=", 1)[1].split(";", 1)[0]
    raise AssertionError("no step-up cookie was set")


def _with_cookie(headers: dict[str, str], token: str) -> dict[str, str]:
    return {**headers, "Cookie": f"{sf.STEP_UP_COOKIE}={token}"}


def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B, SHA-1, T=59 -> 94287082 (last 6 digits: 287082).
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert sf.check_code(secret, "287082", now=59) == 1
    assert sf.check_code(secret, "000000", now=59) is None


def test_code_is_single_use():
    secret = sf.generate_secret()
    now = time.time()
    code = sf._code_for_step(secret, sf._current_step(now))
    step = sf.check_code(secret, code, now=now)
    assert step is not None
    assert sf.check_code(secret, code, now=now, after_step=step) is None


def test_admin_without_second_factor_is_unaffected(fastapi_client):
    _, headers = _admin()
    resp = fastapi_client.get("/api/admin/cache", headers=headers)
    assert resp.status_code == 200


def test_enrol_then_admin_routes_need_step_up(fastapi_client):
    uid, headers = _admin()
    setup = fastapi_client.post("/api/admin/2fa/setup", headers=headers)
    assert setup.status_code == 200
    assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")

    bad = fastapi_client.post("/api/admin/2fa/enable", json={"code": "000000"}, headers=headers)
    assert bad.status_code in (400, 422)

    ok = fastapi_client.post(
        "/api/admin/2fa/enable", json={"code": _code(uid)}, headers=headers
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["unlocked"] is True
    unlocked = _with_cookie(headers, _step_up(ok))

    # Enabling unlocks the browser that did it; one without the cookie is locked.
    assert fastapi_client.get("/api/admin/cache", headers=unlocked).status_code == 200
    locked = fastapi_client.get("/api/admin/cache", headers=headers)
    assert locked.status_code == 403
    assert locked.json()["error"]["details"]["reason"] == "step_up_required"

    # The same code cannot be replayed; the next step's code works.
    replay = fastapi_client.post(
        "/api/admin/2fa/verify", json={"code": _code(uid)}, headers=headers
    )
    assert replay.status_code != 200
    good = fastapi_client.post(
        "/api/admin/2fa/verify", json={"code": _code(uid, 1)}, headers=headers
    )
    assert good.status_code == 200, good.text
    again = _with_cookie(headers, _step_up(good))
    assert fastapi_client.get("/api/admin/cache", headers=again).status_code == 200


def test_step_up_cookie_of_another_admin_is_refused(fastapi_client):
    cookies = {}
    admins = [_admin(), _admin()]
    for uid, headers in admins:
        fastapi_client.post("/api/admin/2fa/setup", headers=headers)
        resp = fastapi_client.post(
            "/api/admin/2fa/enable", json={"code": _code(uid)}, headers=headers
        )
        assert resp.status_code == 200
        cookies[uid] = _step_up(resp)
    (uid_a, _), (uid_b, headers_b) = admins
    stolen = _with_cookie(headers_b, cookies[uid_a])
    assert fastapi_client.get("/api/admin/cache", headers=stolen).status_code == 403


def test_owner_without_an_authenticator_is_held_back_until_they_enrol(fastapi_client, monkeypatch):
    from backend_fastapi.app.core.settings import settings

    monkeypatch.setattr(settings, "main_admin_email_hash", "set", raising=False)
    uid, headers = _admin(main=True)
    resp = fastapi_client.get("/api/admin/cache", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["reason"] == "enrolment_required"
    status = fastapi_client.get("/api/admin/2fa/status", headers=headers).json()
    assert status["required"] and not status["enabled"]
    # The owner enrols right from their Google session: no server visit.
    setup = fastapi_client.post("/api/admin/2fa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    enable = fastapi_client.post(
        "/api/admin/2fa/enable", json={"code": _code(uid)}, headers=headers
    )
    assert enable.status_code == 200, enable.text
    unlocked = _with_cookie(headers, _step_up(enable))
    assert fastapi_client.get("/api/admin/cache", headers=unlocked).status_code == 200


def test_main_admin_is_not_held_back_when_no_owner_email_is_set_up(fastapi_client, monkeypatch):
    from backend_fastapi.app.core.settings import settings

    monkeypatch.setattr(settings, "main_admin_email_hash", None, raising=False)
    _, headers = _admin(main=True)
    assert fastapi_client.get("/api/admin/cache", headers=headers).status_code == 200


def test_non_admin_cannot_use_2fa_endpoints(fastapi_client, auth_headers):
    assert fastapi_client.get("/api/admin/2fa/status", headers=auth_headers).status_code == 403


def test_disable_needs_a_valid_code(fastapi_client):
    uid, headers = _admin()
    fastapi_client.post("/api/admin/2fa/setup", headers=headers)
    fastapi_client.post("/api/admin/2fa/enable", json={"code": _code(uid)}, headers=headers)
    assert (
        fastapi_client.post(
            "/api/admin/2fa/disable", json={"code": "123456"}, headers=headers
        ).status_code
        != 200
    )
    off = fastapi_client.post(
        "/api/admin/2fa/disable", json={"code": _code(uid, 1)}, headers=headers
    )
    assert off.status_code == 200
    assert fastapi_client.get("/api/admin/cache", headers=headers).status_code == 200


def _step_up_cookie_header(resp) -> str:
    for name, value in resp.headers:
        if name.lower() == "set-cookie" and value.startswith(f"{sf.STEP_UP_COOKIE}="):
            return value
    raise AssertionError("no step-up cookie was set")


def test_code_lasts_twelve_hours_by_default(fastapi_client):
    from jose import jwt

    from backend_fastapi.app.core.security import _get_algorithm, _get_secret_key

    assert sf.step_up_hours() == 12
    uid, headers = _admin()
    fastapi_client.post("/api/admin/2fa/setup", headers=headers)
    ok = fastapi_client.post(
        "/api/admin/2fa/enable", json={"code": _code(uid)}, headers=headers
    )
    assert ok.status_code == 200, ok.text
    assert "max-age=43200" in _step_up_cookie_header(ok).lower()
    payload = jwt.decode(_step_up(ok), _get_secret_key(), algorithms=[_get_algorithm()])
    assert 43200 - 60 <= payload["exp"] - time.time() <= 43200 + 60

    status = fastapi_client.get("/api/admin/2fa/status", headers=_with_cookie(headers, _step_up(ok)))
    assert status.json()["valid_hours"] == 12


def test_code_window_follows_the_setting(monkeypatch):
    from backend_fastapi.app.core.settings import settings

    monkeypatch.setattr(settings, "admin_code_valid_hours", 24, raising=False)
    assert sf.step_up_seconds() == 24 * 3600
    # Nonsense falls back to the default; a huge value is capped at a week.
    monkeypatch.setattr(settings, "admin_code_valid_hours", 0, raising=False)
    assert sf.step_up_hours() == sf.DEFAULT_STEP_UP_HOURS
    monkeypatch.setattr(settings, "admin_code_valid_hours", 10_000, raising=False)
    assert sf.step_up_hours() == sf.MAX_STEP_UP_HOURS


def test_admin_screens_code_goes_to_admins_only(fastapi_client):
    from backend_fastapi.app.core.security import create_refresh_token

    path = "/api/admin/2fa/asset-access"
    assert fastapi_client.get(path).status_code == 401

    with SessionLocal() as session:
        reader = User(email=f"r-{uuid.uuid4().hex}@example.com", is_active=True, role=UserRole.USER, provider="magic_link")
        session.add(reader)
        session.commit()
        reader_id = reader.id
    reader_cookie = {"Cookie": f"access_token_cookie={create_access_token(str(reader_id))}"}
    assert fastapi_client.get(path, headers=reader_cookie).status_code == 403

    uid, _ = _admin()
    access = {"Cookie": f"access_token_cookie={create_access_token(str(uid))}"}
    assert fastapi_client.get(path, headers=access).status_code == 204
    # An hour later the access cookie is gone but the refresh cookie still counts.
    refresh = {"Cookie": f"refresh_token_cookie={create_refresh_token(str(uid))}"}
    assert fastapi_client.get(path, headers=refresh).status_code == 204
    # An access token in the refresh slot (or junk) does not.
    wrong = {"Cookie": f"refresh_token_cookie={create_access_token(str(uid))}"}
    assert fastapi_client.get(path, headers=wrong).status_code == 401

