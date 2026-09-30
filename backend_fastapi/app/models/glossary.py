"""Per-series character-name glossary (SRS 2C.1: "maintain consistent
character-name handling across chapters of one series").

One row per (series, target language, source term). Editable by anyone
holding ``correct_translation`` (the existing 1F permission for translation
quality work); consulted as context on every chapter translation for that
series+language so a name translated one way in chapter 3 doesn't drift in
chapter 4.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, func

from .base import Base


class SeriesGlossaryTerm(Base):
    __tablename__ = "series_glossary_terms"
    __table_args__ = (
        Index(
            "uq_glossary_manga_lang_source",
            "manga_id",
            "target_lang",
            "source_term",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    manga_id = Column(
        Integer, ForeignKey("manga.id", ondelete="CASCADE"), nullable=False
    )
    target_lang = Column(String(16), nullable=False)
    source_term = Column(String(120), nullable=False)
    translated_term = Column(String(120), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = ["SeriesGlossaryTerm"]
