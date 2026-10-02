"""Native comment system endpoints (SRS Part 3 / 3A).

Comments are always native -- 1F.12 removed the third-party provider
system entirely, so there is no provider gate here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...core.pagination import MAX_OFFSET
from ...dependencies.auth import get_current_user, get_optional_user, require_permission
from ...models import User
from ...models.user import MAX_COMMENT_LENGTH, MAX_COMMENT_REPLY_DEPTH
from ...services import comment_service, processing_settings_service
from ...services.emoji_catalogue import BASE_EMOJI_COUNT
from ...schemas.comments import (
    CommentCreateRequest,
    CommentEditRequest,
    CommentReactionRequest,
    CommentReportRequest,
    CommentVoteRequest,
    ModeratorRemoveRequest,
    ResolveReportRequest,
)
from ...utils.endpoint_limiter import async_endpoint_limiter

router = APIRouter(prefix="/comments", tags=["comments"])


def _translation_service():
    """The shared translation service singleton configured at startup
    (``translation`` router). Imported lazily so this module doesn't need
    ``translation`` configured to import cleanly."""

    from . import translation as translation_router

    return translation_router.translation_service


def _resolve_target_lang(
    viewer: Optional[User], lang_override: Optional[str], db: Session
) -> Optional[str]:
    if lang_override:
        return lang_override.strip().lower()
    if viewer is None:
        return None
    prefs = processing_settings_service.get_or_create(db, viewer.id)
    if not prefs.auto_translate_comments:
        return None
    return getattr(viewer, "language", None)


@router.get("/config")
def get_comment_config():
    return {
        "max_length": MAX_COMMENT_LENGTH,
        "max_reply_depth": MAX_COMMENT_REPLY_DEPTH,
        "base_emoji_count": BASE_EMOJI_COUNT,
        "sort_options": list(comment_service.VALID_SORTS),
    }


@router.get("/moderation/reports")
def list_reports(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    _moderator: User = Depends(require_permission("handle_reports")),
    db: Session = Depends(get_db),
):
    reports = comment_service.list_reports(
        db, status=status, limit=limit, offset=offset
    )
    return {"items": [comment_service.report_to_dict(r) for r in reports]}


# NOTE: this generic two-segment route must stay registered AFTER every
# literal two-segment path above it (e.g. "/moderation/reports") -- FastAPI
# matches routes in registration order, and {target_type}/{target_id} would
# otherwise shadow them.
@router.get("/{target_type}/{target_id}")
def list_comments(
    target_type: str,
    target_id: int,
    sort: str = Query(comment_service.SORT_TOP),
    limit: int = Query(
        comment_service.DEFAULT_PAGE_SIZE, ge=1, le=comment_service.MAX_PAGE_SIZE
    ),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    lang: Optional[str] = Query(None),
    viewer: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    result = comment_service.list_thread(
        db,
        target_type=target_type,
        target_id=target_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    target_lang = _resolve_target_lang(viewer, lang, db)
    translation_service = _translation_service() if target_lang else None
    items = [
        comment_service.serialize_comment(
            db,
            comment,
            viewer=viewer,
            target_lang=target_lang,
            translation_service=translation_service,
        )
        for comment in result["items"]
    ]
    return {
        "items": items,
        "total": result["total"],
        "limit": result["limit"],
        "offset": result["offset"],
        "sort": result["sort"],
    }


@router.post("/")
async def add_comment(
    request: Request,
    payload: CommentCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await async_endpoint_limiter.check_limit(
        request, f"post_comment:{current_user.id}", limit=20, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        comment = comment_service.create_comment(
            db,
            user=current_user,
            target_type=payload.target_type,
            target_id=payload.target_id,
            content=payload.content,
            parent_id=payload.parent_id,
            attachment_type=payload.attachment_type,
            attachment_url=payload.attachment_url,
            attachment_metadata=payload.attachment_metadata,
        )
        return comment_service.serialize_comment(db, comment, viewer=current_user)

    return await run_in_db_threadpool(_work)


@router.patch("/{comment_id}")
async def edit_comment(
    request: Request,
    comment_id: int,
    payload: CommentEditRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await async_endpoint_limiter.check_limit(
        request, f"edit_comment:{current_user.id}", limit=30, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        comment = comment_service.edit_comment(
            db, user=current_user, comment_id=comment_id, content=payload.content
        )
        return comment_service.serialize_comment(db, comment, viewer=current_user)

    return await run_in_db_threadpool(_work)


@router.delete("/{comment_id}")
def delete_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = comment_service.delete_comment(
        db, user=current_user, comment_id=comment_id
    )
    return comment_service.serialize_comment(db, comment, viewer=current_user)


@router.post("/{comment_id}/vote")
async def vote_comment(
    request: Request,
    comment_id: int,
    payload: CommentVoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await async_endpoint_limiter.check_limit(
        request, f"vote_comment:{current_user.id}", limit=200, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        comment = comment_service.toggle_vote(
            db, user=current_user, comment_id=comment_id, value=payload.value
        )
        return comment_service.serialize_comment(db, comment, viewer=current_user)

    return await run_in_db_threadpool(_work)


@router.post("/{comment_id}/react")
async def react_to_comment(
    request: Request,
    comment_id: int,
    payload: CommentReactionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await async_endpoint_limiter.check_limit(
        request, f"react_comment:{current_user.id}", limit=300, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        comment = comment_service.toggle_reaction(
            db, user=current_user, comment_id=comment_id, emoji=payload.emoji
        )
        return comment_service.serialize_comment(db, comment, viewer=current_user)

    return await run_in_db_threadpool(_work)


@router.post("/{comment_id}/report")
async def report_comment(
    request: Request,
    comment_id: int,
    payload: CommentReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await async_endpoint_limiter.check_limit(
        request, f"report_comment:{current_user.id}", limit=20, window_seconds=3600
    )
    from ...utils.bounded_threadpool import run_in_db_threadpool

    def _work():
        report = comment_service.report_comment(
            db, user=current_user, comment_id=comment_id, reason=payload.reason
        )
        return comment_service.report_to_dict(report)

    return await run_in_db_threadpool(_work)


@router.post("/{comment_id}/remove")
def moderator_remove_comment(
    comment_id: int,
    payload: ModeratorRemoveRequest,
    moderator: User = Depends(require_permission("remove_comments")),
    db: Session = Depends(get_db),
):
    comment = comment_service.moderator_remove_comment(
        db, moderator=moderator, comment_id=comment_id, reason=payload.reason
    )
    return comment_service.serialize_comment(db, comment, viewer=moderator)


@router.post("/moderation/reports/{report_id}/resolve")
def resolve_report(
    report_id: int,
    payload: ResolveReportRequest,
    moderator: User = Depends(require_permission("handle_reports")),
    db: Session = Depends(get_db),
):
    report = comment_service.resolve_report(
        db, moderator=moderator, report_id=report_id, actioned=payload.actioned
    )
    return comment_service.report_to_dict(report)
