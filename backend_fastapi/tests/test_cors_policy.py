"""CORS on a live site names its own address only (security checklist, 2026-10-03)."""

from __future__ import annotations

from types import SimpleNamespace

from backend_fastapi.app.bootstrap.middleware import resolve_cors_configuration


def _settings(**kw):
    base = dict(cors_allowed_origins=None, allowed_origins=None, frontend_url=None, force_https_redirects=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_production_without_origins_answers_no_other_site():
    assert resolve_cors_configuration(_settings(force_https_redirects=True)) == ([], False)


def test_production_drops_a_wildcard_and_keeps_named_origins():
    origins, credentials = resolve_cors_configuration(
        _settings(force_https_redirects=True, cors_allowed_origins=["*", "https://manga.example"])
    )
    assert origins == ["https://manga.example"] and credentials is True


def test_named_origin_allows_credentials():
    origins, credentials = resolve_cors_configuration(
        _settings(force_https_redirects=True, frontend_url="https://manga.example")
    )
    assert origins == ["https://manga.example"] and credentials is True


def test_local_development_keeps_the_open_default():
    assert resolve_cors_configuration(_settings()) == (["*"], False)
