"""Task package exports with lazy loading to avoid import cycles."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "flush_audit": ("backend_fastapi.app.tasks.audit_tasks", "flush_audit"),
    "log_admin_audit": ("backend_fastapi.app.tasks.audit_tasks", "log_admin_audit"),
    "echo": ("backend_fastapi.app.tasks.echo", "echo"),
    "send_magic_link_email": (
        "backend_fastapi.app.tasks.email_tasks",
        "send_magic_link_email",
    ),
    "daily_integrity_scan": (
        "backend_fastapi.app.tasks.pdf_tasks",
        "daily_integrity_scan",
    ),
    "delete_chapter_pages_only": (
        "backend_fastapi.app.tasks.scraper_tasks",
        "delete_chapter_pages_only",
    ),
    "rescrape_chapter": ("backend_fastapi.app.tasks.scraper_tasks", "rescrape_chapter"),
    "rescrape_series": ("backend_fastapi.app.tasks.scraper_tasks", "rescrape_series"),
    "run_fast_scrape": ("backend_fastapi.app.tasks.scraper_tasks", "run_fast_scrape"),
    "report_manga_count_metric": (
        "backend_fastapi.app.tasks.scraper_tasks",
        "report_manga_count_metric",
    ),
    "run_scheduled_scrape": (
        "backend_fastapi.app.tasks.scraper_tasks",
        "run_scheduled_scrape",
    ),
    "scrape_chapter_by_url": (
        "backend_fastapi.app.tasks.scraper_tasks",
        "scrape_chapter_by_url",
    ),
    "scrape_series_by_url": (
        "backend_fastapi.app.tasks.scraper_tasks",
        "scrape_series_by_url",
    ),
    "sync": ("backend_fastapi.app.tasks.scraper_tasks", "sync"),
    "generate_user_suggestions": (
        "backend_fastapi.app.tasks.suggestion_tasks",
        "generate_user_suggestions",
    ),
    "scan": ("backend_fastapi.app.tasks.suggestion_tasks", "scan"),
    "email_service": ("backend_fastapi.app.services", "email_service"),
}

_ALIASES = {
    "send_magic_link_email_task": "send_magic_link_email",
    "log_admin_audit_task": "log_admin_audit",
    "refresh_pdf_integrity_task": "daily_integrity_scan",
    "run_scheduled_scrape_task": "run_scheduled_scrape",
    "run_fast_scrape_task": "run_fast_scrape",
    "run_full_reindex_task": "report_manga_count_metric",
    "scrape_series_by_url_task": "scrape_series_by_url",
    "scrape_chapter_by_url_task": "scrape_chapter_by_url",
    "rescrape_series_task": "rescrape_series",
    "rescrape_chapter_task": "rescrape_chapter",
    "delete_chapter_pages_only_task": "delete_chapter_pages_only",
}


def __getattr__(name: str):
    target = _ALIASES.get(name, name)
    if target in _EXPORTS:
        module_name, attr_name = _EXPORTS[target]
        value = getattr(import_module(module_name), attr_name)
        globals()[target] = value
        if name in _ALIASES:
            globals()[name] = value
        return value
    if name == "default_app_tasks":
        value = {
            "audit": __getattr__("flush_audit"),
            "email": __getattr__("send_magic_link_email"),
            "echo": __getattr__("echo"),
            "pdf": __getattr__("daily_integrity_scan"),
            "suggestions": __getattr__("scan"),
            "scraper": __getattr__("sync"),
        }
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = sorted((*_EXPORTS.keys(), *_ALIASES.keys(), "default_app_tasks"))
