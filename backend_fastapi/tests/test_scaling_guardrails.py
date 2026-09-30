"""Scalability guardrails (SRS 1C).

These enforce the Part 1 obligations that keep the Part 4 database design
possible (1C.3.5), the infrastructure-boundary rule (1C.4.3), and the workload
priority policy (1C.5.3). They are cheap, boot-free structural checks so a
future change that reintroduces an unindexed hotspot, an image blob column, a
hardware-provisioning endpoint, or a broken priority ordering fails CI.
"""

from __future__ import annotations

from sqlalchemy import LargeBinary

from backend_fastapi.app.core.scaling import existing_high_volume_tables
from backend_fastapi.app.core import workload_priority as wp
from backend_fastapi.app.models import Base

# Importing the models module registers every table on Base.metadata.
import backend_fastapi.app.models  # noqa: F401


def _index_column_sets(table) -> list[set[str]]:
    sets = []
    for index in table.indexes:
        sets.append({c.name for c in index.columns})
    # A column declared with index=True or primary_key also yields coverage.
    for col in table.columns:
        if col.index or col.primary_key:
            sets.append({col.name})
    return sets


def test_high_volume_tables_have_partition_key_indexed():
    """Every existing high-volume table indexes its partition-key column(s).

    Without this, time-/key-ordered pagination degrades to a full scan as the
    table grows (SRS 1C.3.5).
    """
    metadata = Base.metadata
    for entry in existing_high_volume_tables():
        table = metadata.tables.get(entry.table)
        assert table is not None, f"{entry.table} missing from metadata"
        index_sets = _index_column_sets(table)
        # The leading partition-key column must be covered by some index.
        leading = entry.partition_key[0]
        assert any(
            leading in cols for cols in index_sets
        ), f"{entry.table}.{leading} (partition key) is not indexed"


def test_no_image_binary_columns_in_relational_db():
    """No image/page/asset binary lives in the relational DB (SRS 1C.3.5).

    Only references (URLs/keys) are stored; binaries live in object storage.
    """
    offenders = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, LargeBinary):
                offenders.append(f"{table.name}.{col.name}")
    assert not offenders, f"binary columns found: {offenders}"


def test_admin_panel_has_no_hardware_provisioning_endpoints():
    """The admin panel manages software limits only (SRS 1C.4.3).

    No VM/server/worker-machine/hardware provisioning endpoints may exist.
    """
    from backend_fastapi.app.api.routers.admin import router as admin_router

    forbidden = (
        "provision",
        "/vm",
        "virtual-machine",
        "hardware",
        "/server",
        "create-server",
        "worker-machine",
        "instance",
        "gpu",
        "cpu-cores",
    )
    hits = []
    for route in admin_router.routes:
        path = getattr(route, "path", "").lower()
        for token in forbidden:
            if token in path:
                hits.append(path)
    assert not hits, f"hardware-provisioning-like admin routes: {hits}"


def test_workload_priority_ordering():
    """Translation (High) > OCR (Medium) > scraping (Low) (SRS 1C.5.3)."""
    translation = wp.priority_for("backend_fastapi.app.tasks.translation_tasks")
    ocr = wp.priority_for("backend_fastapi.app.tasks.ocr_tasks")
    scrape = wp.priority_for("backend_fastapi.app.tasks.scraper_tasks")
    assert translation == wp.HIGH
    assert ocr == wp.MEDIUM
    assert scrape == wp.LOW
    assert translation > ocr > scrape


def test_celery_routes_carry_priorities():
    """The priority policy is wired into Celery task routing (SRS 1C.5.3)."""
    from backend_fastapi.app.core.celery_app import celery_app

    routes = celery_app.conf.task_routes
    translation = routes["backend_fastapi.app.tasks.translation_tasks.*"]
    scrape = routes["backend_fastapi.app.tasks.scraper_tasks.*"]
    assert translation["priority"] == wp.HIGH
    assert scrape["priority"] == wp.LOW
    # Queue isolation is preserved.
    assert translation["queue"] == "translation"
    assert scrape["queue"] == "scrape"
