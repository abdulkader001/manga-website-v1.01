"""Donation links: allow-listed platforms, valid crypto addresses, main admin only."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import Notification, User, UserRole
from backend_fastapi.app.services import donation_service as d

BTC = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
ETH = "0x52908400098527886E0F7030069857D2E4169EE7"
TRX = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"


def _headers(role, main):
    with SessionLocal() as s:
        u = User(email=f"d-{uuid.uuid4().hex}@example.com", is_active=True, provider="magic_link",
                 role=role, is_main_admin=main, is_secondary_admin=True)
        s.add(u)
        s.commit()
        return {"Authorization": f"Bearer {create_access_token(str(u.id))}"}


@pytest.mark.parametrize("platform, url", [
    ("kofi", "https://ko-fi.com/mangaworld"),
    ("buymeacoffee", "https://www.buymeacoffee.com/mangaworld"),
    ("paypal", "https://paypal.me/mangaworld"),
    ("github", "https://github.com/sponsors/mangaworld"),
])
def test_real_platform_links_pass(platform, url):
    assert d.normalize({"kind": "link", "platform": platform, "url": url})["url"] == url


@pytest.mark.parametrize("platform, url", [
    ("paypal", "http://paypal.me/x"),                  # not https
    ("paypal", "https://paypal.me.evil.example/x"),    # lookalike host
    ("paypal", "https://evilpaypal.me/x"),             # lookalike host
    ("kofi", "https://user:pw@ko-fi.com/x"),            # credentials
    ("kofi", "https://ko-fi.com:8443/x"),               # port
    ("kofi", "javascript:alert(1)"),
    ("kofi", "https://ko-fi.com/a b"),
    ("github", "https://github.com/someone/repo"),     # not a sponsors page
    ("unknown", "https://example.com/x"),
])
def test_bad_or_lookalike_links_are_refused(platform, url):
    with pytest.raises(d.DonationError):
        d.normalize({"kind": "link", "platform": platform, "url": url})


@pytest.mark.parametrize("network, address", [("btc", BTC), ("eth", ETH), ("trx", TRX)])
def test_valid_addresses_pass(network, address):
    assert d.normalize({"kind": "crypto", "network": network, "address": address})["address"] == address


@pytest.mark.parametrize("network, address", [
    ("btc", ETH), ("eth", BTC), ("eth", ETH[:-1]), ("eth", ETH + " "), ("trx", "T123"),
    ("btc", "bc1q<script>"), ("nope", BTC),
])
def test_wrong_network_or_broken_address_is_refused(network, address):
    with pytest.raises(d.DonationError):
        d.normalize({"kind": "crypto", "network": network, "address": address.rstrip() + ("x" if address.endswith(" ") else "")})


def test_only_the_main_admin_can_change_them_and_the_owner_is_told(fastapi_client):
    body = {"links": [
        {"kind": "link", "platform": "kofi", "url": "https://ko-fi.com/mangaworld"},
        {"kind": "crypto", "network": "btc", "address": BTC, "note": "Thank you!"},
    ]}
    for headers in ({}, _headers(UserRole.USER, False), _headers(UserRole.SECONDARY, False)):
        assert fastapi_client.put("/api/v1/admin/support", headers=headers, json=body).status_code in (401, 403)

    with SessionLocal() as s:
        before = s.query(Notification).filter(Notification.title == "Donation links changed").count()
    resp = fastapi_client.put("/api/v1/admin/support", headers=_headers(UserRole.ADMIN, True), json=body)
    assert resp.status_code == 200, resp.text
    with SessionLocal() as s:
        after = s.query(Notification).filter(Notification.title == "Donation links changed").count()
    assert after == before + 1

    public = fastapi_client.get("/api/v1/support").json()["links"]
    assert [l["kind"] for l in public] == ["link", "crypto"]
    assert public[1]["label"].startswith("Bitcoin")


def test_one_bad_entry_saves_nothing(fastapi_client):
    admin = _headers(UserRole.ADMIN, True)
    fastapi_client.put("/api/v1/admin/support", headers=admin, json={"links": [
        {"kind": "link", "platform": "kofi", "url": "https://ko-fi.com/keep"}]})
    resp = fastapi_client.put("/api/v1/admin/support", headers=admin, json={"links": [
        {"kind": "link", "platform": "kofi", "url": "https://ko-fi.com/new"},
        {"kind": "link", "platform": "paypal", "url": "https://paypa1.me/thief"},
    ]})
    assert resp.status_code == 422
    assert "Entry 2" in resp.json()["error"]["message"]
    assert [l["url"] for l in fastapi_client.get("/api/v1/support").json()["links"]] == ["https://ko-fi.com/keep"]
