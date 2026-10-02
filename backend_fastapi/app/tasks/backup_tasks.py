"""Storage & Backups background jobs (maintenance queue).

Never retried automatically: a half-finished restore must not run again on
its own, and a failed backup is reported in the Storage & Backups tab.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from ..core.celery_app import celery_app
from ..services import backup_service

logger = structlog.get_logger("backend_fastapi.tasks.backups")


def _quiet(fn, *args, **kwargs) -> Optional[Dict[str, Any]]:
    try:
        return fn(*args, **kwargs)
    except backup_service.BackupError as exc:
        # Already written to the job status for the admin; no traceback spam.
        logger.warning("backup_task_refused", error=str(exc))
        return None


@celery_app.task(name="backend_fastapi.app.tasks.backup_tasks.run_backup", max_retries=0)
def run_backup(trigger: str = "manual", include_images: Optional[bool] = None, actor_id: Optional[int] = None):
    return _quiet(backup_service.create_backup, trigger=trigger, include_images=include_images, actor_id=actor_id)


@celery_app.task(name="backend_fastapi.app.tasks.backup_tasks.weekly_check", max_retries=0)
def weekly_check():
    """Runs hourly from beat; makes the weekly backup at the chosen day and hour."""

    if backup_service.is_due() and backup_service.status().get("state") != "running":
        return _quiet(backup_service.create_backup, trigger="scheduled")
    return None


@celery_app.task(name="backend_fastapi.app.tasks.backup_tasks.restore_backup", max_retries=0)
def restore_backup(name: str, password_token: Optional[str] = None, actor_id: Optional[int] = None):
    # The password travels through the queue encrypted, never as plain text.
    from ..services.secret_vault import unseal

    password = unseal(password_token) if password_token else None
    return _quiet(backup_service.restore, name, password=password, actor_id=actor_id)


@celery_app.task(name="backend_fastapi.app.tasks.backup_tasks.fetch_remote", max_retries=0)
def fetch_remote(name: str):
    return _quiet(backup_service.fetch_remote, name)
