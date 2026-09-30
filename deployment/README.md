# Deployment: web (frontend)

| Path | Purpose |
| --- | --- |
| `web.Dockerfile` | Builds the UI with Vite and serves it with nginx (used by `docker-compose.yml`) |
| `nginx/site.conf` | Site config baked into the web image: security headers, caching, proxying `/api/` |
| `nginx/nginx.conf`, `nginx/entrypoint.sh`, `nginx/config.json.template` | Main nginx config and runtime `/config.json` rendering |
| `manga-site.conf`, `manga-frontend.service` | Same setup without Docker (host nginx + systemd) |
| `manga-certbot.*`, `renew_certificates.*` | TLS certificate renewal |
| `runbook.md` | Source domain change, restore, key rotation, adding a source site |
| `updating.md` | How dependencies and images are pinned and updated |
| `key-rotation.md` | Encryption key rotation steps |

Backend deployment: [../backend_fastapi/deployment/](../backend_fastapi/deployment/README.md).
