"""Audit logging Celery tasks."""

from __future__ import annotations

import structlog
from typing import Any, Dict, Optional

from ..core.celery_app import celery_app
from ..services import audit_service

logger = structlog.get_logger(__name__)


@celery_app.task(name="backend_fastapi.app.tasks.audit_tasks.log_admin_audit")
def log_admin_audit(
    user_id: Optional[int],
    action: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist an admin audit entry."""

    entry_id = audit_service.audit_service.log_action(
        user_id=user_id,
        action=action,
        metadata=metadata,
    )
    return {"entry_id": entry_id}


@celery_app.task(
    name="backend_fastapi.app.tasks.audit_tasks.purge_expired_revoked_tokens"
)
def purge_expired_revoked_tokens() -> Dict[str, Any]:
    """Drop revocation rows for tokens that have since expired on their own.

    Past its own expiry a token is refused by the signature check regardless,
    so the denylist row carries no information. Without this the table only
    ever grows -- one row per logout and per refresh, forever.
    """

    from ..core.db import SessionLocal
    from ..services import token_revocation

    db = SessionLocal()
    try:
        deleted = token_revocation.purge_expired(db)
        logger.info("revoked_tokens_purged", deleted=deleted)
        return {"deleted": deleted}
    finally:
        db.close()


@celery_app.task(name="backend_fastapi.app.tasks.audit_tasks.flush_audit")
def flush_audit() -> Dict[str, str]:
    """Placeholder task for periodic audit maintenance."""

    logger.info("Audit flush task triggered - no-op implementation")
    return {"status": "noop"}


__all__ = ["flush_audit", "log_admin_audit"]
