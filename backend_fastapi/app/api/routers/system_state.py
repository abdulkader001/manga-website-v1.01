"""System-state routes powered solely by FastAPI services."""

from __future__ import annotations

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import AdminBootstrapState, User
from ...services import admin_bootstrap
from ...services.system_state import get_or_create_system_state
from ...utils.client_ip import resolve_client_ip
from ...utils.email_crypto import allow_email_decryption

logger = structlog.get_logger("backend_fastapi.system_state")

router = APIRouter(prefix="/system", tags=["system"])


class AdminTokenRedeemRequest(BaseModel):
    token: str


def _ensure_bootstrap_state(db: Session) -> AdminBootstrapState:
    state = db.query(AdminBootstrapState).first()
    if state is None:
        state = AdminBootstrapState(id=1, admin_initialized=False)
        db.add(state)
        db.flush()
    return state


@router.post("/admin-token/redeem")
def redeem_admin_token(
    payload: AdminTokenRedeemRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Redeem an admin bootstrap token for the current authenticated user."""

    # F-72: the source IP recorded against a one-time admin-token redemption
    # is security evidence -- it must be the client's, not the proxy's.
    client_host = resolve_client_ip(request)
    if client_host == "unknown":
        client_host = None

    try:
        admin_bootstrap.redeem_admin_token(
            current_user,
            payload.token,
            source_ip=client_host,
            session=db,
        )
    except admin_bootstrap.AdminTokenNotConfigured:
        return JSONResponse(
            status_code=200,
            content={"success": False, "message": "Admin promotion is not configured."},
        )
    except admin_bootstrap.AdminTokenExpired:
        return JSONResponse(
            status_code=200,
            content={"success": False, "message": "Token expired."},
        )
    except admin_bootstrap.AdminTokenRedeemed:
        return JSONResponse(
            status_code=200,
            content={"success": False, "message": "Token already redeemed."},
        )
    except (admin_bootstrap.AdminTokenInvalid, admin_bootstrap.AdminTokenError):
        return JSONResponse(
            status_code=200,
            content={"success": False, "message": "Invalid token."},
        )

    state = get_or_create_system_state(db, for_update=False)
    with allow_email_decryption():
        main_admin_email = state.main_admin_email

    return {
        "success": True,
        "message": "Admin access granted.",
        "system_state": {
            "secret_phrase_used": bool(state.secret_phrase_used),
            "main_admin_email": main_admin_email,
        },
    }


@router.get("/bootstrap")
def bootstrap_state(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return whether the system has been initialized.

    Blind Spot #4: the payload is the minimal "is the system initialized"
    boolean — no timestamps, user ids, or token issuance/redemption details
    that would leak internal operational state.

    F-77: it also requires a session. Its only consumer is the admin-claim
    form, which is useless to anyone who is not logged in (redeeming a token
    already requires a session), so publishing "this instance is unclaimed"
    to anonymous scanners bought nothing and advertised a window.
    """

    state = _ensure_bootstrap_state(db)
    return {"admin_initialized": bool(state.admin_initialized)}


@router.get("/state")
def system_state_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Return the current system state flags.

    This endpoint is public and unauthenticated, so it must never expose
    decrypted PII (e.g. the main admin's email). We only surface a boolean
    indicating whether a main admin has been configured.
    """

    state = get_or_create_system_state(db)
    return {
        "secret_phrase_used": bool(state.secret_phrase_used),
        "admin_configured": bool(state.main_admin_email_hash),
    }


@router.get("/health")
def system_health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Provide a lightweight system health summary."""

    checks: Dict[str, Any] = {}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Database health check failed")
        checks["database"] = False

    state = get_or_create_system_state(db)
    checks["secret_phrase_used"] = bool(state.secret_phrase_used)

    # `ok` is derived before adding the informational-only `admin_configured`
    # flag so that an un-bootstrapped (no main admin) system is not reported as
    # unhealthy. This preserves the prior semantics where the decrypted email
    # string never participated in the health verdict.
    ok = all(value is True for value in checks.values() if isinstance(value, bool))

    # Public, unauthenticated endpoint: never leak decrypted PII. Only report
    # whether a main admin has been configured.
    checks["admin_configured"] = bool(state.main_admin_email_hash)

    return {
        "ok": ok,
        "checks": checks,
    }
