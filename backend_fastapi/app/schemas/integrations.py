"""Pydantic schemas for the integration API-key endpoints."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class IntegrationAddRequest(BaseModel):
    """Body of POST /integrations/add.

    ``config``/``payload`` accept whatever shape the selected provider
    needs; ``normalize_provider_payload`` performs the actual per-provider
    validation of that nested value.
    """

    service: str
    config: Optional[Any] = None
    payload: Optional[Any] = None


class IntegrationRemoveRequest(BaseModel):
    """Body of DELETE /integrations/remove."""

    service: str


class IntegrationTestRequest(BaseModel):
    """Body of POST /integrations/test."""

    service: str
