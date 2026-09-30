"""Pydantic schemas for the branding and footer configuration endpoints."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class BrandingUpdateRequest(BaseModel):
    """Body of PUT/POST /branding.

    ``logo`` and ``socialLinks`` accept whatever shape the client sends;
    ``_store_branding`` sanitizes them (dropping non-string values, ignoring
    malformed entries, etc.) rather than rejecting the request outright.
    """

    logo: Optional[Any] = None
    socialLinks: Optional[Any] = None


class FooterUpdateRequest(BaseModel):
    """Body of PUT/POST /footer."""

    contact: Optional[str] = None
    terms: Optional[str] = None
    privacy: Optional[str] = None
    socials: Optional[Any] = None
