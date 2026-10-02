"""Geolock: the public status check and Admin -> Geolock (main admin only)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.auth import require_main_admin_user
from ...models import User
from ...services import geolock
from ...services import secret_vault as vault
from ...utils.audit_logger import log_admin_action

public_router = APIRouter(prefix="/geo", tags=["geolock"])
router = APIRouter(prefix="/admin/geolock", tags=["geolock"])

ATTRIBUTION = {"text": "IP Geolocation by DB-IP", "url": "https://db-ip.com"}


@public_router.get("/status")
def geo_status() -> Dict[str, Any]:
    """Visitors from a blocked country never get here: the middleware answers 451."""

    return {"blocked": False}


def _overview(request: Request) -> Dict[str, Any]:
    return {
        "enabled": (os.getenv("GEOLOCK_ENABLED") or "").strip().lower() == "true",
        "blocked": sorted(geolock.blocked_countries()),
        "source": geolock.source(),
        "sources": list(geolock.SOURCES),
        "countries": sorted(geolock.ISO_COUNTRIES),
        "database": geolock.database_status(),
        "your_country": geolock.country_for_request(request),
        "attribution": ATTRIBUTION,
    }


@router.get("")
def get_geolock(request: Request, _: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    return _overview(request)


class GeolockPayload(BaseModel):
    enabled: bool
    blocked: List[str] = Field(default_factory=list, max_length=260)
    source: str = "geoip"
    # Saving a list that blocks the admin's own current country needs this.
    confirm_self_block: bool = False


@router.put("")
def save_geolock(
    payload: GeolockPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    try:
        blocked = geolock.clean_countries(payload.blocked)
    except geolock.GeolockError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), field="blocked") from exc
    if payload.source not in geolock.SOURCES:
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Choose geoip or cloudflare.", field="source")
    if payload.enabled and payload.source == "geoip" and not geolock.database_status().get("installed"):
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "Install the country database first (Download or Upload), or the lock can't tell countries apart.",
            details={"reason": "no_database"},
        )
    # Where the admin is, judged the way the new settings will judge them.
    mine = geolock.country_for_request(request, via=payload.source)
    if payload.enabled and mine in blocked and not payload.confirm_self_block:
        raise ApiError(
            ErrorCode.CONFLICT,
            f"This blocks {mine}, where you are now: you would lock yourself out of the site.",
            details={"reason": "would_block_you", "country": mine},
        )

    vault.store(db, "GEOLOCK_COUNTRY_SOURCE", payload.source, actor_id=user.id)
    if blocked:
        vault.store(db, "GEOLOCK_BLOCKED_COUNTRIES", ",".join(blocked), actor_id=user.id)
    else:
        vault.remove(db, "GEOLOCK_BLOCKED_COUNTRIES")
    vault.store(db, "GEOLOCK_ENABLED", "true" if payload.enabled else "false", actor_id=user.id)
    log_admin_action(
        db, request, user, "geolock.update", "geolock", "settings", "success",
        new_value=f"enabled={payload.enabled} blocked={','.join(blocked)} source={payload.source}",
    )
    return _overview(request)


@router.post("/database/update")
def update_database(request: Request, user: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    try:
        geolock.download_dbip()
    except geolock.GeolockError as exc:
        raise ApiError(ErrorCode.BAD_GATEWAY, str(exc), details={"reason": "download_failed"}) from exc
    return _overview(request)


@router.post("/database/upload")
async def upload_database(request: Request, user: User = Depends(require_main_admin_user)) -> Dict[str, Any]:
    """Raw .mmdb body (e.g. MaxMind GeoLite2-Country.mmdb)."""

    folder = geolock.db_path().parent
    folder.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=folder, suffix=".mmdb.part")
    tmp = Path(name)
    written = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                written += len(chunk)
                if written > geolock.MAX_DB_BYTES:
                    raise ApiError(ErrorCode.PAYLOAD_TOO_LARGE, "That file is too large for a country database.")
                fh.write(chunk)
        geolock.install_database(tmp)
    except geolock.GeolockError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)
    return _overview(request)


__all__ = ["router", "public_router"]
