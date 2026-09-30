"""Admin audit logging helpers."""

from __future__ import annotations

import structlog
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from ..core.db import SessionLocal
from ..models import AdminAuditLog

logger = structlog.get_logger(__name__)


class AuditServiceError(Exception):
    """Base exception for audit service issues."""


class AuditServiceValidationError(AuditServiceError):
    """Raised when audit payloads fail validation."""


@contextmanager
def _session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:  # pragma: no cover - defensive rollback
        session.rollback()
        raise
    finally:
        session.close()


class AuditService:
    """Persist audit log entries for administrative actions."""

    def _validate(
        self,
        user_id: Optional[int],
        action: str,
        metadata: Optional[Dict[str, Any]],
        operator: Optional[str],
        source_ip: Optional[str],
    ) -> None:
        if user_id is not None and not isinstance(user_id, int):
            raise AuditServiceValidationError("user_id must be int or None")
        if metadata is not None and not isinstance(metadata, dict):
            raise AuditServiceValidationError("metadata must be dict or None")
        if operator is not None and not isinstance(operator, str):
            raise AuditServiceValidationError("operator must be str or None")
        if source_ip is not None and not isinstance(source_ip, str):
            raise AuditServiceValidationError("source_ip must be str or None")

        if action == "bind_primary_admin_email" and metadata and "phrase" in metadata:
            raise AuditServiceValidationError(
                "audit details for 'bind_primary_admin_email' must not include the phrase",
            )

    def log_action(
        self,
        user_id: Optional[int],
        action: str,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
        *,
        operator: Optional[str] = None,
        source_ip: Optional[str] = None,
    ) -> Optional[int]:
        """Create an audit entry. Returns entry ID or ``None`` on failure."""

        self._validate(
            user_id,
            action,
            metadata,
            operator,
            source_ip,
        )

        log_timestamp = timestamp or datetime.now(timezone.utc)
        safe_metadata = dict(metadata or {})

        try:
            with _session_scope() as session:
                entry = AdminAuditLog(
                    user_id=user_id,
                    action=action,
                    operator=operator,
                    source_ip=source_ip,
                    metadata_json=safe_metadata or None,
                    timestamp=log_timestamp,
                )
                session.add(entry)
                session.flush()
                logger.info(
                    "Audit log entry created: id=%s action=%s", entry.id, action
                )
                return entry.id
        except Exception as exc:  # pragma: no cover - database errors vary
            logger.exception("Failed to create audit log: %s", exc)
            return None


audit_service = AuditService()

__all__ = [
    "audit_service",
    "AuditService",
    "AuditServiceError",
    "AuditServiceValidationError",
]
