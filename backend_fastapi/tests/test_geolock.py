"""Geolock: blocked countries get 451, everyone else is untouched."""

from __future__ import annotations

import gzip
import io
import uuid

import pytest
import requests
from starlette.requests import Request

from backend_fastapi.app.core.db import Base, SessionLocal, engine
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import User, UserRole
from backend_fastapi.app.services import geolock

GEO_KEYS = ("GEOLOCK_ENABLED", "GEOLOCK_BLOCKED_COUNTRIES", "GEOLOCK_COUNTRY_SOURCE")


# --------------------------------------------------------------------------
# A real (tiny) MaxMind DB: 1.0.0.0/8 -> JP, nothing else.
# --------------------------------------------------------------------------


def _str(text: str) -> bytes:
    data = text.encode()
    return bytes([(2 << 5) | len(data)]) + data


def _uint(type_code: int, value: int) -> bytes:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big") if value else b""
    if type_code <= 7:
        return bytes([(type_code << 5) | len(raw)]) + raw
    return bytes([len(raw), type_code - 7]) + raw


def _map(items: dict) -> bytes:
    out = bytes([(7 << 5) | len(items)])
    for key, value in items.items():
        out += _str(key) + value
    return out


def make_mmdb() -> bytes:
    node_count = 8
    data = _map({"country": _map({"iso_code": _str("JP")})})
    pointer = node_count + 16  # data section offset 0
    tree = b""
    for bit_index in range(8):  # first octet 1 = 0b00000001
        bit = 1 if bit_index == 7 else 0
        nxt = bit_index + 1
        if bit == 0:
            left, right = nxt, node_count
        else:
            left, right = node_count, pointer
        tree += left.to_bytes(3, "big") + right.to_bytes(3, "big")
    meta = _map(
        {
            "node_count": _uint(6, node_count),
            "record_size": _uint(5, 24),
            "ip_version": _uint(5, 4),
            "database_type": _str("Test-Country"),
            "languages": bytes([1, 4]) + _str("en"),
            "binary_format_major_version": _uint(5, 2),
            "binary_format_minor_version": _uint(5, 0),
            "build_epoch": _uint(9, 1_700_000_000),
            "description": _map({"en": _str("test")}),
        }
    )
    return tree + b"\x00" * 16 + data + b"\xab\xcd\xefMaxMind.com" + meta


@pytest.fixture()
def geo_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOIP_DATABASE_PATH", str(tmp_path / "geoip" / "country.mmdb"))
    for key in GEO_KEYS:
        monkeypatch.delenv(key, raising=False)
    geolock._readers.reset()
    yield tmp_path
    geolock._readers.reset()


def _request(ip: str, headers: dict | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "client": (ip, 1234), "headers": raw, "path": "/", "method": "GET"})


def test_database_lookup_by_address(geo_env):
    candidate = geo_env / "upload.mmdb"
    candidate.write_bytes(make_mmdb())
    status = geolock.install_database(candidate)
    assert status["installed"] and status["type"] == "Test-Country"
    assert geolock.country_for_ip("1.2.3.4") == "JP"
    assert geolock.country_for_ip("8.8.8.8") is None
    assert geolock.country_for_ip("192.168.1.10") is None  # private: never blocked
    assert geolock.country_for_ip("not-an-ip") is None


def test_blocking_decision(geo_env, monkeypatch):
    candidate = geo_env / "upload.mmdb"
    candidate.write_bytes(make_mmdb())
    geolock.install_database(candidate)
    monkeypatch.setenv("GEOLOCK_BLOCKED_COUNTRIES", "jp, cn,ZZ")
    assert geolock.blocked_countries() == {"JP", "CN"}  # unknown codes ignored
    assert not geolock.is_blocked(_request("1.2.3.4"))  # not switched on yet
    monkeypatch.setenv("GEOLOCK_ENABLED", "true")
    assert geolock.is_blocked(_request("1.2.3.4"))
    assert not geolock.is_blocked(_request("8.8.8.8"))
    # A visitor can't fake a country header in database mode.
    assert not geolock.is_blocked(_request("8.8.8.8", {"CF-IPCountry": "JP"}))


def test_cloudflare_header_mode(geo_env, monkeypatch):
    monkeypatch.setenv("GEOLOCK_ENABLED", "true")
    monkeypatch.setenv("GEOLOCK_BLOCKED_COUNTRIES", "US,CA")
    monkeypatch.setenv("GEOLOCK_COUNTRY_SOURCE", "cloudflare")
    assert geolock.is_blocked(_request("10.0.0.1", {"CF-IPCountry": "us"}))
    assert not geolock.is_blocked(_request("10.0.0.1", {"CF-IPCountry": "BD"}))
    assert not geolock.is_blocked(_request("10.0.0.1", {"CF-IPCountry": "XX"}))
    assert not geolock.is_blocked(_request("10.0.0.1"))


def test_bad_database_files_are_refused(geo_env):
    junk = geo_env / "junk.mmdb"
    junk.write_bytes(b"not a database")
    with pytest.raises(geolock.GeolockError, match="not a GeoIP"):
        geolock.install_database(junk)
    assert not geolock.database_status()["installed"]


class _Adapter(requests.adapters.BaseAdapter):
    def __init__(self, routes):
        super().__init__()
        self.routes = routes
        self.seen = []

    def send(self, request, **_kwargs):
        self.seen.append(request.url)
        status, body = next(((s, b) for frag, (s, b) in self.routes.items() if frag in request.url), (404, b""))
        response = requests.Response()
        response.status_code = status
        response.raw = io.BytesIO(body)
        response.request = request
        return response

    def close(self):
        pass


def test_dbip_download_falls_back_to_last_month(geo_env):
    from datetime import datetime, timezone

    adapter = _Adapter({"2026-09.mmdb.gz": (200, gzip.compress(make_mmdb()))})
    session = requests.Session()
    session.mount("https://", adapter)
    status = geolock.download_dbip(now=datetime(2026, 10, 2, tzinfo=timezone.utc), session=session)
    assert status["installed"]
    assert adapter.seen[0].endswith("2026-10.mmdb.gz") and adapter.seen[1].endswith("2026-09.mmdb.gz")
    assert geolock.country_for_ip("1.9.9.9") == "JP"

    nothing = requests.Session()
    nothing.mount("https://", _Adapter({}))
    with pytest.raises(geolock.GeolockError, match="Could not download"):
        geolock.download_dbip(session=nothing)


# --------------------------------------------------------------------------
# Through the app
# --------------------------------------------------------------------------


def test_blocked_visitors_get_451_everywhere_but_health(fastapi_client, geo_env, monkeypatch):
    monkeypatch.setenv("GEOLOCK_ENABLED", "true")
    monkeypatch.setenv("GEOLOCK_BLOCKED_COUNTRIES", "JP")
    monkeypatch.setenv("GEOLOCK_COUNTRY_SOURCE", "cloudflare")
    jp = {"CF-IPCountry": "JP"}
    blocked = fastapi_client.get("/api/v1/geo/status", headers=jp)
    assert blocked.status_code == 451
    assert blocked.json()["error"]["code"] == "REGION_BLOCKED"
    assert fastapi_client.get("/api/v1/manga", headers=jp).status_code == 451
    assert fastapi_client.get("/healthz", headers=jp).status_code != 451
    ok = fastapi_client.get("/api/v1/geo/status", headers={"CF-IPCountry": "BD"})
    assert ok.status_code == 200 and ok.json() == {"blocked": False}
    monkeypatch.setenv("GEOLOCK_ENABLED", "false")
    assert fastapi_client.get("/api/v1/geo/status", headers=jp).status_code == 200


def _user(role: UserRole, main: bool = False) -> dict:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        user = User(
            email=f"geo-{uuid.uuid4().hex}@example.com",
            is_active=True,
            role=role,
            is_main_admin=main,
            is_secondary_admin=role == UserRole.SECONDARY,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.fixture()
def clean_vault():
    yield
    from backend_fastapi.app.services import secret_vault

    with SessionLocal() as session:
        for key in GEO_KEYS:
            secret_vault.remove(session, key)


def test_admin_settings_and_self_lockout_guard(fastapi_client, geo_env, clean_vault):
    admin = _user(UserRole.ADMIN, main=True)
    assert fastapi_client.get("/api/v1/admin/geolock", headers=_user(UserRole.SECONDARY)).status_code == 403
    overview = fastapi_client.get("/api/v1/admin/geolock", headers=admin)
    assert overview.status_code == 200
    assert "JP" in overview.json()["countries"] and overview.json()["database"]["installed"] is False

    no_db = fastapi_client.put("/api/v1/admin/geolock", json={"enabled": True, "blocked": ["CN"]}, headers=admin)
    assert no_db.status_code == 422 and no_db.json()["error"]["details"]["reason"] == "no_database"
    bad = fastapi_client.put("/api/v1/admin/geolock", json={"enabled": False, "blocked": ["QQ"]}, headers=admin)
    assert bad.status_code == 422

    me_jp = {**admin, "CF-IPCountry": "JP"}
    body = {"enabled": True, "blocked": ["JP", "cn"], "source": "cloudflare"}
    guard = fastapi_client.put("/api/v1/admin/geolock", json=body, headers=me_jp)
    assert guard.status_code == 409 and guard.json()["error"]["details"]["reason"] == "would_block_you"

    saved = fastapi_client.put("/api/v1/admin/geolock", json={**body, "blocked": ["CN"]}, headers=me_jp)
    assert saved.status_code == 200, saved.text
    assert saved.json()["blocked"] == ["CN"] and saved.json()["enabled"] is True
    assert fastapi_client.get("/api/v1/geo/status", headers={"CF-IPCountry": "CN"}).status_code == 451

    off = fastapi_client.put("/api/v1/admin/geolock", json={"enabled": False, "blocked": [], "source": "geoip"}, headers=me_jp)
    assert off.status_code == 200
    assert fastapi_client.get("/api/v1/geo/status", headers={"CF-IPCountry": "CN"}).status_code == 200


def test_cli_switches_geolock_off(geo_env, clean_vault, monkeypatch):
    from click.testing import CliRunner

    from backend_fastapi.app.services import secret_vault
    from backend_fastapi.scripts.cli_bootstrap import cli

    with SessionLocal() as session:
        secret_vault.store(session, "GEOLOCK_ENABLED", "true", actor_id=None)
    result = CliRunner().invoke(cli, ["geolock-off"])
    assert result.exit_code == 0, result.output
    with SessionLocal() as session:
        assert secret_vault.current_value(session, "GEOLOCK_ENABLED") == "false"
