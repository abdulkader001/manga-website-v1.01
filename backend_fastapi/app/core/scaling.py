"""Scaling metadata: high-volume table registry (SRS 1C.3.5 / 1C.3.6).

Part 1 must not make the Part 4 database design impossible. One concrete Part 1
obligation is that *every high-volume table has a partition key identified, even
if partitioning is deferred* (1C.3.5), and that those partition/FK columns are
indexed so no query degrades to an unbounded scan as the table grows.

This module is the single source of truth for that identification. The
guardrail tests assert that every registered table which actually exists in the
ORM metadata has its partition-key columns indexed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HighVolumeTable:
    table: str
    growth_driver: str
    # Column(s) that will serve as the partition key AND must be indexed so
    # that queries and pagination stay bounded (1C.3.5).
    partition_key: tuple[str, ...]
    # False for tables not yet created in this part (e.g. Part 2/3 caches).
    exists_now: bool = True
    notes: str = field(default="")


# SRS 1C.3.6 — identify now, partition later.
HIGH_VOLUME_TABLES: tuple[HighVolumeTable, ...] = (
    HighVolumeTable(
        "read_history",
        "users x chapters read",
        ("user_id", "last_read_at"),
        notes="per-user timeline; indexed by (user_id, last_read_at)",
    ),
    HighVolumeTable(
        "admin_audit_logs",
        "all privileged actions",
        ("timestamp",),
        notes="append-only; partition by time",
    ),
    HighVolumeTable(
        "chapters",
        "series x chapters",
        ("manga_id",),
        notes="indexed by (manga_id, chapter_number)",
    ),
    HighVolumeTable(
        "bookmarks",
        "users x bookmarked series",
        ("user_id",),
        notes="indexed by (user_id, manga_id)",
    ),
    HighVolumeTable(
        "scraping_jobs",
        "ingestion jobs over time",
        ("status", "updated_at"),
        notes="indexed by (status, updated_at)",
    ),
    # --- Not created in Part 1; identified now so the design leaves room. ---
    HighVolumeTable(
        "chapter_pages",
        "chapters x pages",
        ("chapter_id",),
        exists_now=False,
        notes="pages currently stored as a JSON column on chapters",
    ),
    # --- Created since (Part 2/3). Registry updated to match reality —
    # otherwise existing_high_volume_tables() silently stops verifying them
    # (SRS 4A.2/4A.3: every high-volume table needs its partition key indexed
    # from the first migration, not just identified on paper). ---
    HighVolumeTable(
        "ocr_cache",
        "chapters (once each, never per language)",
        ("chapter_id",),
        notes="Part 2 (20260810_ocr_translation_cache) — indexed via the "
        "unique (chapter_id, page_index) index",
    ),
    HighVolumeTable(
        "translation_cache",
        "chapters x languages actually requested",
        ("chapter_id", "target_lang"),
        notes="Part 2 (20260810_ocr_translation_cache) — indexed via the "
        "unique (chapter_id, page_index, target_lang) index",
    ),
    HighVolumeTable(
        "notifications",
        "users x events",
        ("user_id", "created_at"),
        notes="Part 1I (20260811_notification_system) — indexed via "
        "(user_id, read) / (user_id, created_at)",
    ),
    HighVolumeTable(
        "comments",
        "users x activity",
        ("target_type", "target_id"),
        notes="Part 3 (20260722_native_comments_core). Polymorphic target "
        "(manga or chapter), not a bare series_id — indexed via "
        "(target_type, target_id, parent_id), migration "
        "20260723_index_comments_table",
    ),
    HighVolumeTable(
        "sessions",
        "users x devices",
        ("expires_at",),
        exists_now=False,
        notes="Auth remains stateless-JWT; DB-backed sessions are a "
        "1C.2.1/1D deliverable, tracked there — out of Part 4's scope "
        "(4.0.1), not a Part 4 gap",
    ),
    HighVolumeTable(
        "usage_counters",
        "users x time buckets",
        ("time_bucket",),
        exists_now=False,
        notes="Part 2 usage ceiling (2E.3) tracks a running counter, not a "
        "per-event table, so there is no usage_counters table to partition",
    ),
)


def existing_high_volume_tables() -> tuple[HighVolumeTable, ...]:
    return tuple(t for t in HIGH_VOLUME_TABLES if t.exists_now)
