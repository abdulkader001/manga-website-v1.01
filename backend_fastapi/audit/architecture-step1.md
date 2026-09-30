# Backend Architecture – Step 1 (Structure Review)

This refactor introduces a dedicated `app/bootstrap/` layer that isolates startup wiring from business/domain logic.

## New backend folder structure

```text
backend_fastapi/app/
├── api/
│   └── routers/            # HTTP entrypoints (controllers)
├── bootstrap/              # App wiring and runtime composition (NEW)
│   ├── __init__.py
│   ├── lifecycle.py        # DB/Redis/Celery startup-shutdown orchestration
│   ├── middleware.py       # Middleware classes + CORS/rate limit config
│   ├── observability.py    # Sentry + env helper wiring
│   ├── providers.py        # Integration vault + OCR/translation provider setup
│   └── routers.py          # API router composition/mounting
├── controllers/            # Legacy domain controllers
├── core/                   # Infrastructure primitives (DB, settings, celery)
├── dependencies/           # FastAPI dependencies
├── models/                 # ORM models
├── schemas/                # DTOs / API schemas
├── services/               # Domain/application services
├── tasks/                  # Celery/background jobs
├── utils/                  # Reusable technical helpers
└── main.py                 # Thin app factory entrypoint
```

## Why this improves scalability

- **Single responsibility at startup:** `main.py` now only orchestrates module calls.
- **Clear boundaries:** Middleware, lifecycle management, observability, provider wiring, and router mounting are separated.
- **Lower merge conflicts:** Startup concerns are split across focused files.
- **Easier testing:** Bootstrap modules can be unit-tested independently.
- **Future-ready lifecycle:** application startup/shutdown now uses FastAPI lifespan flow instead of deprecated `on_event` hooks.

## Core design principle

- Routers/controllers handle HTTP.
- Services handle business logic.
- Utilities expose reusable technical helpers.
- Bootstrap coordinates runtime composition without leaking domain logic.
