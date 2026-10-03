# Deployment: web (frontend)

| Path | Purpose |
| --- | --- |
| `web.Dockerfile` | Builds the UI with Vite and serves it with nginx (used by `docker-compose.yml`) |
| `nginx/site.conf` | Site config baked into the web image: security headers, caching, proxying `/api/` |
| `nginx/nginx.conf`, `nginx/entrypoint.sh`, `nginx/config.json.template` | Main nginx config and runtime `/config.json` rendering |
| `runbook.md` | Source domain change, restore, key rotation, adding a source site |
| `updating.md` | How dependencies and images are pinned and updated |
| `key-rotation.md` | Encryption key rotation steps |

The site runs with Docker Compose behind Caddy only (GUIDE §8); Caddy fetches and renews
the HTTPS certificate. The old host-nginx + systemd files were removed: they could not start
(`nginx -t` failed) and their worker served only one queue.

Backend deployment: [../backend_fastapi/deployment/](../backend_fastapi/deployment/README.md).
