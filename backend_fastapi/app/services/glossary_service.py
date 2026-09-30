"""CRUD for the per-series character-name glossary (SRS 2C.1)."""

from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from ..models.glossary import SeriesGlossaryTerm


def get_glossary(db: Session, manga_id: int, target_lang: str) -> Dict[str, str]:
    rows = (
        db.query(SeriesGlossaryTerm)
        .filter(
            SeriesGlossaryTerm.manga_id == manga_id,
            SeriesGlossaryTerm.target_lang == target_lang,
        )
        .all()
    )
    return {row.source_term: row.translated_term for row in rows}


def list_terms(
    db: Session, manga_id: int, target_lang: str
) -> List[SeriesGlossaryTerm]:
    return (
        db.query(SeriesGlossaryTerm)
        .filter(
            SeriesGlossaryTerm.manga_id == manga_id,
            SeriesGlossaryTerm.target_lang == target_lang,
        )
        .order_by(SeriesGlossaryTerm.source_term)
        .all()
    )


def upsert_term(
    db: Session, manga_id: int, target_lang: str, source_term: str, translated_term: str
) -> SeriesGlossaryTerm:
    source_term = source_term.strip()
    translated_term = translated_term.strip()
    row = (
        db.query(SeriesGlossaryTerm)
        .filter(
            SeriesGlossaryTerm.manga_id == manga_id,
            SeriesGlossaryTerm.target_lang == target_lang,
            SeriesGlossaryTerm.source_term == source_term,
        )
        .one_or_none()
    )
    if row is None:
        row = SeriesGlossaryTerm(
            manga_id=manga_id, target_lang=target_lang, source_term=source_term
        )
        db.add(row)
    row.translated_term = translated_term
    db.commit()
    db.refresh(row)
    return row


def delete_term(db: Session, manga_id: int, target_lang: str, source_term: str) -> bool:
    row = (
        db.query(SeriesGlossaryTerm)
        .filter(
            SeriesGlossaryTerm.manga_id == manga_id,
            SeriesGlossaryTerm.target_lang == target_lang,
            SeriesGlossaryTerm.source_term == source_term,
        )
        .one_or_none()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


__all__ = ["get_glossary", "list_terms", "upsert_term", "delete_term"]
