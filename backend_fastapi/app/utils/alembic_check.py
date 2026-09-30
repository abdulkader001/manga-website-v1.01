"""Utilities for inspecting Alembic migration state without applying migrations."""

from __future__ import annotations

import structlog
import os
from dataclasses import dataclass
from pathlib import Path

logger = structlog.get_logger("backend_fastapi.alembic")


@dataclass
class AlembicSchemaStatus:
    """Migration heads on disk versus the revision the database reports.

    ``head_revisions`` / ``current_revisions`` are ``None`` when the value
    could not be determined at all -- distinct from an empty set, which is the
    legitimate state of a database that has never had a migration applied.
    """

    config_path: Path | None
    config_missing: bool
    errors: list[str]

    head_revisions: set[str] | None = None
    current_revisions: set[str] | None = None

    @property
    def determinate(self) -> bool:
        """Whether drift could actually be evaluated."""

        return self.schema_drift is not None

    @property
    def schema_drift(self) -> bool | None:
        """Return ``True`` when heads and current revisions differ."""

        if self.config_missing:
            return None
        head_revisions = self.head_revisions
        current_revisions = self.current_revisions
        if head_revisions is None or current_revisions is None:
            return None
        return head_revisions != current_revisions

    def to_dict(self) -> dict[str, object]:
        return {
            "config_path": str(self.config_path) if self.config_path else None,
            "config_missing": self.config_missing,
            "schema_drift": self.schema_drift,
            "head_revisions": (
                sorted(self.head_revisions) if self.head_revisions is not None else None
            ),
            "current_revisions": (
                sorted(self.current_revisions)
                if self.current_revisions is not None
                else None
            ),
            "errors": list(self.errors),
        }


def _read_head_revisions(config_path: Path) -> set[str]:
    """Head revisions declared by the migration scripts on disk."""

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(config_path)))
    return set(script.get_heads())


def _read_current_revisions() -> set[str]:
    """Revisions the connected database reports in ``alembic_version``."""

    from alembic.runtime.migration import MigrationContext

    from ..core.db import engine

    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return set(context.get_current_heads())


def _resolve_alembic_config(
    config_path: str | os.PathLike[str] | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if config_path is not None:
        candidates.append(Path(config_path))
    env_config = os.getenv("ALEMBIC_CONFIG")
    if env_config:
        candidates.append(Path(env_config))
    module_root = Path(__file__).resolve()
    # Repository root first. `backend_fastapi/alembic.ini` also exists but
    # lacks `prepend_sys_path`, so resolving it here made every `alembic`
    # invocation fail to import the models package.
    candidates.extend(
        [
            module_root.parents[3] / "alembic.ini",
            module_root.parents[2] / "alembic.ini",
        ]
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def capture_alembic_status(
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> AlembicSchemaStatus:
    """Compare the migration heads on disk with the database's revision."""

    resolved_config = _resolve_alembic_config(config_path)
    errors: list[str] = []

    if resolved_config is None:
        message = "Alembic configuration file could not be located"
        logger.info(message)
        return AlembicSchemaStatus(
            config_path=None,
            config_missing=True,
            errors=[message],
        )

    # Read the revisions through Alembic's own API rather than scraping the
    # CLI. The previous implementation regex-matched `\b[0-9a-z]{6,}\b` over
    # combined stdout/stderr, which cannot work here: revision ids such as
    # `20260903_token_revocation` contain underscores, so the word boundaries
    # never match one, while Alembic's INFO logging ("Context impl
    # PostgresqlImpl", "Will assume transactional DDL") matched happily. Both
    # revision sets therefore resolved to None on every run, `schema_drift`
    # was permanently None, and the guard reported success unconditionally.
    head_revisions: set[str] | None = None
    current_revisions: set[str] | None = None

    try:
        head_revisions = _read_head_revisions(resolved_config)
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"Unable to read migration heads: {exc}")
        logger.warning("Unable to read Alembic migration heads", error=str(exc))

    try:
        current_revisions = _read_current_revisions()
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"Unable to read the database revision: {exc}")
        logger.warning("Unable to read the database Alembic revision", error=str(exc))

    status = AlembicSchemaStatus(
        config_path=resolved_config,
        config_missing=False,
        errors=errors,
        head_revisions=head_revisions,
        current_revisions=current_revisions,
    )

    if status.schema_drift:
        logger.warning(
            "Alembic revisions differ",
            heads=sorted(head_revisions or ()),
            current=sorted(current_revisions or ()),
        )

    return status


__all__ = [
    "AlembicSchemaStatus",
    "capture_alembic_status",
]
