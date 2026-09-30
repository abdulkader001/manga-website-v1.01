"""Admin provider management: multi-provider priority/fallback (SRS 2D).

Gated main-admin-only throughout, extending the resolved D7 decision (SRS
1H.11) that system-wide provider configuration -- credentials or otherwise
-- is Permanent/Main-Administrator territory; Secondary Administrators get
no access to this surface, the same boundary already enforced and tested
for the single-slot ``/admin/system-providers`` endpoints
(test_system_providers.py::test_secondary_admin_cannot_view_or_edit_system_providers).
Distinct from a user's own provider keys (``/user/settings``), which any
signed-in account may configure under their own quota.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import require_main_admin_user
from ...models.provider_management import PROVIDER_SERVICES
from ...services import provider_management_service as pms
from ...services.audit_service import audit_service

router = APIRouter(prefix="/admin/providers", tags=["admin-providers"])


def _vault(request: Request):
    return getattr(request.app.state, "integration_key_vault", None)


def _encrypt(request: Request):
    vault = _vault(request)
    encrypt = getattr(vault, "encrypt", None)
    return encrypt if callable(encrypt) else (lambda v: v)


def _decrypt(request: Request):
    vault = _vault(request)
    decrypt = getattr(vault, "decrypt", None)
    return decrypt if callable(decrypt) else (lambda v: v)


class CreateProviderPayload(BaseModel):
    provider_name: str = Field(..., min_length=1, max_length=120)
    service: str = Field(..., description="ocr | translation | ai")
    provider_id: str = Field(..., min_length=1, max_length=64)
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    website_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    priority: int = Field(default=1, ge=1)


class UpdateProviderPayload(BaseModel):
    provider_name: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    website_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    priority: Optional[int] = Field(default=None, ge=1)
    status: Optional[str] = None


@router.get("", dependencies=[Depends(require_main_admin_user)])
def list_providers(
    service: Optional[str] = None, db: Session = Depends(get_db)
) -> Dict[str, List[Dict[str, Any]]]:
    if service and service not in PROVIDER_SERVICES:
        raise HTTPException(status_code=400, detail="invalid_service")
    records = pms.list_providers(db, service=service)
    return {"providers": [pms.to_dict(r) for r in records]}


@router.post("", dependencies=[Depends(require_main_admin_user)])
def create_provider(
    request: Request,
    payload: CreateProviderPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_main_admin_user),
) -> Dict[str, Any]:
    try:
        record = pms.create_provider(
            db,
            provider_name=payload.provider_name,
            service=payload.service,
            provider_id=payload.provider_id,
            api_url=payload.api_url,
            api_key=payload.api_key,
            website_url=payload.website_url,
            config=payload.config,
            priority=payload.priority,
            created_by_user_id=current_user.id,
            encrypt=_encrypt(request),
        )
    except pms.ProviderManagementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_service.log_action(
        current_user.id,
        "provider.create",
        metadata={"provider_id": record.id, "service": record.service},
    )
    return pms.to_dict(record)


@router.patch("/{provider_pk}", dependencies=[Depends(require_main_admin_user)])
def update_provider(
    request: Request,
    provider_pk: int,
    payload: UpdateProviderPayload,
    db: Session = Depends(get_db),
    current_user=Depends(require_main_admin_user),
) -> Dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    try:
        record = pms.update_provider(
            db, provider_pk, updates, encrypt=_encrypt(request)
        )
    except pms.ProviderManagementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit_service.log_action(
        current_user.id,
        "provider.update",
        metadata={"provider_id": provider_pk, "fields": sorted(updates.keys())},
    )
    return pms.to_dict(record)


@router.delete("/{provider_pk}", dependencies=[Depends(require_main_admin_user)])
def delete_provider(
    provider_pk: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_main_admin_user),
) -> Dict[str, Any]:
    removed = pms.delete_provider(db, provider_pk)
    if not removed:
        raise HTTPException(status_code=404, detail="not_found")
    audit_service.log_action(
        current_user.id,
        "provider.delete",
        metadata={"provider_id": provider_pk},
    )
    return {"status": "ok"}


@router.post("/{provider_pk}/test", dependencies=[Depends(require_main_admin_user)])
def test_provider(
    request: Request,
    provider_pk: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_main_admin_user),
) -> Dict[str, Any]:
    """2D.5: the live test a provider must pass before activation."""

    try:
        result = pms.verify_provider(db, provider_pk, decrypt=_decrypt(request))
    except pms.ProviderManagementError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audit_service.log_action(
        current_user.id,
        "provider.test",
        metadata={"provider_id": provider_pk, "result": result},
    )
    return result


@router.post("/health-check", dependencies=[Depends(require_main_admin_user)])
def health_check_all(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    results = pms.run_health_checks(db, decrypt=_decrypt(request))
    return {"results": results}


__all__ = ["router"]
