"""Reputation system (SRS 3C): earn, revoke, anti-abuse.

Reputation is never written directly to ``User.reputation`` from a request
handler -- every change goes through ``award``/``revoke_for_ref`` so it is
always backed by an auditable ``ReputationEvent`` (3C.2, 1E.5.3: reputation
can never be set, edited, or purchased).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..models import User
from ..models.community import CommentVote, ReputationEvent
from . import ranking_service
from .notification_service import notify_async

# 3C.1 sources
SOURCE_COMMENT_LIKE = "comment_like"
SOURCE_APPROVED_REPORT = "approved_report"
SOURCE_TRANSLATION_CORRECTION = "translation_correction"
SOURCE_PILL_CLAIM = "pill_claim"

# 3C.2 anti-abuse: a crude brigading/vote-ring guard. A genuine reader votes
# on a handful of comments in a session; an account farming reputation for
# allies votes on many distinct targets in a short window. Past this many
# distinct targets in the window, further votes still register (the count
# the author sees is real) but stop minting reputation for that voter.
VOTE_RING_WINDOW_HOURS = 24
VOTE_RING_DISTINCT_TARGET_CAP = 50


def _eligible(user: Optional[User]) -> bool:
    """3C.2: fake/disposable-flagged accounts accrue no reputation."""

    if user is None:
        return False
    if getattr(user, "flagged_for_review", False):
        return False
    return True


def award(
    db: Session,
    *,
    user_id: int,
    delta: int,
    source: str,
    ref_type: Optional[str] = None,
    ref_id: Optional[object] = None,
) -> Optional[ReputationEvent]:
    """Grant (or, with a negative delta, dock) reputation.

    Auditable via ``ReputationEvent``; notifies the user on realm/stage
    advancement (1I, rank.advancement). Returns ``None`` (no-op) for
    ineligible accounts or a zero delta.
    """

    if not delta:
        return None
    user = db.get(User, user_id)
    if not _eligible(user):
        return None

    before = ranking_service.rank_for(db, user.reputation or 0)

    event = ReputationEvent(
        user_id=user_id,
        delta=delta,
        source=source,
        ref_type=ref_type,
        ref_id=str(ref_id) if ref_id is not None else None,
    )
    db.add(event)
    user.reputation = max(0, (user.reputation or 0) + delta)
    db.commit()
    db.refresh(event)

    after = ranking_service.rank_for(db, user.reputation or 0)
    if after.get("realm_name") and (
        after["realm_name"] != before.get("realm_name")
        or after["stage"] != before.get("stage")
    ):
        notify_async(
            type="rank.advancement",
            user_id=user_id,
            title=f"You've advanced to {after['realm_name']}, Stage {after['stage']}",
            body="Your continued contribution to the community pushed your cultivation rank forward.",
            data={"realm_name": after["realm_name"], "stage": after["stage"]},
            dedup_key=f"rank:{after['realm_name']}:{after['stage']}",
        )
    return event


def revoke_for_comment(db: Session, *, comment_id: int) -> int:
    """Revoke every like-reputation event granted for one comment, across
    all voters (3C.2: "reputation from a removed comment is revoked").

    Each like is stored with ``ref_id=f"{comment_id}:{voter_id}"``, so this
    matches the ``"{comment_id}:"`` prefix rather than one exact ref.
    """

    events = (
        db.query(ReputationEvent)
        .filter(
            ReputationEvent.ref_type == "comment_like_vote",
            ReputationEvent.ref_id.like(f"{comment_id}:%"),
            ReputationEvent.revoked_at.is_(None),
        )
        .all()
    )
    now = datetime.utcnow()
    count = 0
    for event in events:
        user = db.get(User, event.user_id)
        if user is not None:
            user.reputation = max(0, (user.reputation or 0) - event.delta)
        event.revoked_at = now
        count += 1
    if count:
        db.commit()
    return count


def revoke_for_ref(db: Session, *, ref_type: str, ref_id: object) -> int:
    """Reverse every non-revoked event tied to ``(ref_type, ref_id)``.

    3C.2: "reputation from a removed comment is revoked." Returns the count
    of events reversed.
    """

    events = (
        db.query(ReputationEvent)
        .filter(
            ReputationEvent.ref_type == ref_type,
            ReputationEvent.ref_id == str(ref_id),
            ReputationEvent.revoked_at.is_(None),
        )
        .all()
    )
    now = datetime.utcnow()
    count = 0
    for event in events:
        user = db.get(User, event.user_id)
        if user is not None:
            user.reputation = max(0, (user.reputation or 0) - event.delta)
        event.revoked_at = now
        count += 1
    if count:
        db.commit()
    return count


def can_vote(*, voter_id: int, target_author_id: int) -> bool:
    """3C.2: self-voting is impossible."""

    return voter_id != target_author_id


def within_vote_ring_budget(db: Session, *, voter_id: int) -> bool:
    """``True`` if this voter is still under the distinct-target cap for the
    reputation-granting window (3C.2 vote-ring heuristic)."""

    cutoff = datetime.utcnow() - timedelta(hours=VOTE_RING_WINDOW_HOURS)
    distinct_targets = (
        db.query(CommentVote.comment_id)
        .filter(CommentVote.user_id == voter_id, CommentVote.created_at >= cutoff)
        .distinct()
        .count()
    )
    return distinct_targets <= VOTE_RING_DISTINCT_TARGET_CAP


__all__ = [
    "SOURCE_COMMENT_LIKE",
    "SOURCE_APPROVED_REPORT",
    "SOURCE_TRANSLATION_CORRECTION",
    "SOURCE_PILL_CLAIM",
    "award",
    "revoke_for_ref",
    "revoke_for_comment",
    "can_vote",
    "within_vote_ring_budget",
]
