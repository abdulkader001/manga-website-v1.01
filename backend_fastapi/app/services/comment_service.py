"""Native comment system core (SRS 3A): threading, editing, moderation,
voting, reactions, reporting, sorting, and pagination.

Two threads only (1G.12.2, series description page and end of chapter),
target_type in {"manga", "chapter"} with target_id the series/chapter id.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..core.api_errors import ApiError, ErrorCode
from ..models import User
from ..models.community import (
    REPORT_STATUS_ACTIONED,
    REPORT_STATUS_DISMISSED,
    REPORT_STATUS_PENDING,
    REPORT_TARGET_COMMENT,
    CommentReaction,
    CommentVote,
    ContentReport,
)
from ..models.user import MAX_COMMENT_LENGTH, MAX_COMMENT_REPLY_DEPTH, Comment
from ..utils.sanitizer import sanitize_html
from . import comment_translation_service, emoji_catalogue, moderation_service
from . import ranking_service, reputation_service
from .audit_service import audit_service
from .notification_service import notify_async
from .spam_filter import flag_reason

SORT_TOP = "top"
SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"
VALID_SORTS = (SORT_TOP, SORT_NEWEST, SORT_OLDEST)
VALID_TARGET_TYPES = ("manga", "chapter")

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# F-28: resolved reports are kept for this long (moderation history/audit
# trail) before being pruned. Pending reports are never touched here.
REPORT_RETENTION_DAYS = 180


def _validate_target_type(target_type: str) -> str:
    normalized = (target_type or "").strip().lower()
    if normalized not in VALID_TARGET_TYPES:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "target_type must be 'manga' or 'chapter'."
        )
    return normalized


def _is_valid_emoji(db: Session, emoji: str) -> bool:
    if not emoji:
        return False
    if emoji.startswith("custom:"):
        from ..models.community import CustomEmoji

        shortcode = emoji[len("custom:") :]
        return (
            db.query(CustomEmoji).filter(CustomEmoji.shortcode == shortcode).first()
            is not None
        )
    return any(
        entry["emoji"] == emoji for entry in emoji_catalogue.BASE_EMOJI_CATALOGUE
    )


# ---------------------------------------------------------------------------
# Create / edit / delete
# ---------------------------------------------------------------------------


def create_comment(
    db: Session,
    *,
    user: User,
    target_type: str,
    target_id: int,
    content: str,
    parent_id: Optional[int] = None,
    attachment_type: Optional[str] = None,
    attachment_url: Optional[str] = None,
    attachment_metadata: Optional[dict] = None,
) -> Comment:
    moderation_service.assert_can_participate(user)

    target_type = _validate_target_type(target_type)
    cleaned = sanitize_html((content or "").strip())
    if not cleaned:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "Comment cannot be empty.", field="content"
        )
    if len(cleaned) > MAX_COMMENT_LENGTH:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"Comments are limited to {MAX_COMMENT_LENGTH} characters.",
            field="content",
        )
    if attachment_type not in (None, "gif", "meme"):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Invalid attachment_type.")

    depth = 0
    parent: Optional[Comment] = None
    if parent_id is not None:
        parent = db.get(Comment, parent_id)
        if (
            parent is None
            or parent.target_type != target_type
            or parent.target_id != target_id
        ):
            raise ApiError(ErrorCode.NOT_FOUND, "Parent comment not found.")
        # D14: nesting is capped for rendering, but the true parent chain is
        # always exact -- only the stored depth (used for indentation)
        # clamps at the cap.
        depth = min(parent.depth + 1, MAX_COMMENT_REPLY_DEPTH)

    source_language = comment_translation_service.detect_source_language(
        cleaned, hint=getattr(user, "language", None)
    )

    comment = Comment(
        user_id=user.id,
        target_type=target_type,
        target_id=target_id,
        content=cleaned,
        parent_id=parent.id if parent else None,
        depth=depth,
        source_language=source_language,
        attachment_type=attachment_type,
        attachment_url=attachment_url,
        attachment_metadata=attachment_metadata,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    reason = flag_reason(cleaned)
    if reason:
        db.add(
            ContentReport(
                target_type=REPORT_TARGET_COMMENT,
                target_id=comment.id,
                reporter_id=None,
                reason=f"automated_filter:{reason}",
            )
        )
        db.commit()

    return comment


def edit_comment(db: Session, *, user: User, comment_id: int, content: str) -> Comment:
    moderation_service.assert_can_participate(user)
    comment = db.get(Comment, comment_id)
    if comment is None or comment.deleted_at or comment.removed_at:
        raise ApiError(ErrorCode.NOT_FOUND, "Comment not found.")
    if comment.user_id != user.id:
        raise ApiError(ErrorCode.FORBIDDEN, "You can only edit your own comments.")

    cleaned = sanitize_html((content or "").strip())
    if not cleaned:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "Comment cannot be empty.", field="content"
        )
    if len(cleaned) > MAX_COMMENT_LENGTH:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"Comments are limited to {MAX_COMMENT_LENGTH} characters.",
            field="content",
        )

    comment.content = cleaned
    comment.source_language = comment_translation_service.detect_source_language(
        cleaned, hint=getattr(user, "language", None)
    )
    comment.edited_at = datetime.utcnow()
    db.commit()
    db.refresh(comment)
    comment_translation_service.invalidate(db, comment.id)
    return comment


def delete_comment(db: Session, *, user: User, comment_id: int) -> Comment:
    """Author's own soft delete -- content is hidden, thread structure (and
    any replies) stays intact."""

    moderation_service.assert_can_participate(user)
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Comment not found.")
    if comment.user_id != user.id:
        raise ApiError(ErrorCode.FORBIDDEN, "You can only delete your own comments.")

    comment.deleted_at = datetime.utcnow()
    db.commit()
    db.refresh(comment)
    return comment


def moderator_remove_comment(
    db: Session, *, moderator: User, comment_id: int, reason: str
) -> Comment:
    """Moderator removal (1F.4.1), distinct from the author's own delete.
    Revokes any reputation the comment generated for its author (3C.2) and
    notifies the affected user with the reason (1I.3.1)."""

    comment = db.get(Comment, comment_id)
    if comment is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Comment not found.")

    # Chain of command: nobody removes the comment of someone of their own tier or above.
    author = db.get(User, comment.user_id) if comment.user_id else None
    if author is not None:
        from .permissions_service import assert_may_act_on

        assert_may_act_on(moderator, author, "remove the comment of", allow_self=True)

    comment.removed_at = datetime.utcnow()
    comment.removed_by_id = moderator.id
    comment.removed_reason = reason
    db.commit()
    db.refresh(comment)

    reputation_service.revoke_for_comment(db, comment_id=comment.id)

    audit_service.log_action(
        moderator.id,
        "comment.remove",
        metadata={"comment_id": comment.id, "reason": reason},
    )
    notify_async(
        type="moderation.action",
        user_id=comment.user_id,
        title="Your comment was removed",
        body=reason
        or "A moderator removed your comment for violating community guidelines.",
        target_type=comment.target_type,
        target_id=comment.target_id,
        data={"action": "remove_comment", "comment_id": comment.id, "reason": reason},
    )
    return comment


# ---------------------------------------------------------------------------
# Listing: threaded, paginated, sorted (1C.3.6)
# ---------------------------------------------------------------------------


def list_thread(
    db: Session,
    *,
    target_type: str,
    target_id: int,
    sort: str = SORT_TOP,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> Dict[str, Any]:
    target_type = _validate_target_type(target_type)
    sort = sort if sort in VALID_SORTS else SORT_TOP
    limit = max(1, min(MAX_PAGE_SIZE, limit))
    offset = max(0, offset)

    base_query = db.query(Comment).filter(
        Comment.target_type == target_type,
        Comment.target_id == target_id,
        Comment.parent_id.is_(None),
    )
    total = base_query.count()

    if sort == SORT_NEWEST:
        base_query = base_query.order_by(Comment.created_at.desc(), Comment.id.desc())
    elif sort == SORT_OLDEST:
        base_query = base_query.order_by(Comment.created_at.asc(), Comment.id.asc())
    else:
        base_query = base_query.order_by(
            Comment.like_count.desc(), Comment.created_at.desc()
        )

    top_level = (
        base_query.options(joinedload(Comment.user)).offset(offset).limit(limit).all()
    )

    all_comments: List[Comment] = list(top_level)
    frontier = [c.id for c in top_level]
    # Bounded BFS by depth cap -- never a full-table scan of the thread.
    for _ in range(MAX_COMMENT_REPLY_DEPTH + 1):
        if not frontier:
            break
        level = (
            db.query(Comment)
            .options(joinedload(Comment.user))
            .filter(Comment.parent_id.in_(frontier))
            .order_by(Comment.created_at.asc())
            .all()
        )
        if not level:
            break
        all_comments.extend(level)
        frontier = [c.id for c in level]

    return {
        "items": all_comments,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": sort,
    }


def serialize_comment(
    db: Session,
    comment: Comment,
    *,
    viewer: Optional[User] = None,
    target_lang: Optional[str] = None,
    translation_service: Any = None,
) -> Dict[str, Any]:
    hidden = comment.deleted_at is not None or comment.removed_at is not None

    data: Dict[str, Any] = {
        "id": comment.id,
        "user_id": comment.user_id,
        "username": getattr(comment.user, "username", None) if comment.user else None,
        "target_type": comment.target_type,
        "target_id": comment.target_id,
        "parent_id": comment.parent_id,
        "depth": comment.depth or 0,
        "content": None if hidden else comment.content,
        "deleted": comment.deleted_at is not None,
        "removed": comment.removed_at is not None,
        "removed_reason": comment.removed_reason if comment.removed_at else None,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "edited_at": comment.edited_at.isoformat() if comment.edited_at else None,
        "source_language": comment.source_language,
        "like_count": comment.like_count or 0,
        "dislike_count": comment.dislike_count or 0,
        "attachment_type": None if hidden else comment.attachment_type,
        "attachment_url": None if hidden else comment.attachment_url,
        "attachment_metadata": None if hidden else comment.attachment_metadata,
        "translated_content": None,
        "viewer_vote": None,
        "reactions": [],
        "rank": None,
    }

    if comment.user is not None:
        rank = ranking_service.rank_for(db, comment.user.reputation or 0)
        data["rank"] = {
            "realm_name": rank["realm_name"],
            "stage": rank["stage"],
            "color_band": rank["color_band"],
        }

    if not hidden and target_lang and translation_service is not None:
        data["translated_content"] = comment_translation_service.translate_comment(
            db, comment, target_lang, translation_service=translation_service
        )

    reaction_rows = (
        db.query(CommentReaction).filter(CommentReaction.comment_id == comment.id).all()
    )
    counts: Dict[str, int] = {}
    viewer_reacted = set()
    for row in reaction_rows:
        counts[row.emoji] = counts.get(row.emoji, 0) + 1
        if viewer is not None and row.user_id == viewer.id:
            viewer_reacted.add(row.emoji)
    data["reactions"] = [
        {"emoji": emoji, "count": count, "viewer_reacted": emoji in viewer_reacted}
        for emoji, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]

    if viewer is not None:
        vote = (
            db.query(CommentVote)
            .filter(
                CommentVote.comment_id == comment.id, CommentVote.user_id == viewer.id
            )
            .one_or_none()
        )
        if vote is not None:
            data["viewer_vote"] = vote.value

    return data


# ---------------------------------------------------------------------------
# Likes / dislikes
# ---------------------------------------------------------------------------


def toggle_vote(db: Session, *, user: User, comment_id: int, value: int) -> Comment:
    if value not in (1, -1):
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "value must be 1 (like) or -1 (dislike)."
        )
    moderation_service.assert_can_participate(user)

    comment = db.get(Comment, comment_id)
    if comment is None or comment.deleted_at or comment.removed_at:
        raise ApiError(ErrorCode.NOT_FOUND, "Comment not found.")
    if not reputation_service.can_vote(
        voter_id=user.id, target_author_id=comment.user_id
    ):
        raise ApiError(
            ErrorCode.SELF_ACTION_FORBIDDEN, "You cannot vote on your own comment."
        )

    existing = (
        db.query(CommentVote)
        .filter(CommentVote.comment_id == comment_id, CommentVote.user_id == user.id)
        .one_or_none()
    )
    # Captured before any mutation below -- ``existing`` gets deleted or its
    # ``.value`` overwritten in place, so this is the only reliable record of
    # what the vote *was* for the reputation adjustment that follows.
    previous_value: Optional[int] = existing.value if existing is not None else None
    ref_id = f"{comment_id}:{user.id}"

    if existing is None:
        db.add(CommentVote(comment_id=comment_id, user_id=user.id, value=value))
        _bump_vote_count(comment, value, +1)
    elif existing.value == value:
        # Toggle off.
        db.delete(existing)
        _bump_vote_count(comment, value, -1)
    else:
        # Flip like<->dislike.
        _bump_vote_count(comment, existing.value, -1)
        _bump_vote_count(comment, value, +1)
        existing.value = value

    db.commit()
    db.refresh(comment)

    def _award_like() -> None:
        if reputation_service.within_vote_ring_budget(db, voter_id=user.id):
            reputation_service.award(
                db,
                user_id=comment.user_id,
                delta=1,
                source=reputation_service.SOURCE_COMMENT_LIKE,
                ref_type="comment_like_vote",
                ref_id=ref_id,
            )

    if previous_value is None:
        if value == 1:
            _award_like()  # brand-new like; a brand-new dislike earns nothing
    elif previous_value == value:
        if previous_value == 1:
            # Toggling the same like off again -- withdraw it.
            reputation_service.revoke_for_ref(
                db, ref_type="comment_like_vote", ref_id=ref_id
            )
    else:
        if previous_value == 1:
            # Was a like, flipped to a dislike -- withdraw it.
            reputation_service.revoke_for_ref(
                db, ref_type="comment_like_vote", ref_id=ref_id
            )
        else:
            # Was a dislike, flipped to a like -- counts as a fresh like.
            _award_like()

    return comment


def _bump_vote_count(comment: Comment, value: int, delta: int) -> None:
    if value == 1:
        comment.like_count = max(0, (comment.like_count or 0) + delta)
    else:
        comment.dislike_count = max(0, (comment.dislike_count or 0) + delta)


# ---------------------------------------------------------------------------
# Emoji reactions
# ---------------------------------------------------------------------------


def toggle_reaction(db: Session, *, user: User, comment_id: int, emoji: str) -> Comment:
    moderation_service.assert_can_participate(user)
    comment = db.get(Comment, comment_id)
    if comment is None or comment.deleted_at or comment.removed_at:
        raise ApiError(ErrorCode.NOT_FOUND, "Comment not found.")
    if not _is_valid_emoji(db, emoji):
        raise ApiError(ErrorCode.VALIDATION_FAILED, "Unknown emoji.")

    existing = (
        db.query(CommentReaction)
        .filter(
            CommentReaction.comment_id == comment_id,
            CommentReaction.user_id == user.id,
            CommentReaction.emoji == emoji,
        )
        .one_or_none()
    )
    if existing is not None:
        db.delete(existing)
        db.commit()
        return comment

    db.add(CommentReaction(comment_id=comment_id, user_id=user.id, emoji=emoji))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # Concurrent double-click; already reacted.
    if comment.user_id != user.id:
        notify_async(
            type="comment.reaction",
            user_id=comment.user_id,
            title="Someone reacted to your comment",
            body=f"{emoji} on your comment",
            target_type=comment.target_type,
            target_id=comment.target_id,
            data={"comment_id": comment.id, "emoji": emoji},
            dedup_key=f"reaction:{comment.id}",
        )
    return comment


# ---------------------------------------------------------------------------
# Reporting (feeds the moderator queue, 1F.4.1)
# ---------------------------------------------------------------------------


def report_comment(
    db: Session, *, user: User, comment_id: int, reason: Optional[str]
) -> ContentReport:
    moderation_service.assert_can_participate(user)
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Comment not found.")

    report = ContentReport(
        target_type=REPORT_TARGET_COMMENT,
        target_id=comment_id,
        reporter_id=user.id,
        reason=(reason or "").strip()[:255] or None,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def list_reports(
    db: Session, *, status: Optional[str] = None, limit: int = 50, offset: int = 0
) -> List[ContentReport]:
    query = db.query(ContentReport)
    if status:
        query = query.filter(ContentReport.status == status)
    return (
        query.order_by(ContentReport.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def resolve_report(
    db: Session, *, moderator: User, report_id: int, actioned: bool
) -> ContentReport:
    report = db.get(ContentReport, report_id)
    if report is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Report not found.")

    report.status = REPORT_STATUS_ACTIONED if actioned else REPORT_STATUS_DISMISSED
    report.resolved_by_id = moderator.id
    report.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(report)

    # 3C.1: approved (actioned) human reports earn the reporter reputation.
    # System-generated reports (reporter_id is None) don't have anyone to
    # reward.
    if actioned and report.reporter_id is not None:
        reputation_service.award(
            db,
            user_id=report.reporter_id,
            delta=5,
            source=reputation_service.SOURCE_APPROVED_REPORT,
            ref_type="content_report",
            ref_id=report.id,
        )

    # F-28: the filer previously heard nothing back once a report they filed
    # was resolved either way. System-generated reports (reporter_id is
    # None) have no one to notify.
    if report.reporter_id is not None:
        notify_async(
            type="moderation.report_resolved",
            user_id=report.reporter_id,
            title="Your report was reviewed",
            body=(
                "A moderator reviewed your report and took action."
                if actioned
                else "A moderator reviewed your report and found no violation."
            ),
            target_type=report.target_type,
            target_id=report.target_id,
            data={"action": "report_resolved", "report_id": report.id, "actioned": actioned},
        )
    return report


def prune_resolved_reports(
    db: Session, *, older_than_days: int = REPORT_RETENTION_DAYS
) -> int:
    """Delete resolved (actioned/dismissed) reports past their retention
    window (F-28). Pending reports are never pruned -- only ones a
    moderator has already acted on."""

    threshold = datetime.utcnow() - timedelta(days=older_than_days)
    deleted = (
        db.query(ContentReport)
        .filter(
            ContentReport.status != REPORT_STATUS_PENDING,
            ContentReport.resolved_at.isnot(None),
            ContentReport.resolved_at < threshold,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def report_to_dict(report: ContentReport) -> Dict[str, Any]:
    return {
        "id": report.id,
        "target_type": report.target_type,
        "target_id": report.target_id,
        "reporter_id": report.reporter_id,
        "reason": report.reason,
        "status": report.status,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "resolved_at": report.resolved_at.isoformat() if report.resolved_at else None,
    }


__all__ = [
    "SORT_TOP",
    "SORT_NEWEST",
    "SORT_OLDEST",
    "VALID_SORTS",
    "create_comment",
    "edit_comment",
    "delete_comment",
    "moderator_remove_comment",
    "list_thread",
    "serialize_comment",
    "toggle_vote",
    "toggle_reaction",
    "report_comment",
    "list_reports",
    "resolve_report",
    "prune_resolved_reports",
    "report_to_dict",
]
