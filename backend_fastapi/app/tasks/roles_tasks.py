"""Daily automatic succession check (runs only when the owner switched it on)."""

from __future__ import annotations

from ..core.celery_app import celery_app
from ..core.db import SessionLocal
from ..services import admin_succession


@celery_app.task(name="backend_fastapi.app.tasks.roles_tasks.succession_check", max_retries=0)
def succession_check():
    with SessionLocal() as db:
        return admin_succession.run(db)
