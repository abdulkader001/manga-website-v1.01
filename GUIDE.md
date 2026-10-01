# Deployment Guide — Manga Reader

Step-by-step instructions to get the whole site running: website, API, database,
job workers (series import, chapter scraping, image compression, OCR,
translation, e-mail, notifications) and the admin account.

> This guide was written from the repo's own files (`docker-compose.yml`,
> `.env.example`, `server.ts`, `deployment/`, `backend_fastapi/`). Commands have
> not been run end-to-end on every OS, so treat the first run as a test and use
> the [Troubleshooting](#10-troubleshooting) table if something differs.

---

## 0. What you are deploying

| Piece | What it does | Runs as |
| --- | --- | --- |
| **Web UI** (`src/`) | React site, built with Vite | nginx (Docker) or `server.ts` (Node gateway) |
| **API** (`backend_fastapi/`) | FastAPI: auth, series, chapters, admin, SEO feeds | gunicorn on port 8000 |
| **PostgreSQL 14+** | All data | container or system service |
| **Redis 7** | Cache, rate limits, job queue | container or system service |
| **Celery workers** | Series import, scraping, WebP compression, OCR, translation, e-mail, notifications | one worker per queue |
| **Celery beat** | Scheduler: checks for new chapters on each series' schedule | 1 process |
| **Storage volume** | Compressed chapter pages, covers, branding, avatars | Docker volume / folder |

**All the "functions" (chapters, series, import, scraping) only work when the
API, database, Redis, the workers AND beat are all running.** If you start only
the website, pages load but imports and new chapters never happen.

### Where can it run?

| Target | Works? | Notes |
| --- | --- | --- |
| Ubuntu/Debian Linux server or VM | ✅ Best choice | Docker path below |
| Windows 10/11 | ✅ | Docker Desktop (WSL2), same commands |
| macOS | ✅ | Docker Desktop, same commands |
| Google Compute Engine / any cloud VM (AWS, Hetzner, DigitalOcean…) | ✅ | It's just Ubuntu — follow the Linux path |
| **Google AI Studio** | ❌ | AI Studio builds/runs small front-end prototypes. It cannot run PostgreSQL, Redis, Celery or long-running workers, so this full-stack site cannot be deployed there. Use a VM instead. |
| Google Cloud Shell | ⚠️ Testing only | Has Docker, but sessions are temporary and there is no public domain/HTTPS. Fine for a trial run. |

**Recommended server size:** 2 vCPU, 4 GB RAM, 40 GB+ disk (chapter images grow
fast — plan disk for your library).

---

## 1. Install the prerequisites

### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates openssl
# Docker Engine + Compose plugin (official convenience script)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER     # then log out and back in
docker --version && docker compose version
```

### Windows

1. Enable WSL2: open PowerShell as admin → `wsl --install` → reboot.
2. Install **Docker Desktop** (WSL2 backend) and **Git for Windows**.
3. Run every command in this guide inside an **Ubuntu (WSL) terminal**, and keep
   the project inside the WSL filesystem (`~/manga-website-v1.01`), not `C:\`.
   That avoids slow disks and Windows line-ending problems.

### macOS

```bash
brew install --cask docker     # then open Docker once and wait for "running"
brew install git openssl
```

---

## 2. Get the code

```bash
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

---

## 3. Create the `.env` file (all variables)

```bash
cp .env.example .env
```

Open `.env` in an editor. The file is big, but only the groups below need your
attention; everything else has a safe default.

> **Two places for settings.** `.env` holds only the server's foundation:
> the database and Redis connection, the site address (`FRONTEND_URL`,
> CORS, HTTPS), the signing/encryption keys and the admin identity
> (`MAIN_ADMIN_EMAIL_HASH`, 2-step login). **Everything else** — Google /
> Microsoft sign-in, SMTP and magic links, OCR and translation, API keys,
> Sentry, limits, image storage — is set later in the admin panel under
> **Admin → Secret Vault** (Section 6.1), encrypted in the database. A vault
> value overrides the same line in `.env`; removing it falls back to `.env`.
> You can still put those values in `.env` if you prefer — the vault is
> simply easier to change and never needs a file edit.

### 3.1 Generate the secrets

Run these and paste each output into the matching variable. **Every secret must
be different from the others.**

```bash
openssl rand -hex 32        # run 5 times: SECRET_KEY, JWT_SECRET_KEY,
                            #   MAGIC_LINK_SECRET, INTEGRATIONS_SECRET,
                            #   ADMIN_PROMOTION_SECRET
openssl rand -hex 16        # POSTGRES_PASSWORD
openssl rand -hex 16        # REDIS_PASSWORD

# EMAIL_ENCRYPTION_KEY (a Fernet key) — REQUIRED, compose refuses to start without it
docker run --rm python:3.11-slim sh -c \
  "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
# (or, if you have Python: pip install cryptography && the same python -c command)
```

### 3.2 Variables you MUST set

| Variable | Set it to | Why |
| --- | --- | --- |
| `SECRET_KEY` | random hex | Session signing. The template value is public — replace it. |
| `JWT_SECRET_KEY` | random hex | Login tokens. |
| `MAGIC_LINK_SECRET` | random hex | E-mail login links. |
| `INTEGRATIONS_SECRET` | random hex | Encrypts API keys you store in the admin panel. **If you lose it, stored keys become unreadable.** |
| `EMAIL_ENCRYPTION_KEY` | Fernet key (above) | Encrypts user e-mails in the database. **Back it up; losing it means losing every e-mail.** |
| `ADMIN_PROMOTION_SECRET` | random hex | Lets you create the first admin (Section 6). |
| `POSTGRES_PASSWORD` | random string | Database password. |
| `REDIS_PASSWORD` | random string | Redis password. |
| `DATABASE_URL` | `postgresql+psycopg2://manga:<POSTGRES_PASSWORD>@db:5432/manga` | Must contain the same password. Keep the `+psycopg2` part. |
| `REDIS_URL` | `redis://default:<REDIS_PASSWORD>@redis:6379/0` | Same password. |
| `CELERY_BROKER_URL` | `redis://default:<REDIS_PASSWORD>@redis:6379/1` | Same password. |
| `CELERY_RESULT_BACKEND` | `redis://default:<REDIS_PASSWORD>@redis:6379/2` | Same password. |

> ⚠ **Passwords with special characters** (`@ : / # $`) break the URLs. Stick to
> letters and digits (`openssl rand -hex 16` does). If a value contains `$`,
> wrap it in single quotes.

### 3.3 Variables for your domain (production)

Replace `localhost` with your real address everywhere it appears:

| Variable | Example |
| --- | --- |
| `FRONTEND_URL` | `https://manga.example.com` |
| `BACKEND_URL` / `BACKEND_ORIGIN` | `http://backend:8000` (inside Docker) |
| `ALLOWED_ORIGINS` | `https://manga.example.com` |
| `CORS_ALLOWED_ORIGINS` | `["https://manga.example.com"]` |
| `MAGIC_LINK_REDIRECT_URL` | `https://manga.example.com/auth/magic-complete` |
| `GOOGLE_OAUTH_REDIRECT_URI` | `https://manga.example.com/api/auth/google/callback` |
| `MICROSOFT_OAUTH_REDIRECT_URI` | `https://manga.example.com/api/v1/auth/microsoft/callback` |
| `REACT_APP_FRONTEND_URL` | `https://manga.example.com` |

### 3.4 Trying it locally over plain HTTP

By default `FORCE_HTTPS_REDIRECTS=true`, which expects TLS in front. For a
local trial on `http://localhost:8080` set:

```env
FORCE_HTTPS_REDIRECTS=false
ENVIRONMENT=development
APP_ENV=development
```

**Never leave `FORCE_HTTPS_REDIRECTS=false` on a public server** — the backend
refuses to start in production with it off, and cookies would be insecure.

### 3.5 Optional features (leave blank to disable)

All of these can be set in **Admin → Secret Vault** instead of `.env`
(recommended). The variable names are the same in both places.

| Feature | Variables | Notes |
| --- | --- | --- |
| **Real e-mail login links** | `EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `EMAIL_FROM_ADDRESS` | With the default `EMAIL_BACKEND=console`, magic links are **printed in the worker logs** instead of sent: `docker compose logs -f celery_worker_email`. |
| **Google sign-in** | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_PROJECT_ID` | Create an OAuth client in Google Cloud Console → *APIs & Services → Credentials*; add the redirect URI there exactly. |
| **Microsoft sign-in** | `MICROSOFT_OAUTH_CLIENT_ID`, `_CLIENT_SECRET`, `_REDIRECT_URI`, `_TENANT` | Empty client id hides the button. |
| **OCR (reading the text on pages)** | `OCR_ENABLED=true` | The backend image ships **Tesseract with Korean, Japanese and Chinese**; nothing else to install. Set the language per series (Series → layout → *Text language on pages*), or leave *Auto*. A remote OCR API is optional (`OCR_MODE=remote`, `REMOTE_OCR_URL`). |
| **Translation** | `TRANSLATION_ENABLED=true` + a provider | OCR only reads text; something must translate it. Easiest: each reader adds a free **Google Gemini** key in *Settings → AI & OCR Engines*. A site-wide default for everyone: Admin → API Management, or `TRANSLATION_API_URL` / `TRANSLATION_API_KEY` in the vault. |
| **Scraper AI** (writes parsers for unknown sites) | added in the admin panel → Series Management → Custom Parser | Not an `.env` value. |
| **Error tracking** | `SENTRY_DSN`, `ENABLE_SENTRY` | Set `ENABLE_SENTRY=false` if unused. |
| **Virus scanning of uploads** | `CLAMAV_HOST`, `CLAMAV_PORT` | Needs a ClamAV container. |
| **Image storage limits** | `PAGE_MAX_WIDTH` (1440), `MIRROR_PAGE_IMAGES` (true), `STORAGE_ALERT_PERCENT` (80) | Defaults are fine. |
| **Admin 2-step login** | `ADMIN_2FA_REQUIRED` | Leave `false` until the admin has enrolled at `/admin/security`. |

### 3.6 Sanity-check the file

```bash
docker compose config > /dev/null && echo "compose file OK"
```

If it errors with *Set EMAIL_ENCRYPTION_KEY*, fill that variable. The repo also
ships `backend_fastapi/deployment/check_env_placeholders.sh` to catch values you
forgot to replace.

---

## 4. Start everything (Docker — recommended, same on Linux/Windows/Mac)

```bash
docker compose up -d --build
```

This builds and starts, in order: PostgreSQL → Redis → **migrations** (creates
every table, seeds bootstrap state) → API → 8 Celery workers → Celery beat →
nginx + website.

First build takes several minutes. Watch progress:

```bash
docker compose ps                 # every service should become "healthy"/"running"
docker compose logs -f backend    # API log; Ctrl+C to leave
docker compose logs manga-stack-migrate   # should end without errors
```

Verify:

```bash
curl http://localhost:8000/healthz          # API alive
curl -I http://localhost:8080               # website alive (200)
```

Open **http://localhost:8080** in a browser.

| Port | Service |
| --- | --- |
| 8080 | Website (nginx) — this is the address users visit |
| 8000 | API directly (for debugging; don't expose publicly — put only 80/443 on the internet) |

### 4.1 Rebuild after pulling an update (installs Tesseract)

The backend image is where Tesseract and its Korean/Japanese/Chinese language
data are installed, so after `git pull` **rebuild it** — restarting is not
enough:

```bash
cd /path/to/manga-website            # the folder with docker-compose.yml
git pull

# 1. Rebuild the backend image (API, all Celery workers and beat share it).
#    --pull also refreshes the Python base image.
docker compose build --pull

# 2. Recreate every container on the new image. The one-shot
#    manga-stack-migrate service runs `alembic upgrade head` first, so new
#    database tables/columns are created before the API starts.
docker compose up -d --force-recreate

# 3. Check the migration finished without errors.
docker compose logs manga-stack-migrate | tail -n 20

# 4. Check Tesseract and its languages are in the image.
docker compose exec backend tesseract --list-langs
#    -> must list: chi_sim chi_tra eng jpn jpn_vert kor osd

# 5. Check everything is healthy.
docker compose ps
```

If the build ever seems to reuse an old image, force a clean one:

```bash
docker compose build --pull --no-cache
docker compose up -d --force-recreate
```

Run migrations by hand (normally not needed — step 2 does it):

```bash
docker compose run --rm manga-stack-migrate
```

After changing a vault setting marked **Restart** (e.g. `OCR_ENABLED`,
Sentry, rate limits):

```bash
docker compose restart backend celery_beat \
  celery_worker celery_worker_scrape celery_worker_compress celery_worker_ocr \
  celery_worker_translation celery_worker_email celery_worker_maintenance \
  celery_worker_notifications
```

Useful commands:

```bash
docker compose ps
docker compose logs -f <service>      # backend | celery_worker_scrape | celery_beat | web | db ...
docker compose restart backend
docker compose down                   # stop (data kept in volumes)
docker compose down -v                # stop AND DELETE database + images  ⚠
```

---

## 5. Alternative: run without Docker for the app (developer setup)

Use this if you want to edit code with hot reload. You still need PostgreSQL and
Redis — the easiest way is Docker for just those two.

1. **Node 22** (see `.nvmrc`) and **Python 3.11**:

   ```bash
   # Linux/macOS with nvm:
   nvm install 22 && nvm use 22
   sudo apt-get install -y python3.11 python3.11-venv libpq-dev   # Ubuntu
   ```

2. **Publish DB/Redis ports to your machine.** `docker-compose.yml` doesn't
   expose them, so create `docker-compose.override.yml` next to it:

   ```yaml
   services:
     db:
       ports: ["127.0.0.1:5432:5432"]
     redis:
       ports: ["127.0.0.1:6379:6379"]
   ```

   ```bash
   docker compose up -d db redis
   ```

3. **Point `.env` at localhost** (instead of `db` / `redis`):

   ```env
   DATABASE_URL=postgresql+psycopg2://manga:<POSTGRES_PASSWORD>@localhost:5432/manga
   REDIS_URL=redis://default:<REDIS_PASSWORD>@localhost:6379/0
   CELERY_BROKER_URL=redis://default:<REDIS_PASSWORD>@localhost:6379/1
   CELERY_RESULT_BACKEND=redis://default:<REDIS_PASSWORD>@localhost:6379/2
   REDIS_HOST=localhost
   BACKEND_URL=http://127.0.0.1:8000
   FORCE_HTTPS_REDIRECTS=false
   ```

4. **Python environment and migrations:**

   ```bash
   python3.11 -m venv .venv && source .venv/bin/activate
   pip install -r backend_fastapi/requirements.lock
   export PYTHONPATH=$PWD/backend_fastapi:$PWD
   set -a && source .env && set +a           # load the variables into this shell
   alembic upgrade head
   python backend_fastapi/scripts/seed_bootstrap_state.py
   ```

5. **Run each process in its own terminal** (activate the venv and load `.env`
   in each):

   ```bash
   # Terminal 1 — API
   npm run backend

   # Terminal 2 — worker consuming every queue
   celery -A backend_fastapi.app.core.celery_app:celery_app worker \
     -Q default,celery,scrape,compress,ocr,translation,email,maintenance,notifications -l info

   # Terminal 3 — scheduler (REQUIRED for automatic new-chapter checks)
   celery -A backend_fastapi.app.core.celery_app:celery_app beat -l info

   # Terminal 4 — website + gateway
   npm install
   npm run dev          # http://localhost:3000
   ```

   > The README's shorter worker command (`-Q scrape,celery`) only handles
   > scraping. The full queue list above is needed for image compression,
   > OCR, translation, e-mail and notifications.

**Windows note:** run all of this inside WSL2. Native Windows can't run the
Celery worker reliably.

---

## 6. Create the first admin account

Nobody is admin on a fresh install. Do this once:

1. Make sure `ADMIN_PROMOTION_SECRET` is set in `.env` (Section 3.2).
2. Open the website and **sign up / log in** with the e-mail you want as admin
   (with `EMAIL_BACKEND=console`, read the link from
   `docker compose logs celery_worker_email`).
3. Generate a one-time promotion token:

   ```bash
   docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap \
     issue-admin-token --email you@example.com
   ```

   It prints a token (valid 30 min by default).
4. Redeem it:

   ```bash
   docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap \
     promote-user --token <TOKEN> --email you@example.com
   ```

5. Log out and in again. The admin menu now appears.
6. Afterwards: empty `ADMIN_PROMOTION_SECRET` (or rotate it), keep
   `MAIN_ADMIN_AUTO_PROMOTE_ENABLED=false`, then enroll 2-step login at
   `/admin/security` and set `ADMIN_2FA_REQUIRED=true`.

(Non-Docker: same commands without `docker compose exec backend`, venv active.)

### 6.1 Move the remaining settings into the Secret Vault

1. As the admin, open **`/admin/security`** and enrol an authenticator app
   (Google Authenticator, Aegis, 1Password …). The vault refuses to open
   without it.
2. Open **Admin → Secret Vault**, enter a 6-digit code to unlock it (10
   minutes), and set what you need — at minimum:
   - **Translation & OCR → Server OCR enabled = true** (then restart, 4.1);
   - **Email & magic links** (SMTP) if you want real login e-mails;
   - **Google / Microsoft sign-in** if you use them.
3. Once a value is in the vault you can delete that line from `.env`. Keep
   `.env` itself (and a private backup of it): without `INTEGRATIONS_SECRET`
   the vault cannot be decrypted.

---

## 7. Start using the site's functions

All of this is in the **admin area** once you are logged in as admin.

### Import a series and its chapters

1. Admin → Series → **Import & Scrape Manga**.
2. Enter the **MangaUpdates link** (metadata: title, description, genres, cover)
   and the **source series URL** (where chapters/images come from).
3. Choose **Page Layout** (auto / vertical strips / book format / one page per
   chapter). Click **Test & Live Preview** — it must show a title, chapter
   count and page images. Nothing is saved yet.
4. Click **Start Auto-Scrape**. The `scrape` and `compress` workers fetch every
   chapter and convert the pages to WebP. Follow it with:

   ```bash
   docker compose logs -f celery_worker_scrape celery_worker_compress
   ```
5. New chapters are then picked up automatically by **celery_beat** on the
   series' schedule (set per series in the admin panel).

If the preview finds nothing, the site isn't covered by a built-in parser: use
**Custom Parser** (needs a Scraper AI key added in that panel). Details and
the list of supported/unsupported sources: `backend_fastapi/README.md` and
`deployment/runbook.md`. Only import content you have the rights to host.

### Other features

| Feature | Needs |
| --- | --- |
| Browse, search, ratings, bookmarks, comments | API + DB (works out of the box) |
| Magic-link / Google / Microsoft login | E-mail or OAuth variables (Section 3.5) + `celery_worker_email` |
| Page translation overlay | Vault: *Server OCR enabled*; a translator (reader's own AI key in *Settings → AI & OCR Engines*, or a site default in Admin → API Management). Readers switch it on once in *Settings → Reading & Translation*. |
| Translated chapter names | Same translator as the overlay. Source names like `522 원준 522화 2024-11-07` show as `Chapter 522`; real subtitles are translated and cached. |
| Notifications, storage alerts | `celery_worker_notifications`, `celery_worker_maintenance`, beat |
| Ads, branding, announcements, maintenance mode | Admin → Site settings |
| Backups | Section 9 |

---

## 8. Go live on a Linux server with a domain and HTTPS

1. **Server:** Ubuntu 22.04/24.04 VM, open ports **22, 80, 443** only (firewall
   / cloud security group). Do **not** expose 8000, 5432 or 6379.
2. **DNS:** create an `A` record `manga.example.com → <server IP>`.
3. Install Docker and clone the repo (Sections 1–2) on the server, e.g. in
   `/var/www/manga`.
4. Build `.env` with your real domain values (Section 3.3).
   - Keep `FORCE_HTTPS_REDIRECTS=true`.
   - If you want production mode (`APP_ENV=production`, `ENVIRONMENT=production`):
     note `docker-compose.yml` hard-codes `APP_ENV: development` in several
     services' `environment:` blocks — change those to `production` too, or
     the stack keeps running in development mode. Production mode also enforces
     stricter secret checks, so all secrets in Section 3.2 must be real.
   - If a load balancer / proxy sits in front, add its network range to
     `TRUSTED_PROXY_CIDRS`.
5. `docker compose up -d --build` (Section 4).
6. **TLS termination.** The compose `web` container speaks plain HTTP on 8080,
   so put a TLS reverse proxy in front. Simplest with Caddy on the host:

   ```bash
   sudo apt-get install -y caddy
   sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
   manga.example.com {
       reverse_proxy 127.0.0.1:8080
   }
   EOF
   sudo systemctl reload caddy
   ```

   Caddy fetches and renews Let's Encrypt certificates automatically and sends
   `X-Forwarded-Proto`, which the backend uses to avoid redirect loops.
   (Prefer nginx + certbot? See `deployment/manga-site.conf`,
   `deployment/renew_certificates.md` and the `manga-certbot.*` units.)
7. **Start on boot:** containers already use `restart: unless-stopped`; make sure
   Docker itself starts on boot: `sudo systemctl enable docker`.
   (`backend_fastapi/deployment/setup-server.sh` also installs a
   `manga-compose` systemd unit if you want that.)
8. Test: open `https://manga.example.com`, log in, run an import.

### Updating later

Same as Section 4.1:

```bash
cd /var/www/manga
git pull
docker compose build --pull
docker compose up -d --force-recreate   # migrations run automatically first
docker compose exec backend tesseract --list-langs
```

---

## 9. Backups (do this before you add content)

Three things hold your site's state:

| What | Where | Back it up with |
| --- | --- | --- |
| Database | `db-data` volume | `backend_fastapi/deployment/backup_postgres.sh` |
| Chapter images/covers | `app-storage` volume | `backend_fastapi/deployment/backup_storage.sh` |
| **Your `.env`** (esp. `EMAIL_ENCRYPTION_KEY`, `INTEGRATIONS_SECRET`) | the server | copy it somewhere safe and private — without these keys, encrypted data cannot be recovered |

Scheduled runs: `backend_fastapi/deployment/manga-backup.timer`. Restore
procedure: `backend_fastapi/deployment/backups.md` and `deployment/runbook.md`.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Set EMAIL_ENCRYPTION_KEY to a Fernet key` | Fill `EMAIL_ENCRYPTION_KEY` (Section 3.1). |
| Backend exits at startup about `FORCE_HTTPS_REDIRECTS` | You're in production mode with it `false`. Enable TLS, or use development mode (Section 3.4). |
| Site loads but login/redirects loop on plain `http://localhost` | `FORCE_HTTPS_REDIRECTS` is still `true`; set `false` for local only. |
| `password authentication failed` (DB) or Redis `NOAUTH` | Passwords in `DATABASE_URL` / `REDIS_URL` / `CELERY_*` don't match `POSTGRES_PASSWORD` / `REDIS_PASSWORD`. After changing the DB password on an existing volume, run `docker compose down -v` (deletes data) or change it inside Postgres. |
| `ModuleNotFoundError: psycopg` | `DATABASE_URL` must start `postgresql+psycopg2://`. |
| Imports stay "queued" forever | Workers or beat not running: `docker compose ps`; for non-Docker, start the worker with **all** queues (Section 5). |
| Chapter has no pictures / slow | Check `celery_worker_compress` logs; ensure enough disk (`docker system df`). |
| `$argon2id...` value turns into garbage | Wrap values containing `$` in single quotes in `.env`. |
| Translation/OCR overlay does nothing | Reader: *Settings → Reading & Translation* must be on. Server: vault *Server OCR enabled* = true and restarted (4.1). |
| Reader says "Text was found but not translated" | OCR works but nothing translates: add an AI key in *Settings → AI & OCR Engines* (press **Test connection**), or a site default in Admin → API Management. |
| `tesseract: not found` / OCR "engine not available" | The backend image is old: rebuild it (Section 4.1) and check `docker compose exec backend tesseract --list-langs`. |
| Korean/Chinese pages read as garbage | Set the series' *Text language on pages* (Series → layout) to the language actually printed on the pages. |
| Secret Vault says "Set up your authenticator app" | Enrol 2-step login at `/admin/security` first (Section 6.1). |
| Port already in use | Another program uses 8080/8000/5432; stop it or change the published port in `docker-compose.yml`. |
| Windows: `exec ... no such file or directory` in a container | Line endings; clone inside WSL (Section 1) or run `git config core.autocrlf false` before cloning. |
| API docs (`/docs`) missing | Intentional in production; set `EXPOSE_API_DOCS=true` on a private deploy. |

---

## 11. Quick checklist

- [ ] Docker installed, `docker compose version` works
- [ ] `.env` created; 6 random secrets + 2 passwords + Fernet key set; URLs/passwords consistent
- [ ] `docker compose build --pull && docker compose up -d --force-recreate`; all services healthy
- [ ] `docker compose exec backend tesseract --list-langs` lists `kor jpn chi_sim`
- [ ] Authenticator enrolled; OCR, e-mail and sign-in settings entered in **Admin → Secret Vault**
- [ ] First admin created and promoted (Section 6)
- [ ] First series imported; new chapters arrive via beat
- [ ] Domain + HTTPS in front (production)
- [ ] `.env` and backups stored safely off the server

More detail: `README.md`, `backend_fastapi/README.md`, `deployment/README.md`,
`deployment/runbook.md`, `deployment/key-rotation.md`.
