"""Admin -> Site Functions: the owner's on/off switches for the website.

Owner only, and **not delegable**: the routes ask for the main admin
(``require_main_admin_user``, which also asks for the authenticator code) and
there is no catalogue permission for them, so nobody else can be given access,
not even an Admin. Every change is written to the admin audit log.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core import site_functions as registry
from ...core.db import get_db
from ...dependencies.auth import require_main_admin_user
from ...models import User
from ...services import site_functions as functions
from ...utils.audit_logger import log_admin_action

router = APIRouter(prefix="/admin/site-functions", tags=["site-functions"])


def _overview(db: Session) -> Dict[str, Any]:
    states = functions.states(db)
    items = []
    for entry in registry.catalogue():
        items.append({**entry, "enabled": states[entry["key"]]})
    return {"groups": list(registry.GROUPS), "functions": items}


@router.get("")
def list_functions(
    db: Session = Depends(get_db), _: User = Depends(require_main_admin_user)
) -> Dict[str, Any]:
    return _overview(db)


class FunctionPayload(BaseModel):
    enabled: bool


@router.put("/{key}")
def switch_function(
    key: str,
    payload: FunctionPayload,
    request: Request,
    db: Session = Depends(get_db),
    owner: User = Depends(require_main_admin_user),
) -> Dict[str, Any]:
    functions.set_enabled(db, key, payload.enabled, owner.id)
    log_admin_action(
        db, request, owner, "SITE_FUNCTION", "site_function", key, "success",
        new_value="on" if payload.enabled else "off",
    )
    return _overview(db)


__all__ = ["router"]
