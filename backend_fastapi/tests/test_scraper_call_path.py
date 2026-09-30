"""Gap C — enforce that the blocking scraper never runs in the async process.

H6 (sync ``time.sleep`` / ``requests`` inside the scrapers) was dispositioned
in Phase 4 as *confirmed / documented* rather than fixed, on the strength of a
single invariant: the blocking scraper only ever executes inside Celery's
prefork worker pool (off the event loop), never inline on an API request.

That disposition is only safe while the invariant actually holds, so this test
enforces it with an AST scan (robust against comments/strings, unlike grep).
If anyone later calls the scraper inline from a sync/async endpoint, this test
fails and H6 must be re-opened as a real fix (make the blocking calls async or
move them fully into the worker) rather than a doc note.

The concrete invariants:

* The request/async process (everything under ``app/api/``) must not
  instantiate the blocking scraper, call ``scrape_manga``/``scrape_chapter``,
  invoke the workflow methods, or import ``BaseScraper`` /
  ``ScraperWorkflowService``. It may only *enqueue* work via ``.delay(...)`` /
  ``.apply_async(...)``.
* Across the whole app, the blocking scraper (``BaseScraper(...)`` +
  ``scrape_manga`` / ``scrape_chapter`` calls) is confined to
  ``services/scraper_workflow_service.py``, and ``ScraperWorkflowService`` is
  only instantiated in ``tasks/scraper_tasks.py`` — i.e. it runs only where a
  Celery task drives it.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"
API_DIR = APP_DIR / "api"

# Names that, when instantiated, pull in the blocking scraper machinery.
BLOCKING_CLASSES = {"BaseScraper", "ScraperWorkflowService"}
# Methods that perform the actual blocking scrape (time.sleep / requests.get).
BLOCKING_METHODS = {"scrape_manga", "scrape_chapter"}
# The workflow driver methods (also the Celery task names). Reaching these
# without going through ``.delay`` / ``.apply_async`` means an inline call.
WORKFLOW_CALLABLES = {"process_manga_scrape", "process_chapter_scrape"}
# Attribute accessors that denote an async enqueue rather than an inline call.
ENQUEUE_ATTRS = {"delay", "apply_async"}


def _iter_py(root: Path):
    for path in sorted(root.rglob("*.py")):
        yield path


def _rel(path: Path) -> str:
    return str(path.relative_to(APP_DIR))


def _scan_for_inline_scraper_use(path: Path) -> list[str]:
    """Return human-readable findings of inline scraper use in ``path``."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []

    for node in ast.walk(tree):
        # Imports of the blocking machinery into this module.
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in BLOCKING_CLASSES:
                    findings.append(f"{_rel(path)}:{node.lineno}: imports {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] in BLOCKING_CLASSES:
                    findings.append(f"{_rel(path)}:{node.lineno}: imports {alias.name}")

        if not isinstance(node, ast.Call):
            continue
        func = node.func

        # Direct instantiation: BaseScraper(...) / ScraperWorkflowService(...).
        if isinstance(func, ast.Name) and func.id in BLOCKING_CLASSES:
            findings.append(f"{_rel(path)}:{node.lineno}: instantiates {func.id}(...)")
        # Bare inline call of a Celery task function: process_manga_scrape(...).
        if isinstance(func, ast.Name) and func.id in WORKFLOW_CALLABLES:
            findings.append(
                f"{_rel(path)}:{node.lineno}: calls {func.id}(...) inline "
                "(not .delay/.apply_async)"
            )
        # Attribute calls.
        if isinstance(func, ast.Attribute):
            if func.attr in BLOCKING_METHODS:
                findings.append(
                    f"{_rel(path)}:{node.lineno}: calls .{func.attr}(...) "
                    "(blocking scrape)"
                )
            if func.attr in WORKFLOW_CALLABLES:
                findings.append(
                    f"{_rel(path)}:{node.lineno}: calls .{func.attr}(...) inline "
                    "(workflow method, not enqueued)"
                )
            # `.delay(...)` / `.apply_async(...)` are the allowed enqueue path
            # and are intentionally not flagged.

    return findings


def test_no_inline_scraper_call_in_request_path() -> None:
    """No module under app/api/ may touch the blocking scraper directly."""

    findings: list[str] = []
    for path in _iter_py(API_DIR):
        findings.extend(_scan_for_inline_scraper_use(path))

    assert findings == [], (
        "The async request process (app/api/) must reach the scraper only via "
        "a Celery enqueue (.delay/.apply_async), never inline. Offending "
        "references:\n  " + "\n  ".join(findings)
    )


def test_blocking_scraper_confined_to_worker_layer() -> None:
    """BaseScraper + scrape_* stay in the scraper/workflow layer; the workflow
    service is only instantiated by the Celery task module."""

    # The scraper package may instantiate/recurse into itself; these services
    # are the external drivers of the blocking scrape methods, and all three
    # run ONLY inside Celery tasks (enforced below and by
    # test_no_inline_scraper_call_in_request_path: app/api/ reaches them
    # exclusively via .delay/.apply_async):
    #   - scraper_workflow_service: initial ingestion (process_*_scrape)
    #   - rescrape_service: staged full-series rescrape (1G.12.4)
    #   - scheduled_checks_service: periodic new-chapter checks (1G.12A),
    #     driven only by the run_scheduled_chapter_checks beat task
    scrape_pkg_prefix = "scrapers/"
    worker_driver_modules = {
        "services/scraper_workflow_service.py",
        "services/rescrape_service.py",
        "services/scheduled_checks_service.py",
    }

    base_scraper_sites: set[str] = set()
    scrape_call_sites: set[str] = set()
    workflow_instantiation_sites: set[str] = set()

    for path in _iter_py(APP_DIR):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                if func.id == "BaseScraper":
                    base_scraper_sites.add(_rel(path))
                if func.id == "ScraperWorkflowService":
                    workflow_instantiation_sites.add(_rel(path))
            if isinstance(func, ast.Attribute) and func.attr in BLOCKING_METHODS:
                scrape_call_sites.add(_rel(path))

    def _outside_scraper_layer(sites: set[str]) -> set[str]:
        return {
            s
            for s in sites
            if not s.startswith(scrape_pkg_prefix) and s not in worker_driver_modules
        }

    # BaseScraper is only constructed in the scraper package or its workflow.
    assert _outside_scraper_layer(base_scraper_sites) == set(), (
        "BaseScraper(...) escaped the scraper/workflow layer; found in: "
        f"{sorted(_outside_scraper_layer(base_scraper_sites))}"
    )
    # scrape_manga/scrape_chapter are only called inside the scraper package
    # (internal recursion) or by the workflow driver — never elsewhere.
    assert _outside_scraper_layer(scrape_call_sites) == set(), (
        "scrape_manga/scrape_chapter called outside the scraper/workflow "
        f"layer; found in: {sorted(_outside_scraper_layer(scrape_call_sites))}"
    )
    # The workflow (which owns the blocking calls) is only ever started by the
    # Celery task module — i.e. it runs in the prefork worker, not the API.
    assert workflow_instantiation_sites == {"tasks/scraper_tasks.py"}, (
        "ScraperWorkflowService(...) should be instantiated only in "
        "tasks/scraper_tasks.py (the Celery worker layer); found in: "
        f"{sorted(workflow_instantiation_sites)}"
    )

    # The staged-rescrape driver likewise runs only inside the Celery task
    # module — never inline from the API.
    staged_call_sites: set[str] = set()
    for path in _iter_py(APP_DIR):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run_staged_rescrape":
                staged_call_sites.add(_rel(path))
            if isinstance(func, ast.Name) and func.id == "run_staged_rescrape":
                staged_call_sites.add(_rel(path))
    assert staged_call_sites <= {"tasks/scraper_tasks.py"}, (
        "run_staged_rescrape(...) must only be driven from the Celery task "
        f"module; found in: {sorted(staged_call_sites)}"
    )

    # Likewise the scheduled-check driver (1G.12A) — never inline from the API.
    check_call_sites: set[str] = set()
    for path in _iter_py(APP_DIR):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else (func.id if isinstance(func, ast.Name) else None)
            )
            if name == "run_check" and "scheduled_checks" in path.name:
                continue  # internal recursion guard, not applicable here
            if name == "run_check":
                check_call_sites.add(_rel(path))
    assert check_call_sites <= {"tasks/scraper_tasks.py"}, (
        "scheduled_checks_service.run_check(...) must only be driven from "
        f"the Celery task module; found in: {sorted(check_call_sites)}"
    )
