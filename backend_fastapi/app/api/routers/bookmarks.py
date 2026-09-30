"""Authenticated bookmark management routes."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user
from ...models import Bookmark, Chapter, Manga, User
from ...schemas.bookmarks import (
    BookmarkListResponse,
    BookmarkCreateRequest,
    BookmarkActionResponse,
)

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@dataclass(slots=True)
class _BookmarkPayload:
    id: int
    manga_id: int
    manga_title: str | None
    cover_image: str | None
    chapter_id: int | None
    chapter_title: str | None
    created_at: str | None


def _bookmark_to_payload(
    bookmark: Bookmark, manga: Manga | None, chapter: Chapter | None
) -> dict[str, object | None]:
    created_at = getattr(bookmark, "created_at", None)
    payload = _BookmarkPayload(
        id=bookmark.id,
        manga_id=bookmark.manga_id,
        manga_title=getattr(manga, "title", None),
        cover_image=getattr(manga, "cover_image", None)
        or getattr(manga, "cover_url", None),
        chapter_id=bookmark.chapter_id,
        chapter_title=getattr(chapter, "chapter_title", None),
        created_at=created_at.isoformat() if created_at else None,
    )
    return asdict(payload)


@router.get("/", response_model=BookmarkListResponse)
@router.get("", response_model=BookmarkListResponse)
def list_bookmarks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's bookmarks sorted by creation time."""

    rows = (
        db.query(Bookmark, Manga, Chapter)
        .join(Manga, Bookmark.manga_id == Manga.id)
        .join(Chapter, Bookmark.chapter_id == Chapter.id, isouter=True)
        .filter(Bookmark.user_id == current_user.id)
        .order_by(Bookmark.created_at.desc().nullslast(), Bookmark.id.desc())
        .all()
    )

    return [
        _bookmark_to_payload(bookmark, manga, chapter)
        for bookmark, manga, chapter in rows
    ]


@router.post(
    "/", response_model=BookmarkActionResponse, status_code=status.HTTP_201_CREATED
)
@router.post(
    "",
    response_model=BookmarkActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_bookmark(
    payload: BookmarkCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create (or ensure) a bookmark for the current user."""

    manga_id = payload.mangaId if payload.mangaId is not None else payload.manga_id
    chapter_id = (
        payload.chapterId if payload.chapterId is not None else payload.chapter_id
    )

    if manga_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="mangaId is required"
        )

    manga = db.get(Manga, manga_id)
    if manga is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="manga_not_found"
        )

    query = db.query(Bookmark).filter(
        Bookmark.user_id == current_user.id,
        Bookmark.manga_id == manga_id,
    )
    if chapter_id is None:
        query = query.filter(Bookmark.chapter_id.is_(None))
    else:
        query = query.filter(Bookmark.chapter_id == chapter_id)

    existing = query.first()
    if existing is not None:
        return JSONResponse(
            BookmarkActionResponse(
                message="already_bookmarked", id=existing.id
            ).model_dump(),
            status_code=status.HTTP_200_OK,
        )

    bookmark = Bookmark(
        user_id=current_user.id, manga_id=manga_id, chapter_id=chapter_id
    )
    db.add(bookmark)
    db.commit()
    db.refresh(bookmark)

    return BookmarkActionResponse(message="bookmark_added", id=bookmark.id)


@router.delete("/{manga_id}", response_model=BookmarkActionResponse)
def delete_bookmark_for_manga(
    manga_id: int,
    chapter_id: int | None = Query(default=None, alias="chapterId"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete bookmarks for a manga, optionally scoped to a chapter."""

    query = db.query(Bookmark).filter(
        Bookmark.user_id == current_user.id,
        Bookmark.manga_id == manga_id,
    )
    if chapter_id is not None:
        query = query.filter(Bookmark.chapter_id == chapter_id)

    deleted_count = query.delete(synchronize_session=False)
    if not deleted_count:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bookmark_not_found"
        )

    db.commit()

    return {"message": "bookmark_deleted", "count": deleted_count}


@router.delete("/by-id/{bookmark_id}", response_model=BookmarkActionResponse)
def delete_bookmark_by_id(
    bookmark_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a bookmark by its row identifier."""

    bookmark = (
        db.query(Bookmark)
        .filter(Bookmark.id == bookmark_id, Bookmark.user_id == current_user.id)
        .first()
    )
    if bookmark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="bookmark_not_found"
        )

    db.delete(bookmark)
    db.commit()

    return {"message": "bookmark_deleted"}
