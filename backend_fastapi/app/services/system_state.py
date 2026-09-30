"""System state helpers for the FastAPI backend."""

from __future__ import annotations

import structlog
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..models import SystemState

logger = structlog.get_logger(__name__)


@contextmanager
def get_db_session() -> Iterator[Session]:
    """Provide a short-lived session for background helpers."""

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_or_create_system_state(
    session: Session, *, for_update: bool = False
) -> SystemState:
    """Return the singleton :class:`SystemState`, creating it if missing."""

    query = session.query(SystemState)
    if for_update:
        query = query.with_for_update()

    state = query.first()
    if not state:
        state = SystemState(id=1)
        session.add(state)
        session.flush()
        logger.info("Initialized SystemState singleton row")
    return state


def get_system_state(session: Session) -> SystemState | None:
    """Return the singleton :class:`SystemState`, or ``None`` if absent.

    F-63: the read-only counterpart to :func:`get_or_create_system_state`. Read
    endpoints must use this one. Creating the row from a read path issues an
    INSERT that is never committed (``get_read_db`` only closes its session),
    and the unique-index lock it holds deadlocks any second session in the same
    request against the first — resolved only by PostgreSQL's
    ``statement_timeout``, which turned the manga listing into a flat 5s 504.
    """

    return session.query(SystemState).first()


def is_secret_phrase_used(session: Session) -> bool:
    """Report whether the bootstrap secret phrase has been consumed.

    Safe on a read-only session: never creates the singleton row. A missing row
    means bootstrap has not happened, so the phrase cannot have been used.
    """

    state = get_system_state(session)
    return bool(state is not None and state.secret_phrase_used)


def ensure_system_state_initialized() -> None:
    """Ensure the singleton row exists at application startup."""

    with get_db_session() as session:
        get_or_create_system_state(session)


__all__ = [
    "ensure_system_state_initialized",
    "get_db_session",
    "get_or_create_system_state",
    "get_system_state",
    "is_secret_phrase_used",
]
