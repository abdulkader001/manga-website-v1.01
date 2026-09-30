"""Community endpoints (SRS Part 3): emojis, reputation, cultivation rank,
Pills, GIFs/memes, and user-level community moderation (block/timeout).

Comment CRUD/voting/reactions/reporting live in ``comments.py``; this router
covers the surrounding community systems that aren't comment-specific.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.api_errors import ApiError, ErrorCode
from ...core.db import get_db
from ...dependencies.auth import (
    get_current_user,
    require_main_admin_user,
    require_permission,
)
from ...models import User
from ...services import (
    comment_service,
    emoji_catalogue,
    gif_service,
    meme_service,
    moderation_service,
    pill_service,
    ranking_service,
)
from ...utils.endpoint_limiter import async_endpoint_limiter
from ...schemas.comments import CommentReportRequest
from ...schemas.community import (
    BlockUserRequest,
    CustomEmojiCreateRequest,
    RealmUpdateRequest,
    TimeoutUserRequest,
)

router = APIRouter(prefix="/community", tags=["community"])


# ---------------------------------------------------------------------------
# Emoji picker (3A.4)
# ---------------------------------------------------------------------------


@router.get("/emojis")
def list_emojis(q: Optional[str] = Query(None), db: Session = Depends(get_db)):
    return {
        "base": emoji_catalogue.search(q or ""),
        "custom": emoji_catalogue.list_custom(db),
        "categories": emoji_catalogue.categories(),
    }


@router.post("/emojis/custom")
def add_custom_emoji(
    payload: CustomEmojiCreateRequest,
    admin: User = Depends(require_main_admin_user),
    db: Session = Depends(get_db),
):
    emoji = emoji_catalogue.add_custom(
        db,
        shortcode=payload.shortcode,
        image_url=payload.image_url,
        category=payload.category or "custom",
        created_by_id=admin.id,
    )
    return {
        "id": emoji.id,
        "shortcode": emoji.shortcode,
        "emoji": f"custom:{emoji.shortcode}",
        "image_url": emoji.image_url,
        "category": emoji.category,
    }


@router.delete("/emojis/custom/{emoji_id}")
def remove_custom_emoji(
    emoji_id: int,
    _admin: User = Depends(require_main_admin_user),
    db: Session = Depends(get_db),
):
    removed = emoji_catalogue.remove_custom(db, emoji_id)
    if not removed:
        raise ApiError(ErrorCode.NOT_FOUND, "Custom emoji not found.")
    return {"removed": True}


# ---------------------------------------------------------------------------
# Cultivation rank / reputation (3C / 3D)
# ---------------------------------------------------------------------------


@router.get("/rank/me")
def get_my_rank(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return ranking_service.rank_for(db, current_user.reputation or 0)


@router.get("/rank/{user_id}")
def get_user_rank(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(ErrorCode.NOT_FOUND, "User not found.")
    return ranking_service.rank_for(db, user.reputation or 0)


@router.get("/realms")
def list_realms(db: Session = Depends(get_db)):
    return {
        "items": [
            ranking_service.realm_to_dict(r) for r in ranking_service.list_realms(db)
        ]
    }


@router.patch("/realms/{realm_id}")
def update_realm(
    realm_id: int,
    payload: RealmUpdateRequest,
    _admin: User = Depends(require_main_admin_user),
    db: Session = Depends(get_db),
):
    realm = ranking_service.update_realm(
        db,
        realm_id,
        name=payload.name,
        reputation_threshold=payload.reputation_threshold,
        stage_count=payload.stage_count,
        color_band=payload.color_band,
        dedicated_contributor=payload.dedicated_contributor,
    )
    if realm is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Realm not found.")
    return ranking_service.realm_to_dict(realm)


# ---------------------------------------------------------------------------
# Pills (3C.3)
# ---------------------------------------------------------------------------


@router.get("/pills")
def list_my_pills(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    pills = pill_service.list_for_user(db, user_id=current_user.id)
    return {"items": [pill_service.pill_to_dict(p) for p in pills]}


@router.post("/pills/{pill_id}/claim")
def claim_pill(
    pill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pill = pill_service.claim(db, user_id=current_user.id, pill_id=pill_id)
    return pill_service.pill_to_dict(pill)


# ---------------------------------------------------------------------------
# Community moderation of users (1F.4.1) -- block / timeout
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/block")
def block_user(
    user_id: int,
    payload: BlockUserRequest,
    moderator: User = Depends(require_permission("block_user")),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(ErrorCode.NOT_FOUND, "User not found.")
    moderation_service.block_user(
        db, moderator=moderator, target=target, reason=payload.reason
    )
    return {"blocked": True}


@router.post("/users/{user_id}/unblock")
def unblock_user(
    user_id: int,
    moderator: User = Depends(require_permission("block_user")),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(ErrorCode.NOT_FOUND, "User not found.")
    moderation_service.unblock_user(db, moderator=moderator, target=target)
    return {"blocked": False}


@router.post("/users/{user_id}/timeout")
def timeout_user(
    user_id: int,
    payload: TimeoutUserRequest,
    moderator: User = Depends(require_permission("timeout_user")),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise ApiError(ErrorCode.NOT_FOUND, "User not found.")
    moderation_service.timeout_user(
        db,
        moderator=moderator,
        target=target,
        hours=payload.hours,
        reason=payload.reason,
    )
    return {"timed_out_until": target.community_timeout_until.isoformat()}


# ---------------------------------------------------------------------------
# GIFs -- Tier 1 (3B.2): URL/metadata only, never the file
# ---------------------------------------------------------------------------


@router.get("/gifs/search")
def search_gifs(q: str = Query(...), _current_user: User = Depends(get_current_user)):
    return gif_service.search(q)


# ---------------------------------------------------------------------------
# Memes -- Tier 2 (3B.2/3B.4)
# ---------------------------------------------------------------------------


@router.post("/memes")
async def upload_meme(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await async_endpoint_limiter.check_limit(
        request, f"upload_meme:{current_user.id}", limit=20, window_seconds=3600
    )
    meme = meme_service.upload_meme(db, request, file, user=current_user)
    return meme_service.meme_to_dict(meme)


@router.get("/memes/file/{filename}")
def serve_meme_file(filename: str, request: Request, db: Session = Depends(get_db)):
    path = meme_service.resolve_file_path(db, request, filename)
    if path is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Meme not found.")
    return FileResponse(path, media_type="image/webp")


@router.delete("/memes/{meme_id}")
def remove_meme(
    meme_id: int,
    request: Request,
    moderator: User = Depends(require_permission("moderate_images")),
    db: Session = Depends(get_db),
):
    meme = meme_service.remove_meme(
        db, request, meme_id=meme_id, reason="Removed by moderator"
    )
    if meme is None:
        raise ApiError(ErrorCode.NOT_FOUND, "Meme not found.")
    return meme_service.meme_to_dict(meme)


@router.post("/memes/{meme_id}/report")
async def report_meme(
    request: Request,
    meme_id: int,
    payload: CommentReportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    await async_endpoint_limiter.check_limit(
        request, f"report_meme:{current_user.id}", limit=20, window_seconds=3600
    )
    report = meme_service.report_meme(
        db, user=current_user, meme_id=meme_id, reason=payload.reason
    )
    return comment_service.report_to_dict(report)
