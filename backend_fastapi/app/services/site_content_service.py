"""Admin-editable site content: footer text, social links and site-wide
settings (maintenance mode, registration, reader defaults)."""

from __future__ import annotations

import json
import re
import secrets
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import FooterSettings, Setting
from ..utils.sanitizer import strip_all_html

FOOTER_TEXT_KEY = "footer_text"
SITE_SETTINGS_KEY = "site_settings"

_ICON_RE = re.compile(r"^[a-z0-9 _-]{1,60}$")

DEFAULT_SITE_SETTINGS: Dict[str, Any] = {
    "maintenance_mode": False,
    "allow_registration": True,
    "default_reader_mode": "webtoon",
    "auto_scrape_hours": 168,
}
READER_MODES = {"webtoon", "paged", "double", "vertical", "horizontal"}


def _get_json(db: Session, key: str) -> Any:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row is None or not row.value:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return None


def _set_json(db: Session, key: str, value: Any) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    encoded = json.dumps(value)
    if row is None:
        db.add(Setting(key=key, value=encoded))
    else:
        row.value = encoded


# ---------------------------------------------------------------------------
# Social links
# ---------------------------------------------------------------------------


def _safe_url(value: Any, *, allow_mailto: bool = True) -> Optional[str]:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if len(url) > 500:
        return None
    lowered = url.lower()
    if lowered.startswith(("https://", "http://")):
        return url
    if allow_mailto and lowered.startswith("mailto:") and "@" in url:
        return url
    return None


def normalize_social_link(raw: Dict[str, Any], *, link_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    url = _safe_url(raw.get("url"))
    if not url:
        return None
    platform = strip_all_html(str(raw.get("platform") or "custom")).strip().lower()[:30] or "custom"
    title = strip_all_html(str(raw.get("title") or raw.get("label") or platform)).strip()[:60]
    icon = str(raw.get("icon") or "fas fa-link").strip().lower()
    if not _ICON_RE.match(icon):
        icon = "fas fa-link"
    custom_icon = _safe_url(raw.get("custom_icon_url"), allow_mailto=False)
    if custom_icon and not custom_icon.lower().startswith("https://"):
        custom_icon = None
    identifier = str(link_id or raw.get("id") or "").strip()[:40]
    if not re.match(r"^[A-Za-z0-9_-]{1,40}$", identifier):
        identifier = secrets.token_hex(6)
    return {
        "id": identifier,
        "platform": platform,
        "title": title or platform,
        "label": title or platform,
        "url": url,
        "icon": icon,
        "custom_icon_url": custom_icon or "",
    }


def _footer_row(db: Session) -> FooterSettings:
    row = db.query(FooterSettings).first()
    if row is None:
        row = FooterSettings(contact="", terms="", privacy="", socials=[])
        db.add(row)
        db.flush()
    return row


def get_social_links(db: Session) -> List[Dict[str, Any]]:
    row = db.query(FooterSettings).first()
    raw = row.socials if row is not None and isinstance(row.socials, list) else []
    links = []
    for entry in raw:
        if isinstance(entry, dict):
            link = normalize_social_link(entry, link_id=entry.get("id"))
            if link:
                links.append(link)
    return links


def replace_social_links(db: Session, items: List[Any]) -> List[Dict[str, Any]]:
    links: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in items[:30]:
        if not isinstance(entry, dict):
            continue
        link = normalize_social_link(entry)
        if link is None:
            continue
        if link["id"] in seen:
            link["id"] = secrets.token_hex(6)
        seen.add(link["id"])
        links.append(link)
    row = _footer_row(db)
    row.socials = links
    db.commit()
    return links


# ---------------------------------------------------------------------------
# Footer text
# ---------------------------------------------------------------------------


def get_footer_text(db: Session) -> Dict[str, str]:
    data = _get_json(db, FOOTER_TEXT_KEY) or {}
    return {
        "copyright": str(data.get("copyright") or ""),
        "disclaimer": str(data.get("disclaimer") or ""),
    }


def set_footer_text(db: Session, *, copyright: Optional[str], disclaimer: Optional[str]) -> None:
    current = get_footer_text(db)
    if copyright is not None:
        current["copyright"] = strip_all_html(copyright).strip()[:300]
    if disclaimer is not None:
        current["disclaimer"] = strip_all_html(disclaimer).strip()[:1000]
    _set_json(db, FOOTER_TEXT_KEY, current)


# ---------------------------------------------------------------------------
# Site-wide settings
# ---------------------------------------------------------------------------


def get_site_settings(db: Session) -> Dict[str, Any]:
    stored = _get_json(db, SITE_SETTINGS_KEY) or {}
    merged = dict(DEFAULT_SITE_SETTINGS)
    merged.update({k: v for k, v in stored.items() if k in DEFAULT_SITE_SETTINGS})
    return merged


def update_site_settings(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    current = get_site_settings(db)
    if "maintenance_mode" in payload:
        current["maintenance_mode"] = bool(payload["maintenance_mode"])
    if "allow_registration" in payload:
        current["allow_registration"] = bool(payload["allow_registration"])
    mode = payload.get("default_reader_mode")
    if isinstance(mode, str) and mode in READER_MODES:
        current["default_reader_mode"] = mode
    if payload.get("auto_scrape_hours") not in (None, ""):
        try:
            hours = int(payload["auto_scrape_hours"])
        except (TypeError, ValueError):
            hours = current["auto_scrape_hours"]
        current["auto_scrape_hours"] = max(1, min(hours, 24 * 30))
    _set_json(db, SITE_SETTINGS_KEY, current)
    return current


def registration_open(db: Session) -> bool:
    return bool(get_site_settings(db).get("allow_registration", True))


def maintenance_enabled(db: Session) -> bool:
    return bool(get_site_settings(db).get("maintenance_mode", False))
