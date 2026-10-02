"""Donation / support links: public list, main-admin-only editing."""

from __future__ import annotations

from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.powers import require_power
from ...models import User
from ...services import donation_service as donations
from ...utils.audit_logger import log_admin_action

router = APIRouter(tags=["support"])
logger = structlog.get_logger("backend_fastapi.support")


@router.get("/support")
def public_support_links(db: Session = Depends(get_db)) -> Dict[str, Any]:
    return {"links": donations.get_links(db, only_enabled=True)}


@router.get("/admin/support")
def admin_support_links(
    db: Session = Depends(get_db), _: User = Depends(require_power("manage_donations"))
) -> Dict[str, Any]:
    return {"links": donations.get_links(db), **donations.options()}


class SupportLinksPayload(BaseModel):
    links: List[Dict[str, Any]] = Field(default_factory=list)


@router.put("/admin/support")
def update_support_links(
    payload: SupportLinksPayload,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_power("manage_donations")),
) -> Dict[str, Any]:
    try:
        links, changes = donations.replace_links(db, payload.links)
    except donations.DonationError as exc:
        raise ApiError(ErrorCode.VALIDATION_FAILED, str(exc), field="links") from exc

    summary = "; ".join(changes) or "edited labels or visibility"
    log_admin_action(
        db, request, user, "DONATION_LINKS_UPDATE", "settings", "donation_links", "success",
        new_value=summary[:500],
    )
    if changes:
        # Money destinations changed: make sure the owner sees it.
        try:
            from ...services.notification_service import create_notification

            create_notification(
                db,
                type="security.donation_links",
                title="Donation links changed",
                body=f"Donation links were changed: {summary}. If this wasn't you, "
                "check them in Admin Settings and sign out other sessions.",
                user_id=None,
                category="security",
                dedup_key=None,
            )
            db.commit()
        except Exception:  # pragma: no cover - a notice must not undo the save
            db.rollback()
            logger.exception("donation_change_notice_failed")
    return {"links": links, **donations.options()}


__all__ = ["router"]
