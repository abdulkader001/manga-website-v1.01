"""Routes for managing advertisement slots."""

from __future__ import annotations

import structlog
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import require_permission
from ...models import AdSlot, GlobalAdProvider, User
from ...schemas.ad_slots import AdSlotCreate, AdSlotUpdate
from ...services.ad_placements import is_valid_placement
from ...utils.sanitizer import sanitize_ad_html

logger = structlog.get_logger("backend_fastapi.routers.ad_slots")

router = APIRouter(prefix="/ad-slots", tags=["ads"])


def _slot_to_dict(slot: AdSlot) -> dict[str, Any]:
    provider = slot.provider
    return {
        "id": slot.id,
        "name": slot.name,
        "slot_key": slot.slot_key,
        "slot_group": slot.slot_group,
        "placement": slot.placement,
        "position": slot.position or 0,
        "height_px": slot.height_px,
        "max_width_px": slot.max_width_px,
        "type": slot.type,
        "image_url": slot.image_url,
        "link_url": slot.link_url,
        "link": slot.link_url,
        "alt_text": slot.alt_text,
        "enabled": bool(slot.enabled),
        "active": bool(slot.enabled),
        "html_code": slot.html_code,
        "metadata": slot.metadata_json or {},
        "provider_id": slot.provider_id,
        "provider_name": provider.name if provider else None,
        "created_at": slot.created_at.isoformat() if slot.created_at else None,
        "updated_at": slot.updated_at.isoformat() if slot.updated_at else None,
    }


def _find_provider(
    db: Session,
    *,
    provider_id: Optional[int] = None,
    provider_name: Optional[str] = None,
) -> GlobalAdProvider | None:
    if provider_id is not None:
        provider = db.get(GlobalAdProvider, int(provider_id))
        if provider:
            return provider
    if provider_name:
        normalized = provider_name.strip()
        if normalized:
            return (
                db.query(GlobalAdProvider)
                .filter(GlobalAdProvider.name.ilike(normalized))
                .first()
            )
    return None


@router.get("")
def list_ad_slots(
    slot_key: Optional[str] = Query(default=None, description="Filter by slot key"),
    slot_group: Optional[str] = Query(default=None, description="Filter by slot group"),
    placement: Optional[str] = Query(default=None, description="Filter by placement"),
    enabled_only: bool = Query(default=False, description="Return only enabled slots"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List advertisement slots available in the system."""

    query = db.query(AdSlot)
    if slot_key:
        query = query.filter(AdSlot.slot_key == slot_key)
    if slot_group:
        query = query.filter(AdSlot.slot_group == slot_group)
    if placement:
        query = query.filter(AdSlot.placement == placement)
    if enabled_only:
        query = query.filter(AdSlot.enabled.is_(True))
    slots = query.order_by(AdSlot.position.asc(), AdSlot.id.asc()).all()
    return [_slot_to_dict(slot) for slot in slots]


@router.get("/{slot_id}")
def get_ad_slot(slot_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return a single ad slot by identifier."""

    slot = db.get(AdSlot, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ad slot not found"
        )
    return _slot_to_dict(slot)


def _extract_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(data)
    if "link" in payload and "link_url" not in payload:
        payload["link_url"] = payload["link"]
    if "active" in payload and "enabled" not in payload:
        payload["enabled"] = payload["active"]
    canvas = {
        key: payload.pop(key)
        for key in ("page_target", "canvas_x", "canvas_y", "width_px")
        if key in payload
    }
    if canvas:
        metadata = dict(payload.get("metadata") or {})
        metadata.update({k: v for k, v in canvas.items() if v is not None})
        payload["metadata"] = metadata
    return payload


def _validate_placement(data: Dict[str, Any]) -> None:
    """Reject unknown placements so a typo cannot silently hide a slot."""

    if "placement" not in data:
        return
    placement = data.get("placement")
    if placement is not None:
        placement = str(placement).strip()
    if not is_valid_placement(placement):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown placement: {placement}",
        )


def _clean_dimension(value: Any) -> Optional[int]:
    """Normalise a pixel dimension; non-positive values mean "unset"."""

    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Size values must be whole numbers of pixels",
        ) from None
    return number if number > 0 else None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_ad_slot(
    payload: AdSlotCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_ads")),
) -> dict[str, Any]:
    """Create a new advertisement slot."""

    data = _extract_payload(payload.model_dump(exclude_unset=True))
    metadata_payload = data.get("metadata")
    _validate_placement(data)

    name = (data.get("name") or "").strip()
    slot_key = (data.get("slot_key") or "").strip()
    if not name or not slot_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="name and slot_key are required",
        )

    provider = _find_provider(
        db,
        provider_id=data.get("provider_id"),
        provider_name=data.get("provider_name") or data.get("provider"),
    )

    placement = data.get("placement")
    slot = AdSlot(
        name=name,
        slot_key=slot_key,
        slot_group=data.get("slot_group"),
        placement=(placement or "").strip() or None,
        position=int(data.get("position") or 0),
        height_px=_clean_dimension(data.get("height_px")),
        max_width_px=_clean_dimension(data.get("max_width_px")),
        type=data.get("type") or "image",
        image_url=data.get("image_url"),
        link_url=data.get("link_url"),
        alt_text=data.get("alt_text"),
        html_code=sanitize_ad_html(data.get("html_code") or data.get("html")),
        enabled=bool(data.get("enabled", True)),
        metadata_json=metadata_payload or {},
        provider_id=provider.id if provider else data.get("provider_id"),
    )

    db.add(slot)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Failed to create ad slot due to integrity error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot_key already exists"
        ) from exc

    db.refresh(slot)
    return _slot_to_dict(slot)


@router.put("/{slot_id}")
@router.patch("/{slot_id}")
def update_ad_slot(
    slot_id: int,
    payload: AdSlotUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_ads")),
) -> dict[str, Any]:
    """Update an existing advertisement slot."""

    slot = db.get(AdSlot, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ad slot not found"
        )

    data = _extract_payload(payload.model_dump(exclude_unset=True))
    metadata_payload = data.get("metadata") if "metadata" in data else None
    _validate_placement(data)

    updatable_fields = {
        "name",
        "slot_key",
        "slot_group",
        "placement",
        "position",
        "height_px",
        "max_width_px",
        "type",
        "image_url",
        "link_url",
        "alt_text",
        "html_code",
        "html",
        "enabled",
    }

    for field, value in data.items():
        if field not in updatable_fields:
            continue
        if field in ("html", "html_code"):
            slot.html_code = sanitize_ad_html(value) or None
        elif field == "enabled":
            slot.enabled = bool(value)
        elif field == "slot_group":
            slot.slot_group = value or None
        elif field == "placement":
            slot.placement = (value or "").strip() or None
        elif field == "position":
            slot.position = int(value or 0)
        elif field in ("height_px", "max_width_px"):
            setattr(slot, field, _clean_dimension(value))
        elif field == "slot_key" and value:
            slot.slot_key = value.strip()
        elif field == "name" and value:
            slot.name = value.strip()
        else:
            setattr(slot, field, value or None)

    if metadata_payload is not None:
        slot.metadata_json = metadata_payload or {}

    provider_update_requested = (
        "provider_id" in data or "provider" in data or "provider_name" in data
    )
    if provider_update_requested:
        provider = _find_provider(
            db,
            provider_id=data.get("provider_id"),
            provider_name=data.get("provider_name") or data.get("provider"),
        )
        slot.provider_id = provider.id if provider else None

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.warning("Failed to update ad slot %s: %s", slot_id, exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot_key conflict"
        ) from exc

    db.refresh(slot)
    return _slot_to_dict(slot)


@router.delete("/{slot_id}")
def delete_ad_slot(
    slot_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("manage_ads")),
) -> dict[str, Any]:
    """Delete an advertisement slot."""

    slot = db.get(AdSlot, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ad slot not found"
        )

    db.delete(slot)
    db.commit()
    return {"deleted": slot_id}
