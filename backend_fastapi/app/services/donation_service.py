"""Donation / support links (Ko-fi, Buy Me a Coffee, PayPal, crypto ...).

Money goes wherever these point, so they are locked down harder than ordinary
footer links:

* only the main admin can change them (with their authenticator step-up);
* a payment link must be ``https://`` on a known donation platform (no other
  host, no port, no user:password@, no lookalike domain);
* a crypto address must match its network's address format exactly, and the
  page shows the network next to it so nobody sends coins on the wrong chain;
* every change is written to the audit log and announced in the main admin's
  bell, so a swapped address can't go unnoticed.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from ..utils.sanitizer import strip_all_html
from .site_content_service import _get_json, _set_json

DONATION_KEY = "donation_links"
MAX_LINKS = 12

# Platform -> hosts it may live on (the bare domain and its subdomains).
PLATFORMS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "kofi": ("Ko-fi", ("ko-fi.com",)),
    "buymeacoffee": ("Buy Me a Coffee", ("buymeacoffee.com", "buymeacoff.ee")),
    "paypal": ("PayPal", ("paypal.me", "paypal.com")),
    "patreon": ("Patreon", ("patreon.com",)),
    "opencollective": ("Open Collective", ("opencollective.com",)),
    "liberapay": ("Liberapay", ("liberapay.com",)),
    "github": ("GitHub Sponsors", ("github.com",)),
    "stripe": ("Stripe", ("buy.stripe.com", "donate.stripe.com")),
    "boosty": ("Boosty", ("boosty.to",)),
}

# Network -> (label, address pattern). Patterns follow each chain's address
# format; anything else (spaces, wrong length, wrong prefix) is refused.
NETWORKS: Dict[str, Tuple[str, re.Pattern]] = {
    "btc": ("Bitcoin (BTC)", re.compile(r"^(bc1[02-9ac-hj-np-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$")),
    "eth": ("Ethereum / ERC-20 (ETH, USDT, USDC)", re.compile(r"^0x[0-9a-fA-F]{40}$")),
    "bsc": ("BNB Smart Chain / BEP-20", re.compile(r"^0x[0-9a-fA-F]{40}$")),
    "trx": ("Tron / TRC-20 (TRX, USDT)", re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")),
    "sol": ("Solana (SOL, USDC)", re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")),
    "ltc": ("Litecoin (LTC)", re.compile(r"^(ltc1[02-9ac-hj-np-z]{11,71}|[LM3][1-9A-HJ-NP-Za-km-z]{26,33})$")),
    "doge": ("Dogecoin (DOGE)", re.compile(r"^D[1-9A-HJ-NP-Za-km-z]{33}$")),
    "xmr": ("Monero (XMR)", re.compile(r"^[48][1-9A-HJ-NP-Za-km-z]{94}$")),
    "ton": ("TON", re.compile(r"^(EQ|UQ)[A-Za-z0-9_-]{46}$")),
}


class DonationError(ValueError):
    pass


def _host_allowed(host: str, allowed: Tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowed)


def _clean_link_url(platform: str, raw: Any) -> str:
    url = str(raw or "").strip()
    if not url or len(url) > 300 or any(c.isspace() for c in url):
        raise DonationError("Enter the full https:// link from the platform.")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise DonationError("Donation links must start with https://")
    if parts.username or parts.password or parts.port:
        raise DonationError("That link has a login or a port in it; use the platform's plain link.")
    host = (parts.hostname or "").lower().rstrip(".")
    _, allowed = PLATFORMS[platform]
    if not _host_allowed(host, allowed):
        raise DonationError(
            f"A {PLATFORMS[platform][0]} link must be on {', '.join(allowed)}; got {host or 'no address'}."
        )
    if platform == "github" and not parts.path.lower().startswith("/sponsors/"):
        raise DonationError("Use your github.com/sponsors/... page.")
    return url


def _clean_address(network: str, raw: Any) -> str:
    address = str(raw or "").strip()
    label, pattern = NETWORKS[network]
    if not pattern.match(address):
        raise DonationError(f"That is not a valid {label} address. Copy it again from your wallet.")
    return address


def fingerprint(value: str) -> str:
    """Short, stable fingerprint of a link or address, for change notices."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(raw.get("kind") or "link").strip().lower()
    identifier = str(raw.get("id") or "").strip()[:40]
    if not re.match(r"^[A-Za-z0-9_-]{1,40}$", identifier):
        identifier = secrets.token_hex(6)
    note = strip_all_html(str(raw.get("note") or "")).strip()[:120]
    enabled = raw.get("enabled", True) is not False
    if kind == "crypto":
        network = str(raw.get("network") or "").strip().lower()
        if network not in NETWORKS:
            raise DonationError("Pick the coin's network.")
        address = _clean_address(network, raw.get("address"))
        return {
            "id": identifier, "kind": "crypto", "network": network,
            "label": NETWORKS[network][0], "address": address,
            "note": note, "enabled": enabled,
        }
    if kind != "link":
        raise DonationError("Unknown kind of donation entry.")
    platform = str(raw.get("platform") or "").strip().lower()
    if platform not in PLATFORMS:
        raise DonationError("Pick the platform (Ko-fi, Buy Me a Coffee, PayPal ...).")
    url = _clean_link_url(platform, raw.get("url"))
    return {
        "id": identifier, "kind": "link", "platform": platform,
        "label": PLATFORMS[platform][0], "url": url,
        "note": note, "enabled": enabled,
    }


def get_links(db: Session, *, only_enabled: bool = False) -> List[Dict[str, Any]]:
    stored = _get_json(db, DONATION_KEY) or []
    out = []
    for item in stored if isinstance(stored, list) else []:
        try:
            clean = normalize(item)  # re-validated on the way out, too
        except (DonationError, AttributeError, TypeError):
            continue
        if only_enabled and not clean["enabled"]:
            continue
        out.append(clean)
    return out


def _target(item: Dict[str, Any]) -> str:
    return item.get("url") or item.get("address") or ""


def replace_links(db: Session, items: List[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Validate every entry (all or nothing) and store them. Returns the new
    list and a human summary of what changed."""

    if not isinstance(items, list) or len(items) > MAX_LINKS:
        raise DonationError(f"Up to {MAX_LINKS} donation entries.")
    clean: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(items, start=1):
        if not isinstance(raw, dict):
            raise DonationError(f"Entry {index} is not valid.")
        try:
            item = normalize(raw)
        except DonationError as exc:
            raise DonationError(f"Entry {index}: {exc}") from None
        if item["id"] in seen:
            item["id"] = secrets.token_hex(6)
        seen.add(item["id"])
        clean.append(item)

    before = {_target(i): i for i in get_links(db)}
    after = {_target(i): i for i in clean}
    changes = [f"added {after[t]['label']} ({fingerprint(t)})" for t in after if t not in before]
    changes += [f"removed {before[t]['label']} ({fingerprint(t)})" for t in before if t not in after]

    _set_json(db, DONATION_KEY, clean)
    db.commit()
    return clean, changes


def options() -> Dict[str, Any]:
    return {
        "platforms": [{"id": k, "label": v[0], "hosts": list(v[1])} for k, v in PLATFORMS.items()],
        "networks": [{"id": k, "label": v[0]} for k, v in NETWORKS.items()],
    }


__all__ = ["DonationError", "get_links", "normalize", "options", "replace_links"]
