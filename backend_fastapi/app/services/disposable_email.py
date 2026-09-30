"""Disposable / temporary email detection (SRS 1D.2).

An account is usable only when backed by a genuinely verified identity, so
disposable and temporary email domains are rejected. The blocklist is
**updatable without a code deploy** (SRS 1D.2.4): it is the union of

  1. a small built-in seed of well-known disposable providers,
  2. the ``DISPOSABLE_EMAIL_DOMAINS`` environment variable (comma-separated),
  3. an optional newline-delimited file at ``DISPOSABLE_EMAIL_BLOCKLIST_FILE``.

Editing the env var or the file (both operational config, not source) updates
the blocklist without shipping code.

For the magic-link path the rejection must be *silent* — the caller returns the
same non-enumerating confirmation screen and simply never sends a link
(SRS 1D.1A.5). For paths where disclosure is acceptable (OAuth account
creation) the caller may surface ``DISPOSABLE_EMAIL_REJECTED``.
"""

from __future__ import annotations

import os
from functools import lru_cache

# A deliberately small seed of common disposable providers. The authoritative,
# frequently-updated list is supplied operationally via env/file (see above).
DEFAULT_DISPOSABLE_DOMAINS: frozenset[str] = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "10minutemail.com",
        "tempmail.com",
        "temp-mail.org",
        "throwawaymail.com",
        "yopmail.com",
        "getnada.com",
        "trashmail.com",
        "sharklasers.com",
        "dispostable.com",
        "maildrop.cc",
        "fakeinbox.com",
        "mintemail.com",
        "mohmal.com",
    }
)


def _env_domains() -> frozenset[str]:
    raw = os.getenv("DISPOSABLE_EMAIL_DOMAINS", "")
    items = {d.strip().lower() for d in raw.split(",") if d.strip()}
    return frozenset(items)


def _file_domains() -> frozenset[str]:
    path = os.getenv("DISPOSABLE_EMAIL_BLOCKLIST_FILE")
    if not path:
        return frozenset()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return frozenset(
                line.strip().lower()
                for line in fh
                if line.strip() and not line.startswith("#")
            )
    except OSError:
        return frozenset()


@lru_cache(maxsize=1)
def _cached_blocklist() -> frozenset[str]:
    return DEFAULT_DISPOSABLE_DOMAINS | _env_domains() | _file_domains()


def reload_blocklist() -> None:
    """Drop the cached blocklist so the next check re-reads env/file."""

    _cached_blocklist.cache_clear()


def _domain_of(email: str) -> str:
    return (
        (email or "").strip().lower().rsplit("@", 1)[-1] if "@" in (email or "") else ""
    )


def is_disposable_domain(email_or_domain: str) -> bool:
    """Return ``True`` if the address (or bare domain) is disposable."""

    value = (email_or_domain or "").strip().lower()
    domain = _domain_of(value) if "@" in value else value
    if not domain:
        return False
    blocklist = _cached_blocklist()
    if domain in blocklist:
        return True
    # Also match subdomains of a blocked apex (e.g. foo.mailinator.com).
    return any(domain.endswith("." + blocked) for blocked in blocklist)


def flag_if_disposable(db, user) -> bool:
    """Defense-in-depth check at login (SRS 1H.7.1 / D5).

    New account creation already refuses a disposable domain outright (the
    magic-link request and OAuth paths both reject before any account
    exists). This covers the residual case: the blocklist gained a domain
    *after* an account was created with it. Never bans outright — D5's
    resolved safe default is flag-for-review, so one shared-network false
    positive (a dormitory, an office) never locks a real person out.
    Every detection is audited immutably, whether or not it is a repeat.
    Returns ``True`` if the account was (re-)flagged this call.
    """

    email = getattr(user, "email_plaintext", None)
    if not email or not is_disposable_domain(email):
        return False

    from datetime import datetime

    from ..models import AdminAuditLog

    already_flagged = bool(getattr(user, "flagged_for_review", False))
    user.flagged_for_review = True
    user.flag_reason = "disposable_email_domain"
    user.flagged_at = datetime.utcnow()
    db.add(user)
    db.add(
        AdminAuditLog(
            user_id=user.id,
            action="DISPOSABLE_EMAIL_FLAGGED",
            metadata_json={
                "target_type": "user",
                "target_id": str(user.id),
                "result": "flagged_for_review",
                "repeat_detection": already_flagged,
            },
            operator="disposable_email_service",
        )
    )
    return True
