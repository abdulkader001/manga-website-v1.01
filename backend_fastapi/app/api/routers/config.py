"""Configuration discovery endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.site_access import login_required

from ...services.provider_registry import ProviderRegistryState

router = APIRouter(prefix="/config", tags=["config"])


def _provider_state(request: Request) -> ProviderRegistryState:
    state = getattr(request.app.state, "provider_registry", None)
    if isinstance(state, ProviderRegistryState):
        return state
    return ProviderRegistryState()


@router.get("/providers")
async def list_providers(request: Request) -> Dict[str, Any]:
    """Public: which services the site can run, and nothing else.

    F-89: no provider names, endpoints, models, key fragments or headers --
    those are on the main-admin-only ``/admin/system-providers``.
    """
    state = _provider_state(request)
    return {
        "availableServices": sorted(state.runtime.keys()),
        "local": {
            "enabled": state.local_ocr_enabled,
            "engine": state.local_ocr_engine,
        },
    }


@router.get("/site-access")
def site_access(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Public: whether visitors must sign in before reading."""
    return {"loginRequired": login_required(db)}


__all__ = ["router"]
