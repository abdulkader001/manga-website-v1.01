"""Pydantic schemas for the advertisement slot admin endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class AdSlotFields(BaseModel):
    """Fields shared by create and update requests.

    ``link``/``active``/``html``/``provider`` are legacy aliases the router
    falls back to only when their canonical counterpart
    (``link_url``/``enabled``/``html_code``/``provider_id``/``provider_name``)
    is absent from the request.
    """

    slot_group: Optional[str] = None
    placement: Optional[str] = None
    position: Optional[int] = None
    height_px: Optional[int] = None
    max_width_px: Optional[int] = None
    type: Optional[str] = None
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    link: Optional[str] = None
    alt_text: Optional[str] = None
    html_code: Optional[str] = None
    html: Optional[str] = None
    enabled: Optional[bool] = None
    active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    provider_id: Optional[int] = None
    provider_name: Optional[str] = None
    provider: Optional[str] = None
    # Visual Ads Manager canvas position (kept in the slot's metadata).
    page_target: Optional[str] = None
    canvas_x: Optional[int] = None
    canvas_y: Optional[int] = None
    width_px: Optional[int] = None


class AdSlotCreate(AdSlotFields):
    name: str
    slot_key: str


class AdSlotUpdate(AdSlotFields):
    name: Optional[str] = None
    slot_key: Optional[str] = None
