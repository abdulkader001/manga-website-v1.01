"""Reading and changing the owner's website-function switches.

Values come from three places (``core.site_functions`` says which): the
``site_functions`` table, the older ``system_settings.login_required`` column
and two keys of the site settings JSON. This module is the only door to all of
them, so the Site Functions page, the public config and the route guards agree.

Guards read the table through a small per-process cache (a few seconds), and the
process that handled a change forgets at once, so a switch takes effect at once
on that process and within ``CACHE_TTL_SECONDS`` on the others.
"""

from __future__ import annotations

import time
from typing import Dict

from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.site_functions import REGISTRY, SIGN_IN_METHODS, FunctionSpec
from ..models import SiteFunction

CACHE_TTL_SECONDS = 5.0
_cache: dict = {"expires": 0.0, "rows": {}}


def invalidate_cache() -> None:
    _cache["expires"] = 0.0


def _table_rows(db: Session) -> Dict[str, bool]:
    now = time.monotonic()
    if now < _cache["expires"]:
        return _cache["rows"]
    try:
        rows = {r.key: bool(r.enabled) for r in db.query(SiteFunction).all()}
    except Exception:  # table missing before the migration: use the defaults
        db.rollback()
        rows = {}
    _cache["rows"] = rows
    _cache["expires"] = now + CACHE_TTL_SECONDS
    return rows


def _require(key: str) -> FunctionSpec:
    spec = REGISTRY.get(key)
    if spec is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Unknown function.", details={"function": key})
    return spec


def _read(db: Session, spec: FunctionSpec) -> bool:
    if spec.store == "login_required":
        from ..dependencies.site_access import login_required

        return login_required(db)
    if spec.store.startswith("site_setting:"):
        from . import site_content_service as content

        name = spec.store.split(":", 1)[1]
        return bool(content.get_site_settings(db).get(name, spec.default))
    return _table_rows(db).get(spec.key, spec.default)


def is_enabled(db: Session, key: str) -> bool:
    return _read(db, _require(key))


def states(db: Session) -> Dict[str, bool]:
    return {key: _read(db, spec) for key, spec in REGISTRY.items()}


def _write(db: Session, spec: FunctionSpec, enabled: bool, actor_id: int | None) -> None:
    if spec.store == "login_required":
        from .system_settings_service import get_or_create_system_settings

        get_or_create_system_settings(db).login_required = enabled
    elif spec.store.startswith("site_setting:"):
        from . import site_content_service as content
        from .maintenance import invalidate_maintenance_cache

        content.update_site_settings(db, {spec.store.split(":", 1)[1]: enabled})
        db.flush()  # the next write in this session must find the row, not add a second
        invalidate_maintenance_cache()
    else:
        row = db.get(SiteFunction, spec.key)
        if row is None:
            db.add(SiteFunction(key=spec.key, enabled=enabled, updated_by=actor_id))
        else:
            row.enabled = enabled
            row.updated_by = actor_id


def set_enabled(db: Session, key: str, enabled: bool, actor_id: int | None) -> Dict[str, bool]:
    """Switch one function. Refuses to leave the site with no way to sign in."""

    spec = _require(key)
    if key in SIGN_IN_METHODS and not enabled:
        others_on = [m for m in SIGN_IN_METHODS if m != key and is_enabled(db, m)]
        if not others_on:
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "At least one sign-in method must stay on, or nobody could sign in.",
                details={"reason": "last_sign_in_method", "function": key},
            )
    _write(db, spec, bool(enabled), actor_id)
    db.commit()
    invalidate_cache()
    return states(db)


def reset_all(db: Session) -> None:
    """Every function back to its default (the recovery command)."""

    for spec in REGISTRY.values():
        _write(db, spec, spec.default, None)
    db.commit()
    invalidate_cache()


def ip_visible_to(db: Session, viewer) -> bool:
    """May ``viewer`` see visitors' IP addresses? The owner always; everyone else
    only while the owner has "Visitor IP addresses are for the owner only" off."""

    from ..dependencies.auth import is_main_admin

    if is_main_admin(viewer):
        return True
    try:
        return not is_enabled(db, "ip_owner_only")
    except Exception:  # an unreadable switch hides the address
        return False


def record_ips(db: Session) -> bool:
    """Should new audit entries and ad clicks keep the visitor's IP address?"""

    try:
        return is_enabled(db, "record_ips")
    except Exception:  # an unreadable switch keeps the default
        return True


def disabled_error(key: str) -> ApiError:
    spec = _require(key)
    return ApiError(
        ErrorCode.FUNCTION_DISABLED,
        f"{spec.label} is switched off on this site.",
        details={"function": key},
    )
