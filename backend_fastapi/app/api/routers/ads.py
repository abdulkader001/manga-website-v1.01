"""Public advertisement endpoints for slot listings and click tracking."""

from __future__ import annotations

import structlog
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_optional_user
from ...models import AdClick, AdSlot, User
from ...services import site_functions
from ...services.ad_placements import list_placements
from ...services.ads_config_service import load_ads_config
from ...utils.email_crypto import allow_email_decryption
from ...utils.client_ip import resolve_client_ip

logger = structlog.get_logger("backend_fastapi.routers.ads")

router = APIRouter(prefix="/ads", tags=["ads"])


def _slot_to_dict(slot: AdSlot) -> Dict[str, Any]:
    provider = slot.provider
    return {
        "id": slot.id,
        "name": slot.name,
        "type": slot.type,
        "image_url": slot.image_url,
        "link_url": slot.link_url,
        "alt": slot.alt_text or "Advertisement",
        "provider": provider.name if provider else None,
        "enabled": bool(slot.enabled),
        "html": slot.html_code,
        "metadata": slot.metadata_json or {},
        "slot_group": slot.slot_group,
        "placement": slot.placement,
        "position": slot.position or 0,
        "height_px": slot.height_px,
        "max_width_px": slot.max_width_px,
    }


def _list_slots(db: Session, placement: str | None = None) -> List[Dict[str, Any]]:
    query = db.query(AdSlot)
    if placement:
        query = query.filter(AdSlot.placement == placement)
    slots = query.order_by(AdSlot.position.asc(), AdSlot.id.asc()).all()
    return [_slot_to_dict(slot) for slot in slots]


@router.get("/")
def list_ads_root(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Backwards-compatible endpoint mirroring the legacy Flask response."""

    return _list_slots(db)


@router.get("/slots")
def list_ads_slots(
    placement: str | None = Query(
        default=None, description="Only return slots assigned to this placement"
    ),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Primary endpoint for FE: returns all configured ad slots."""

    return _list_slots(db, placement=placement)


@router.get("/placements")
def list_ad_placements() -> List[Dict[str, Any]]:
    """Expose the placement catalogue so the admin panel can offer real choices."""

    return list_placements()


@router.get("/config")
def fetch_ads_config() -> Dict[str, Any]:
    """Expose the structured ads configuration for public rendering."""

    return load_ads_config()


@router.post("/click/{slot_id}", status_code=status.HTTP_201_CREATED)
def track_click(
    slot_id: int,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Record an advertisement click with optional user attribution."""

    slot = db.get(AdSlot, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="slot_not_found"
        )

    # F-72: attribute the click to the real client, not the reverse proxy.
    ip_address = resolve_client_ip(request)
    if ip_address == "unknown" or not site_functions.record_ips(db):
        ip_address = None

    with allow_email_decryption():
        user_email = user.email if user else None

    click = AdClick(
        slot_id=slot_id,
        user_email=user_email,
        ip_address=ip_address,
    )
    db.add(click)
    db.commit()

    # The address is stored for the owner only; it is not written to the logs.
    logger.info("Recorded ad click for slot_id=%s", slot_id)
    return {"message": "click_recorded", "slot_id": slot_id}


__all__ = ["router"]
