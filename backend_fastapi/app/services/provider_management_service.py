"""Multi-provider admin management (SRS 2D).

Supports many providers per service (ocr/translation/ai) with integer
priority and equal load distribution across providers sharing a level
(2D.3), a status lifecycle gated by a live test before activation (2D.5),
and usage/error statistics (2D.2). This is additive to, and independent
of, the existing single-slot ``ProviderCredentials`` system Part 1 built
(``/admin/system-providers``) -- that endpoint keeps working unchanged;
this is the richer object 2D.2 asks for.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
import structlog
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..models.provider_management import (
    DEFAULT_PRIORITY,
    PROVIDER_SERVICES,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_FAILING,
    STATUS_INACTIVE,
    SystemProviderInstance,
)

logger = structlog.get_logger(__name__)

# A provider is pulled out of rotation after this many consecutive failures
# (2D.3 "a provider marked failing is removed from rotation until it
# recovers"); a single subsequent success brings it back.
CONSECUTIVE_FAILURE_THRESHOLD = 3

LiveTestFn = Callable[
    [SystemProviderInstance, Callable[[Optional[str]], Optional[str]]],
    Tuple[bool, Optional[str]],
]


class ProviderManagementError(ValueError):
    pass


def _identity_decrypt(value: Optional[str]) -> Optional[str]:
    return value


def list_providers(
    db: Session, *, service: Optional[str] = None
) -> List[SystemProviderInstance]:
    query = db.query(SystemProviderInstance)
    if service:
        query = query.filter(SystemProviderInstance.service == service)
    return query.order_by(
        SystemProviderInstance.service,
        SystemProviderInstance.priority,
        SystemProviderInstance.id,
    ).all()


def get_provider(db: Session, provider_pk: int) -> Optional[SystemProviderInstance]:
    return db.get(SystemProviderInstance, provider_pk)


def create_provider(
    db: Session,
    *,
    provider_name: str,
    service: str,
    provider_id: str,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    website_url: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    priority: int = DEFAULT_PRIORITY,
    created_by_user_id: Optional[int] = None,
    encrypt: Callable[[str], str] = lambda v: v,
) -> SystemProviderInstance:
    if service not in PROVIDER_SERVICES:
        raise ProviderManagementError(f"service must be one of {PROVIDER_SERVICES}")
    if not provider_name or not provider_name.strip():
        raise ProviderManagementError("provider_name is required")
    if not provider_id or not provider_id.strip():
        raise ProviderManagementError("provider_id is required")
    if priority < 1:
        raise ProviderManagementError("priority must be a positive integer")

    record = SystemProviderInstance(
        provider_name=provider_name.strip(),
        service=service,
        provider_id=provider_id.strip().lower(),
        api_url=api_url,
        api_key=encrypt(api_key) if api_key else None,
        website_url=website_url,
        config=config or None,
        priority=priority,
        status=STATUS_INACTIVE,
        usage_stats={"requests": 0, "volume": 0, "cost": None},
        error_stats={
            "failure_count": 0,
            "consecutive_failures": 0,
            "failure_rate": 0.0,
            "last_error": None,
            "last_error_at": None,
        },
        created_by_user_id=created_by_user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_provider(
    db: Session,
    provider_pk: int,
    updates: Dict[str, Any],
    *,
    encrypt: Callable[[str], str] = lambda v: v,
) -> SystemProviderInstance:
    record = get_provider(db, provider_pk)
    if record is None:
        raise ProviderManagementError("provider not found")

    if "provider_name" in updates and updates["provider_name"]:
        record.provider_name = str(updates["provider_name"]).strip()
    if "priority" in updates and updates["priority"] is not None:
        priority = int(updates["priority"])
        if priority < 1:
            raise ProviderManagementError("priority must be a positive integer")
        record.priority = priority
    if "api_url" in updates:
        record.api_url = updates["api_url"]
    if "website_url" in updates:
        record.website_url = updates["website_url"]
    if "config" in updates:
        record.config = updates["config"]
    if updates.get("api_key"):
        record.api_key = encrypt(updates["api_key"])

    # 2D.5: "active" is never set directly -- only verify_provider() can
    # move a provider into rotation. Turning a provider off is always safe
    # and needs no verification.
    if "status" in updates and updates["status"] is not None:
        new_status = str(updates["status"]).strip().lower()
        if new_status == STATUS_ACTIVE:
            raise ProviderManagementError(
                "status cannot be set to active directly; use the test/verify action"
            )
        if new_status not in (STATUS_INACTIVE, STATUS_DISABLED):
            raise ProviderManagementError(
                f"status must be one of {STATUS_INACTIVE!r}, {STATUS_DISABLED!r}"
            )
        record.status = new_status

    db.commit()
    db.refresh(record)
    return record


def delete_provider(db: Session, provider_pk: int) -> bool:
    record = get_provider(db, provider_pk)
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True


# --------------------------------------------------------------------------
# 2D.5 live verification
# --------------------------------------------------------------------------


def _live_test_translation_or_ai(
    provider: SystemProviderInstance, decrypt: Callable[[Optional[str]], Optional[str]]
) -> Tuple[bool, Optional[str]]:
    from .translation_service import TranslationProviderError, TranslationService

    cfg: Dict[str, Any] = {
        "provider": provider.provider_id,
        "api_url": provider.api_url,
        "api_key": decrypt(provider.api_key) if provider.api_key else None,
    }
    if isinstance(provider.config, dict):
        if provider.config.get("model"):
            cfg["model"] = provider.config["model"]
        if isinstance(provider.config.get("headers"), dict):
            cfg["headers"] = provider.config["headers"]

    if not cfg.get("api_url"):
        return False, "missing_api_url"

    service = TranslationService(
        default_api_url=cfg.get("api_url"),
        default_api_key=cfg.get("api_key"),
        default_provider_config=cfg,
    )
    try:
        result = service._perform_translation(
            text="hello",
            source_lang="en",
            target_lang="es",
            provider_config=service.default_provider_config,
        )
    except TranslationProviderError as exc:
        return False, str(exc)[:300]
    except Exception as exc:  # pragma: no cover - defensive
        return False, str(exc)[:300]

    if not result or not result.strip():
        return False, "empty_response"
    return True, None


def _live_test_ocr(
    provider: SystemProviderInstance, decrypt: Callable[[Optional[str]], Optional[str]]
) -> Tuple[bool, Optional[str]]:
    if provider.provider_id in ("tesseract_local", "local"):
        return True, None
    if not provider.api_url:
        return False, "missing_api_url"
    try:
        response = requests.head(provider.api_url, timeout=5)
    except Exception as exc:  # pragma: no cover - network dependent
        return False, str(exc)[:300]
    if response.status_code >= 500:
        return False, f"http_{response.status_code}"
    return True, None


def _default_live_test(
    provider: SystemProviderInstance, decrypt: Callable[[Optional[str]], Optional[str]]
) -> Tuple[bool, Optional[str]]:
    if provider.service == "ocr":
        return _live_test_ocr(provider, decrypt)
    return _live_test_translation_or_ai(provider, decrypt)


def verify_provider(
    db: Session,
    provider_pk: int,
    *,
    decrypt: Callable[[Optional[str]], Optional[str]] = _identity_decrypt,
    live_test: Optional[LiveTestFn] = None,
) -> Dict[str, Any]:
    """2D.5: "A provider must pass a live test before it can be
    activated." Runs a real operation and returns a real result."""

    record = get_provider(db, provider_pk)
    if record is None:
        raise ProviderManagementError("provider not found")

    test_fn = live_test or _default_live_test
    ok, error = test_fn(record, decrypt)

    record.last_verified_at = datetime.utcnow()
    record.last_health_check_at = record.last_verified_at
    if ok:
        record.status = STATUS_ACTIVE
        stats = dict(record.error_stats or {})
        stats["consecutive_failures"] = 0
        record.error_stats = stats
    else:
        record.status = STATUS_INACTIVE
        stats = dict(record.error_stats or {})
        stats["last_error"] = error
        stats["last_error_at"] = record.last_verified_at.isoformat()
        record.error_stats = stats

    db.commit()
    db.refresh(record)
    return {"ok": ok, "error": error, "status": record.status}


def run_health_checks(
    db: Session,
    *,
    decrypt: Callable[[Optional[str]], Optional[str]] = _identity_decrypt,
    live_test: Optional[LiveTestFn] = None,
) -> List[Dict[str, Any]]:
    """2D.5: scheduled health checks feeding the dashboard; a provider
    failing health checks is auto-disabled (moved to "failing") and the
    administrator alerted."""

    results: List[Dict[str, Any]] = []
    candidates = (
        db.query(SystemProviderInstance)
        .filter(SystemProviderInstance.status.in_([STATUS_ACTIVE, STATUS_FAILING]))
        .all()
    )
    test_fn = live_test or _default_live_test
    for provider in candidates:
        ok, error = test_fn(provider, decrypt)
        provider.last_health_check_at = datetime.utcnow()
        if ok:
            if provider.status == STATUS_FAILING:
                logger.info(
                    "provider_recovered",
                    provider_id=provider.id,
                    service=provider.service,
                )
            provider.status = STATUS_ACTIVE
            record_success(db, provider.id, commit=False)
        else:
            record_failure(db, provider.id, error, commit=False)
        results.append(
            {"id": provider.id, "ok": ok, "error": error, "status": provider.status}
        )
    db.commit()
    return results


# --------------------------------------------------------------------------
# 2D.3 priority + equal load distribution, 2D.4 fallback usage recording
# --------------------------------------------------------------------------


def select_provider(db: Session, service: str) -> Optional[SystemProviderInstance]:
    """Pick one active provider for ``service``: the lowest priority level
    that has any active provider, distributed EQUALLY (round robin) across
    every provider sharing that level (2D.3)."""

    active = (
        db.query(SystemProviderInstance)
        .filter(
            and_(
                SystemProviderInstance.service == service,
                SystemProviderInstance.status == STATUS_ACTIVE,
            )
        )
        .all()
    )
    if not active:
        return None

    top_priority = min(p.priority for p in active)
    tier = sorted((p for p in active if p.priority == top_priority), key=lambda p: p.id)
    if len(tier) == 1:
        chosen = tier[0]
    else:
        # Round robin on the lowest rotation_counter -- exactly even
        # distribution across every provider sharing the level, and
        # observable per-provider via usage_stats.requests.
        chosen = min(tier, key=lambda p: (p.rotation_counter, p.id))

    chosen.rotation_counter += 1
    stats = dict(chosen.usage_stats or {})
    stats["requests"] = int(stats.get("requests") or 0) + 1
    chosen.usage_stats = stats
    db.commit()
    db.refresh(chosen)
    return chosen


def record_success(db: Session, provider_pk: int, *, commit: bool = True) -> None:
    record = get_provider(db, provider_pk)
    if record is None:
        return
    stats = dict(record.error_stats or {})
    stats["consecutive_failures"] = 0
    record.error_stats = stats
    if record.status == STATUS_FAILING:
        record.status = STATUS_ACTIVE
    if commit:
        db.commit()


def record_failure(
    db: Session, provider_pk: int, error: Optional[str], *, commit: bool = True
) -> None:
    record = get_provider(db, provider_pk)
    if record is None:
        return
    stats = dict(record.error_stats or {})
    failure_count = int(stats.get("failure_count") or 0) + 1
    consecutive = int(stats.get("consecutive_failures") or 0) + 1
    requests_made = int((record.usage_stats or {}).get("requests") or 0)
    stats["failure_count"] = failure_count
    stats["consecutive_failures"] = consecutive
    stats["failure_rate"] = (
        round(failure_count / requests_made, 4) if requests_made else 1.0
    )
    stats["last_error"] = error
    stats["last_error_at"] = datetime.utcnow().isoformat()
    record.error_stats = stats

    if consecutive >= CONSECUTIVE_FAILURE_THRESHOLD and record.status == STATUS_ACTIVE:
        record.status = STATUS_FAILING
        logger.warning(
            "provider_marked_failing",
            provider_id=record.id,
            service=record.service,
            consecutive_failures=consecutive,
        )
    if commit:
        db.commit()


def to_dict(record: SystemProviderInstance) -> Dict[str, Any]:
    return {
        "id": record.id,
        "provider_name": record.provider_name,
        "service": record.service,
        "provider_id": record.provider_id,
        "api_url": record.api_url,
        "has_api_key": bool(record.api_key),
        "website_url": record.website_url,
        "status": record.status,
        "priority": record.priority,
        "usage_stats": record.usage_stats or {},
        "error_stats": record.error_stats or {},
        "last_verified_at": (
            record.last_verified_at.isoformat() if record.last_verified_at else None
        ),
        "last_health_check_at": (
            record.last_health_check_at.isoformat()
            if record.last_health_check_at
            else None
        ),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


__all__ = [
    "ProviderManagementError",
    "list_providers",
    "get_provider",
    "create_provider",
    "update_provider",
    "delete_provider",
    "verify_provider",
    "run_health_checks",
    "select_provider",
    "record_success",
    "record_failure",
    "to_dict",
    "CONSECUTIVE_FAILURE_THRESHOLD",
]
