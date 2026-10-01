"""System health probes for parity with the legacy backend."""

from __future__ import annotations

import structlog
import os
from typing import Dict

import psutil
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.settings import settings
from ...dependencies.auth import require_main_admin_user

logger = structlog.get_logger("backend_fastapi.health")

router = APIRouter(
    prefix="/health",
    tags=["health"],
    dependencies=[Depends(require_main_admin_user)],
)


def _google_project_required() -> bool:
    explicit = os.getenv("REQUIRE_GOOGLE_PROJECT_ID")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}

    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    if client_id and client_secret:
        return True

    translation_provider = (settings.default_translation_provider or "").strip().lower()
    if translation_provider.startswith("google"):
        return True

    return False


def _env_checks() -> Dict[str, bool]:
    checks = {
        "SECRET_KEY": bool(os.getenv("SECRET_KEY")),
        "FRONTEND_URL": bool(os.getenv("FRONTEND_URL")),
        "REDIS_URL": bool(os.getenv("REDIS_URL")),
        "DATABASE_URL": bool(os.getenv("DATABASE_URL")),
    }

    if _google_project_required():
        checks["GOOGLE_PROJECT_ID"] = bool(os.getenv("GOOGLE_PROJECT_ID"))
    else:
        checks["GOOGLE_PROJECT_ID"] = True

    return checks


def _configured_warnings() -> list[str]:
    warnings: list[str] = []
    raw = os.getenv("STARTUP_WARNINGS")
    if raw:
        for part in raw.split("|"):
            candidate = part.strip()
            if candidate:
                warnings.append(candidate)

    if _google_project_required():
        google_warning = "GOOGLE_PROJECT_ID environment variable is missing."
        if not os.getenv("GOOGLE_PROJECT_ID") and google_warning not in warnings:
            warnings.append(google_warning)

    return warnings


def _database_ok(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("DB health check failed: %s", exc)
        return False


@router.get("", response_model=None)
async def get_health(db: Session = Depends(get_db)) -> dict[str, object]:
    """Return overall service health state."""

    cpu_percent = psutil.cpu_percent(interval=0.0)
    memory_percent = psutil.virtual_memory().percent
    env_checks = _env_checks()
    warnings = _configured_warnings()
    db_ok = _database_ok(db)

    status = "ok" if all(env_checks.values()) and db_ok else "degraded"
    from .site_admin import health_extras

    extras = health_extras(db) if db_ok else {}
    services = [
        {
            "name": "Database",
            "status": "healthy" if db_ok else "down",
            "explanation": "Primary PostgreSQL database." if db_ok else "Database unreachable.",
        },
        {
            "name": "Configuration",
            "status": "healthy" if all(env_checks.values()) else "degraded",
            "explanation": "; ".join(warnings) or "All required settings present.",
        },
    ]
    return {
        **extras,
        "services": services,
        "status": status,
        "system_status": "Fully Operational" if status == "ok" else "Degraded",
        "db":"ok" if db_ok else "error",
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "env_ok": env_checks,
        "warnings": warnings,
    }


@router.get("/security", response_model=None)
def get_security_status() -> dict[str, object]:
    """Return environment configuration checks for the admin UI."""

    env_checks = {
        "SECRET_KEY": bool(os.getenv("SECRET_KEY")),
        "FRONTEND_URL": bool(os.getenv("FRONTEND_URL")),
    }

    if _google_project_required():
        env_checks["GOOGLE_PROJECT_ID"] = bool(os.getenv("GOOGLE_PROJECT_ID"))
    else:
        env_checks["GOOGLE_PROJECT_ID"] = True
    warnings = _configured_warnings()

    status = "secure" if all(env_checks.values()) else "warnings"
    return {"status": status, "checks": env_checks, "warnings": warnings}


__all__ = ["router"]
