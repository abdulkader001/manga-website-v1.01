"""Utility CLI helpers for the FastAPI backend."""

from __future__ import annotations

import argparse
import structlog
from contextlib import contextmanager
from typing import Iterator

from .services.scraper_service import (
    delete_chapter_pages_only,
    rescrape_chapter as rescrape_chapter_service,
    rescrape_series as rescrape_series_service,
)

from . import models  # noqa: F401  # ensures model metadata is registered
from .core.db import SessionLocal
from .models import Chapter, Manga

logger = structlog.get_logger(__name__)


@contextmanager
def _session_scope() -> Iterator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def migrate() -> None:
    """Run database migrations via Alembic."""

    from alembic import command
    from alembic.config import Config
    import os

    logger.info("Migrating database")

    alembic_cfg_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "alembic.ini"
    )
    alembic_cfg = Config(alembic_cfg_path)
    # Ensure correct base path for script location
    script_location = os.path.join(os.path.dirname(__file__), "migrations")
    alembic_cfg.set_main_option("script_location", script_location)
    command.upgrade(alembic_cfg, "head")
    logger.info("Database migration complete")


def rescrape_series(manga_id: int) -> None:
    """Trigger a rescrape for the specified manga ID."""

    with _session_scope() as session:
        manga = session.get(Manga, manga_id)
        if manga is None:
            raise SystemExit(f"Manga id={manga_id} not found")
        logger.info("Starting rescrape for manga id=%s", manga_id)
        rescrape_series_service(manga, db_session=session)
        logger.info("Rescrape complete for manga id=%s", manga_id)


def rescrape_chapter(chapter_id: int, *, delete_previous: bool = False) -> None:
    """Trigger a chapter rescrape, optionally deleting existing pages."""

    with _session_scope() as session:
        chapter = session.get(Chapter, chapter_id)
        if chapter is None:
            raise SystemExit(f"Chapter id={chapter_id} not found")
        logger.info(
            "Starting rescrape for chapter id=%s (delete_previous=%s)",
            chapter_id,
            delete_previous,
        )
        if delete_previous:
            delete_chapter_pages_only(chapter, db_session=session)
        rescrape_chapter_service(chapter, db_session=session)
        logger.info("Rescrape complete for chapter id=%s", chapter_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="FastAPI backend utility commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="Create database tables")

    series_parser = subparsers.add_parser(
        "rescrape-series", help="Trigger a full rescrape for a manga series"
    )
    series_parser.add_argument("manga_id", type=int, help="ID of the manga to rescrape")

    chapter_parser = subparsers.add_parser(
        "rescrape-chapter", help="Rescrape a single chapter"
    )
    chapter_parser.add_argument(
        "chapter_id", type=int, help="ID of the chapter to rescrape"
    )
    chapter_parser.add_argument(
        "--delete-previous",
        action="store_true",
        help="Delete existing chapter pages before rescraping",
    )

    args = parser.parse_args()

    if args.command == "migrate":  # pragma: no cover - exercised via CLI
        migrate()
    elif args.command == "rescrape-series":  # pragma: no cover - exercised via CLI
        rescrape_series(args.manga_id)
    elif args.command == "rescrape-chapter":  # pragma: no cover - exercised via CLI
        rescrape_chapter(args.chapter_id, delete_previous=args.delete_previous)
    else:  # pragma: no cover - defensive fallback
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover - module executed as a script
    main()
