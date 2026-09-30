def test_imports_smoke():
    import backend_fastapi.app.main as main_module
    from backend_fastapi.app.core.celery_app import celery_app

    assert hasattr(main_module, "app")
    assert "scraper-cleanup-stuck-jobs" in celery_app.conf.beat_schedule
