"""Per-series character-name glossary endpoints (SRS 2C.1)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import require_permission
from ...models import Manga
from ...services import glossary_service

router = APIRouter(prefix="/manga/{manga_id}/glossary", tags=["glossary"])


class GlossaryTermPayload(BaseModel):
    target_lang: str = Field(..., min_length=1, max_length=16)
    source_term: str = Field(..., min_length=1, max_length=120)
    translated_term: str = Field(..., min_length=1, max_length=120)


class GlossaryTermResponse(BaseModel):
    source_term: str
    translated_term: str


def _ensure_manga(db: Session, manga_id: int) -> None:
    if db.get(Manga, manga_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


@router.get("", response_model=List[GlossaryTermResponse])
def list_glossary(
    manga_id: int,
    target_lang: str,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("correct_translation")),
):
    _ensure_manga(db, manga_id)
    terms = glossary_service.list_terms(db, manga_id, target_lang)
    return [
        {"source_term": t.source_term, "translated_term": t.translated_term}
        for t in terms
    ]


@router.put("", response_model=GlossaryTermResponse)
def upsert_glossary_term(
    manga_id: int,
    payload: GlossaryTermPayload,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("correct_translation")),
):
    _ensure_manga(db, manga_id)
    row = glossary_service.upsert_term(
        db,
        manga_id,
        payload.target_lang.strip(),
        payload.source_term,
        payload.translated_term,
    )
    return {"source_term": row.source_term, "translated_term": row.translated_term}


@router.delete("")
def delete_glossary_term(
    manga_id: int,
    target_lang: str,
    source_term: str,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("correct_translation")),
):
    _ensure_manga(db, manga_id)
    removed = glossary_service.delete_term(db, manga_id, target_lang, source_term)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return {"status": "ok"}


__all__ = ["router"]
