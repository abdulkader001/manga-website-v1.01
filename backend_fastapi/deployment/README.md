# Deployment: backend

| Path | Purpose |
| --- | --- |
| `gunicorn.conf.py`, `logging.conf` | API server settings (loaded by `scripts/start_backend.sh`) |
| `docker-compose.scale.yml` | Overlay that runs one Celery worker per queue: `docker compose -f docker-compose.yml -f backend_fastapi/deployment/docker-compose.scale.yml up -d` |
| `k8s/` | Kubernetes manifests: API, Celery worker/beat, migrate job |
| `manga-compose.service` | systemd unit that starts the Docker Compose stack on boot |
| `setup-server.sh`, `migrate.sh`, `check_env_placeholders.sh` | Server bootstrap and migrations |
| `backup_*.sh`, `restore_*.sh`, `verify_*_restore.sh`, `run_backups.sh`, `run_backup_verification.sh`, `manga-backup*.service/.timer`, `backups.md` | Postgres, Redis and pictures backups, scheduled runs, restore tests and the written restore drill |
| `monitoring.sh` | Endpoint uptime polling |

Web/nginx deployment: [../../deployment/](../../deployment/README.md).
