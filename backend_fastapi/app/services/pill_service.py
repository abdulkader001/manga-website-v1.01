"""Pills -- the cache-sharing reward (SRS 3C.3).

Minted when a user's shared translation contribution is the ACCEPTED version
under quality tiering (1H.14.8), never for a superseded attempt. Claiming is
a separate, deliberate action from the notification bell so the contributor
actually sees the reward (3C.3.2/3C.3.4) rather than reputation quietly
changing in the background.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..models.community import (
    PILL_REPUTATION_VALUE,
    PILL_STATUS_CLAIMED,
    PILL_STATUS_REVOKED,
    Pill,
)
from . import reputation_service
from .notification_service import notify_async


def mint_if_new(
    db: Session, *, user_id: int, chapter_id: int, target_lang: str
) -> Optional[Pill]:
    """Mint a Pill for this (user, chapter, language) if one doesn't already
    exist (3C.3.3: one Pill per chapter per language per contributing user).

    Safe to call once per accepted page write within the same chapter --
    the unique constraint makes this idempotent even under concurrent
    writers, so callers don't need to pre-check.
    """

    existing = (
        db.query(Pill)
        .filter(
            Pill.user_id == user_id,
            Pill.chapter_id == chapter_id,
            Pill.target_lang == target_lang,
        )
        .one_or_none()
    )
    if existing is not None:
        return None

    pill = Pill(user_id=user_id, chapter_id=chapter_id, target_lang=target_lang)
    db.add(pill)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(pill)

    notify_async(
        type="reputation.pill_earned",
        user_id=user_id,
        title="You earned a Pill for sharing your translation",
        body=(
            f"Your shared translation is now serving every reader of this "
            f"chapter in this language. Claim your Pill to add "
            f"{PILL_REPUTATION_VALUE} reputation."
        ),
        target_type="chapter",
        target_id=chapter_id,
        data={
            "pill_id": pill.id,
            "target_lang": target_lang,
            "reputation": PILL_REPUTATION_VALUE,
        },
        dedup_key=f"pill:{pill.id}",
    )
    return pill


def claim(db: Session, *, user_id: int, pill_id: int) -> Pill:
    pill = db.get(Pill, pill_id)
    if pill is None or pill.user_id != user_id:
        raise ApiError(ErrorCode.NOT_FOUND, "Pill not found.")
    if pill.status == PILL_STATUS_CLAIMED:
        raise ApiError(
            ErrorCode.PILL_ALREADY_CLAIMED, "This Pill has already been claimed."
        )
    if pill.status == PILL_STATUS_REVOKED:
        raise ApiError(ErrorCode.NOT_FOUND, "This Pill is no longer available.")

    pill.status = PILL_STATUS_CLAIMED
    pill.claimed_at = datetime.utcnow()
    db.commit()
    db.refresh(pill)

    reputation_service.award(
        db,
        user_id=user_id,
        delta=PILL_REPUTATION_VALUE,
        source=reputation_service.SOURCE_PILL_CLAIM,
        ref_type="pill",
        ref_id=pill.id,
    )
    return pill


def revoke(db: Session, *, pill_id: int, reason: str) -> Optional[Pill]:
    """Revoke a Pill for fraud only (3C.3.3) -- never for being superseded
    by a later, better translation. Reverses any reputation it granted."""

    pill = db.get(Pill, pill_id)
    if pill is None:
        return None
    was_claimed = pill.status == PILL_STATUS_CLAIMED
    pill.status = PILL_STATUS_REVOKED
    pill.revoked_at = datetime.utcnow()
    pill.revoked_reason = reason
    db.commit()
    db.refresh(pill)

    if was_claimed:
        reputation_service.revoke_for_ref(db, ref_type="pill", ref_id=pill.id)
    return pill


def list_for_user(db: Session, *, user_id: int) -> List[Pill]:
    """Pill history for the user's own profile/activity log (3C.3.3)."""

    return (
        db.query(Pill)
        .filter(Pill.user_id == user_id)
        .order_by(Pill.created_at.desc())
        .all()
    )


def pill_to_dict(pill: Pill) -> dict:
    return {
        "id": pill.id,
        "chapter_id": pill.chapter_id,
        "target_lang": pill.target_lang,
        "status": pill.status,
        "reputation_value": PILL_REPUTATION_VALUE,
        "claimed_at": pill.claimed_at.isoformat() if pill.claimed_at else None,
        "revoked_reason": pill.revoked_reason,
        "created_at": pill.created_at.isoformat() if pill.created_at else None,
    }


__all__ = ["mint_if_new", "claim", "revoke", "list_for_user", "pill_to_dict"]
