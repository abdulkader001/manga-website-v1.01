"""Shared accessor for the singleton system_settings row (id=1)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import SystemSettings


def get_or_create_system_settings(db: Session) -> SystemSettings:
    """Fetch the singleton system_settings row, creating it if missing."""

    settings = db.query(SystemSettings).first()
    if settings is None:
        settings = SystemSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


__all__ = ["get_or_create_system_settings"]
