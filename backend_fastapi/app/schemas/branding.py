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
    name: Optional[str] = None
    tagline: Optional[str] = None
    logo_url: Optional[str] = None
    homepage_title: Optional[str] = None
    homepage_subtitle: Optional[str] = None


class FooterUpdateRequest(BaseModel):
    """Body of PUT/POST /footer."""

    contact: Optional[str] = None
    terms: Optional[str] = None
    privacy: Optional[str] = None
    socials: Optional[Any] = None
    copyright: Optional[str] = None
    disclaimer: Optional[str] = None
    social_links: Optional[Any] = None
