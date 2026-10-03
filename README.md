# Manga Reader

React UI (`src/`) on a FastAPI + Postgres + Redis + Celery backend
(`backend_fastapi/`). Read `backend_fastapi/README.md` for how imports, parsers,
picture compression and layouts work.

**Installing or running the site?**
- Trying it on your own computer, no domain: [`TEST_COMPUTER.md`](TEST_COMPUTER.md)
- The live server people visit (Linux, domain, HTTPS, backups): [`GUIDE.md`](GUIDE.md)

The commands below are the developer setup only.

```bash
cp .env.example .env                 # fill in the secrets
docker compose up -d db redis
alembic upgrade head
npm run backend                      # API on :8000
celery -A backend_fastapi.app.core.celery_app:celery_app worker -Q scrape,celery -l info
npm install && npm run dev           # UI on :3000
```

| Folder | Contents |
| --- | --- |
| `src/`, `public/` | The UI |
| `backend_fastapi/` | API, workers, scrapers, tests; `audit/` and `deployment/` for the backend |
| `deployment/` | Web image and nginx |
| `audit/` | Audit reports |
