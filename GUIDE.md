# Deployment Guide — Manga Reader (Ubuntu)

Step-by-step instructions to get the whole site running on **Ubuntu 22.04 or
24.04** (Debian 12 works the same): website, API, database, job workers
(series import, chapter scraping, image compression, OCR, translation, e-mail,
notifications) and the admin account.

> **How these commands were checked.** On Ubuntu 24.04 this was run for real:
> the `.env` generator, the admin-hash tool, every database migration on
> PostgreSQL 16 (up to `20261014_four_roles`), the API, a worker on all nine
> queues, the scheduler, the web gateway, the `apt` package names, the Caddyfile
> (`caddy validate`) and both Compose files (`docker compose config`, Compose
> v5). **Not run:** the Docker image builds, and anything that needs the
> internet from your server (Docker's installer, NodeSource, Let's Encrypt).
> Treat the first run as a test and use [Troubleshooting](#10-troubleshooting)
> if something differs.
>
> **Two documents, kept up to date with every change:**
> - **`GUIDE.md`** (this file) is *how to run the site*.
> - **[`AUDIT_LOG.md`](AUDIT_LOG.md)** is *what was changed, why, and how to undo it*. It also has a one-page map of the site, the database migration ledger, and rollback steps.
>
> Updating an existing site? Go to [Section 12](#12-updating-safely-and-rolling-back).
>
> **First install? A shorter walk-through is in [`guide/`](guide/README.md):**
> [Linux](guide/INSTALL-LINUX.md) (same steps as here, fewer options),
> [Windows](guide/INSTALL-WINDOWS.md), [macOS](guide/INSTALL-MACOS.md). This file
> is the full reference behind them.

All commands below are run in a terminal on the Ubuntu machine (on a server:
your SSH session), from the project folder `~/manga-website-v1.01` unless a
step says otherwise. Lines starting with `#` are comments; copying them is
harmless.

---

## 0. What you are deploying

| Piece | What it does | Runs as |
| --- | --- | --- |
| **Web UI** (`src/`) | React site, built with Vite | nginx (Docker) or `server.ts` (Node gateway, developer setup) |
| **API** (`backend_fastapi/`) | FastAPI: auth, series, chapters, admin, SEO feeds | gunicorn on port 8000 |
| **PostgreSQL 14+** | All data | container |
| **Redis 7** | Cache, rate limits, job queue | container |
| **Celery workers** | Series import, scraping, WebP compression, OCR, translation, e-mail, notifications | one worker per queue (8 containers; 2 on a small server) |
| **Celery beat** | Scheduler: checks for new chapters on each series' schedule | 1 container |
| **Storage volume** | Compressed chapter pages, covers, branding, avatars, backups | Docker volume `app-storage` |

**All the "functions" (chapters, series, import, scraping) only work when the
API, database, Redis, the workers AND beat are all running.** If you start only
the website, pages load but imports and new chapters never happen.

### Where can it run?

| Target | Works? | Notes |
| --- | --- | --- |
| **Ubuntu 22.04 / 24.04 LTS (64-bit), server or desktop** | ✅ Best choice | This guide |
| Debian 12 | ✅ | Same commands |
| Google Compute Engine / any cloud VM (AWS, Hetzner, DigitalOcean…) | ✅ | It's just Ubuntu: follow this guide |
| Windows 10/11, macOS | ✅ | Use [`guide/INSTALL-WINDOWS.md`](guide/INSTALL-WINDOWS.md) / [`guide/INSTALL-MACOS.md`](guide/INSTALL-MACOS.md); after the install, the rest of this file applies (inside the Ubuntu/WSL terminal on Windows) |
| **Google AI Studio** | ❌ | AI Studio builds/runs small front-end prototypes. It cannot run PostgreSQL, Redis, Celery or long-running workers, so this full-stack site cannot be deployed there. Use a VM instead. |
| Google Cloud Shell | ⚠️ Testing only | Has Docker, but sessions are temporary and there is no public domain/HTTPS. Fine for a trial run. |

**Recommended server size:** 2 vCPU, 4 GB RAM, 40 GB+ disk (chapter images grow
fast — plan disk for your library). A 1 GB / 1 vCPU server works with the
small profile ([Section 4.2](#42-small-server-about-1-gb-ram-1-cpu)) and a swap
file ([Section 1](#1-install-the-prerequisites-ubuntu)).

### The short version (trial on this machine)

```bash
sudo apt-get update && sudo apt-get install -y git curl ca-certificates python3
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker "$USER"
# log out and back in, then:
git clone https://github.com/abdulkader001/manga-website-v1.01.git && cd manga-website-v1.01
python3 backend_fastapi/scripts/make_env.py --local && chmod 600 .env
docker compose up -d --build
curl http://localhost:8000/healthz          # {"ok":true}
```

Open <http://localhost:8080>. Then continue at
[Section 6](#6-create-the-first-admin-account-one-time-admin-sign-in). A real
server with a domain and HTTPS: [Section 8](#8-go-live-on-a-linux-server-with-a-domain-and-https).

---

## 1. Install the prerequisites (Ubuntu)

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates openssl python3
```

Docker Engine and the Compose plugin (Docker's official installer; it also
enables the Docker service at boot):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

**Log out and back in** (on a server: close the SSH window and connect again)
so the group change takes effect. For the current terminal only, `newgrp docker`
also works. Then check:

```bash
docker --version
docker compose version        # must be v2.24 or newer: Section 8 relies on it
docker run --rm hello-world
```

*"permission denied … docker.sock"* means you have not logged out and in yet.
*"docker: 'compose' is not a docker command"* means the Compose plugin is
missing; Ubuntu's own `docker.io` package does not include it. Either use the
installer above, or on Ubuntu 24.04 install both from Ubuntu's repository:
`sudo apt-get install -y docker.io docker-compose-v2`.

### Optional but recommended on a server

**Keep Docker's logs from filling the disk.** By default container logs grow
forever. Set a cap *before* the first start (it applies to containers created
afterwards; restarting Docker briefly stops running containers):

```bash
test -f /etc/docker/daemon.json && echo "daemon.json exists: add the log-opts by hand" || {
  sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
  sudo systemctl restart docker
}
```

**Swap file on a server with 2 GB RAM or less.** Building the images
(`npm ci`, the front-end build, installing the Python packages) needs more
memory than the running site. Without swap the kernel may kill the build
(`Killed`, exit code 137):

```bash
free -h                                  # is there already swap?
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 2. Get the code

```bash
cd ~
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

Every command from here on runs **inside this folder**. In a new terminal,
first `cd ~/manga-website-v1.01`.

---

## 3. Create the `.env` file (all variables)

> **Two places for settings.** `.env` holds only the server's foundation:
> the database and Redis connection, the site address (`FRONTEND_URL`,
> CORS, HTTPS), the signing/encryption keys and the admin identity
> (`MAIN_ADMIN_EMAIL_HASH`, `MAIN_ADMIN_PASSWORD_HASH`). **Everything else** — Google /
> Microsoft sign-in, SMTP and magic links, OCR and translation, API keys,
> Sentry, limits, image storage — is set later in the admin panel under
> **Admin → Secret Vault** (Section 6.1), encrypted in the database. A vault
> value overrides the same line in `.env`; removing it falls back to `.env`.
> You can still put those values in `.env` if you prefer — the vault is
> simply easier to change and never needs a file edit.

### 3.1 Create the file with fresh secrets

One command creates `.env` from `.env.example` with new random secrets and
database/Redis passwords that match inside the URLs. It never overwrites an
existing `.env`.

```bash
python3 backend_fastapi/scripts/make_env.py --local   # trying it on this machine, http://localhost:8080
# or, for a real server with a domain and HTTPS (then do Section 3.3):
python3 backend_fastapi/scripts/make_env.py

chmod 600 .env        # the file holds every secret; only you should read it
```

It prints `Created …/.env with new random secrets.` **Copy `.env` somewhere
safe and private** (password manager, encrypted USB): losing `EMAIL_ENCRYPTION_KEY`
or `INTEGRATIONS_SECRET` makes the stored e-mails and API keys unreadable.

*By hand instead* (`cp .env.example .env`, then):

```bash
openssl rand -hex 32        # run 4 times: SECRET_KEY, JWT_SECRET_KEY,
                            #   MAGIC_LINK_SECRET, INTEGRATIONS_SECRET
openssl rand -hex 16        # POSTGRES_PASSWORD
openssl rand -hex 16        # REDIS_PASSWORD
# EMAIL_ENCRYPTION_KEY (a Fernet key; plain Python, nothing to install):
python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
```

Every secret must be different from the others.

### 3.2 What the secrets and passwords are

| Variable | Set it to | Why |
| --- | --- | --- |
| `SECRET_KEY` | random hex | Session signing. The template value is public — replace it. |
| `JWT_SECRET_KEY` | random hex | Login tokens. |
| `MAGIC_LINK_SECRET` | random hex | E-mail login links. |
| `INTEGRATIONS_SECRET` | random hex | Encrypts API keys you store in the admin panel. **If you lose it, stored keys become unreadable.** |
| `EMAIL_ENCRYPTION_KEY` | Fernet key (above) | Encrypts user e-mails in the database. **Back it up; losing it means losing every e-mail.** Compose refuses to start without it. |
| `POSTGRES_PASSWORD` | random string | Database password. |
| `REDIS_PASSWORD` | random string | Redis password. |
| `DATABASE_URL` | `postgresql+psycopg2://manga:<POSTGRES_PASSWORD>@db:5432/manga` | Must contain the same password. Keep the `+psycopg2` part. |
| `REDIS_URL` | `redis://default:<REDIS_PASSWORD>@redis:6379/0` | Same password. |
| `CELERY_BROKER_URL` | `redis://default:<REDIS_PASSWORD>@redis:6379/1` | Same password. |
| `CELERY_RESULT_BACKEND` | `redis://default:<REDIS_PASSWORD>@redis:6379/2` | Same password. |

`make_env.py` fills all of these. After changing the database password of a
site that has already run, the old password stays inside the database volume:
see the Troubleshooting row *password authentication failed*.

> ⚠ **Passwords with special characters** (`@ : / # $`) break the URLs. Stick to
> letters and digits (`openssl rand -hex 16` does). If a value contains `$`,
> wrap it in single quotes.

### 3.3 Variables for your domain (production)

Skip this on a local trial. For a real domain, replace `localhost` with your
address. One command does the address lines (set `DOMAIN` first; it also
switches the server to production mode):

```bash
DOMAIN=manga.example.com
sed -i \
  -e "s#^CORS_ALLOWED_ORIGINS=.*#CORS_ALLOWED_ORIGINS=[\"https://$DOMAIN\"]#" \
  -e "s#http://localhost:8080#https://$DOMAIN#g" \
  -e "s#http://127.0.0.1:8080#https://$DOMAIN#g" \
  -e "s#http://localhost:8000/api/auth/google/callback#https://$DOMAIN/api/auth/google/callback#" \
  -e "s#http://localhost:3000/api/v1/auth/microsoft/callback#https://$DOMAIN/api/v1/auth/microsoft/callback#" \
  -e "s#^BACKEND_URL=.*#BACKEND_URL=http://backend:8000#" \
  -e "s#^BACKEND_ORIGIN=.*#BACKEND_ORIGIN=http://backend:8000#" \
  -e "s#^APP_ENV=.*#APP_ENV=production#" \
  -e "s#^ENVIRONMENT=.*#ENVIRONMENT=production#" \
  .env
grep -nE '^(APP_ENV|ENVIRONMENT|FORCE_HTTPS_REDIRECTS|FRONTEND_URL|ALLOWED_ORIGINS|CORS_ALLOWED_ORIGINS|MAGIC_LINK_REDIRECT_URL|GOOGLE_OAUTH_REDIRECT_URI|MICROSOFT_OAUTH_REDIRECT_URI|BACKEND_URL)=' .env
```

The result should match this table (edit by hand with `nano .env` if not):

| Variable | Value |
| --- | --- |
| `FRONTEND_URL` | `https://manga.example.com` |
| `BACKEND_URL` / `BACKEND_ORIGIN` | `http://backend:8000` (inside Docker) |
| `ALLOWED_ORIGINS` | `https://manga.example.com` |
| `CORS_ALLOWED_ORIGINS` | `["https://manga.example.com"]` |
| `MAGIC_LINK_REDIRECT_URL` | `https://manga.example.com/auth/magic-complete` |
| `GOOGLE_OAUTH_REDIRECT_URI` | `https://manga.example.com/api/auth/google/callback` |
| `MICROSOFT_OAUTH_REDIRECT_URI` | `https://manga.example.com/api/v1/auth/microsoft/callback` |
| `REACT_APP_FRONTEND_URL` | `https://manga.example.com` |
| `FORCE_HTTPS_REDIRECTS` | `true` (leave it) |
| `APP_ENV` / `ENVIRONMENT` | `production` |

`APP_ENV=production` in `.env` alone does nothing in Docker: `docker-compose.yml`
sets `APP_ENV: development` itself. [Section 8](#8-go-live-on-a-linux-server-with-a-domain-and-https)
step 5 adds the small file that fixes this without editing `docker-compose.yml`.
Production mode also enforces stricter secret checks; `make_env.py` already
made them real.

### 3.4 Trying it locally over plain HTTP

`make_env.py --local` already sets this. If you made `.env` another way: by
default `FORCE_HTTPS_REDIRECTS=true`, which expects TLS in front. For a trial on
`http://localhost:8080` set:

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
| **Real e-mail login links** | `EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `EMAIL_FROM_ADDRESS` | With the default `EMAIL_BACKEND=console`, magic links are **printed in the worker logs** instead of sent: `docker compose logs -f celery_worker_email` (small profile: `celery_worker`). |
| **Google sign-in** | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_PROJECT_ID` | Create an OAuth client in Google Cloud Console → *APIs & Services → Credentials*; add the redirect URI there exactly. Step by step: [`GOOGLE_LOGIN_SETUP.md`](GOOGLE_LOGIN_SETUP.md). |
| **Microsoft sign-in** | `MICROSOFT_OAUTH_CLIENT_ID`, `_CLIENT_SECRET`, `_REDIRECT_URI`, `_TENANT` | Empty client id hides the button. |
| **OCR (reading the text on pages)** | `OCR_ENABLED=true` | The backend image ships **Tesseract with Korean, Japanese and Chinese**; nothing else to install. Set the language per series (Series → layout → *Text language on pages*), or leave *Auto*. A remote OCR API is optional (`OCR_MODE=remote`, `REMOTE_OCR_URL`). |
| **Translation** | `TRANSLATION_ENABLED=true` + a provider | OCR only reads text; something must translate it. Easiest: each reader adds a free **Google Gemini** key in *Settings → AI & OCR Engines*. A site-wide default for everyone: Admin → API Management, or `TRANSLATION_API_URL` / `TRANSLATION_API_KEY` in the vault. |
| **Scraper AI** (writes parsers for unknown sites) | added in the admin panel → Series Management → Custom Parser | Not an `.env` value. |
| **Error tracking** | `SENTRY_DSN`, `ENABLE_SENTRY` | Set `ENABLE_SENTRY=false` if unused. |
| **Virus scanning of uploads** | `CLAMAV_HOST`, `CLAMAV_PORT` | Needs a ClamAV container. |
| **Image storage limits** | `PAGE_MAX_WIDTH` (1440), `MIRROR_PAGE_IMAGES` (true), `STORAGE_ALERT_PERCENT` (80) | Defaults are fine. |
| **Memory and speed tuning** | `GUNICORN_WORKERS`, `GUNICORN_MAX_REQUESTS`, `CELERY_MAX_TASKS_PER_CHILD`, `CELERY_MAX_MEMORY_PER_CHILD_KB`, `PAGE_PROCESSING_CONCURRENCY` | Read when a process starts (before the vault loads), so they stay in `.env`. Section 4.2. |

### 3.6 Sanity-check the file

```bash
docker compose config > /dev/null && echo "compose file OK"
grep -nE '^[A-Z_]+=.*(example-|changeme|<generate)' .env || echo "no leftover placeholders"
ls -l .env            # should start with -rw-------
```

If the first command errors with *Set EMAIL_ENCRYPTION_KEY*, fill that
variable. The `grep` prints any secret line you forgot to replace.

---

## 4. Start everything (Docker — recommended)

```bash
docker compose up -d --build
```

This builds and starts, in order: PostgreSQL → Redis → **migrations** (creates
every table) → API → 8 Celery workers → Celery beat → nginx + website.

The first build takes 5–15 minutes. Watch progress:

```bash
docker compose ps                       # every service should become "healthy"/"running"
docker compose logs -f backend          # API log; Ctrl+C to leave
docker compose logs manga-stack-migrate # should end without errors
```

`manga-stack-migrate` shows as *exited (0)*: correct, it runs once and stops.
If something says `restarting` or `exited (1)`: `docker compose logs --tail 50 <service>`.

Verify:

```bash
curl http://localhost:8000/healthz          # API alive: {"ok":true}
curl -I http://localhost:8080               # website alive (200)
```

Open **http://localhost:8080** in a browser (on a server without a domain yet,
use the SSH tunnel below).

| Port | Service |
| --- | --- |
| 8080 | Website (nginx) — this is the address users visit |
| 8000 | API directly (for debugging; never expose it publicly) |

> **Docker publishes these ports on every network interface, and Docker
> bypasses Ubuntu's `ufw` firewall.** On a public server they would be open to
> the whole internet even with `ufw` on. [Section 8](#8-go-live-on-a-linux-server-with-a-domain-and-https)
> step 5 binds them to `127.0.0.1` so only your reverse proxy can reach them.
> Until then, on a public machine browse through an SSH tunnel, run **on your
> own PC**: `ssh -L 8080:localhost:8080 your-user@your-server-ip`, then visit
> <http://localhost:8080>.

### 4.1 Rebuild after pulling an update (installs Tesseract)

> On a live site, follow [Section 12](#12-updating-safely-and-rolling-back):
> it adds the backup and "what's new" steps before these commands.

The backend image is where Tesseract and its Korean/Japanese/Chinese language
data are installed, so after `git pull` **rebuild it** — restarting is not
enough:

```bash
cd ~/manga-website-v1.01
git pull --ff-only

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
Sentry, rate limits), restart the API, the scheduler and every worker. This
form works for the full stack and the small profile alike, because it asks
Compose which services exist:

```bash
docker compose restart backend celery_beat $(docker compose config --services | grep '^celery_worker')
```

Useful commands:

```bash
docker compose ps
docker compose logs -f <service>      # backend | celery_worker_scrape | celery_beat | web | db ...
docker compose logs --tail 100 backend
docker compose restart backend
docker compose up -d --force-recreate # re-read .env (restart does NOT)
docker compose exec db psql -U manga manga      # database shell (\q to leave)
docker stats --no-stream              # memory and CPU per container
docker system df                      # disk used by images, volumes, build cache
docker compose down                   # stop (data kept in volumes)
docker compose down -v                # stop AND DELETE database + images  ⚠
```

### 4.2 Small server (about 1 GB RAM, 1 CPU)

The default stack starts eight background workers and four API workers
(about 2.5 GB of memory). On a small server use the small profile. Make it
permanent by adding one line to `.env`, so every later `docker compose`
command (logs, updates, restarts) uses it without extra flags:

```bash
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml' >> .env
docker compose config --services      # db redis manga-stack-migrate backend web celery_beat celery_worker celery_worker_scrape
docker compose up -d --build
```

Without that line, add `-f docker-compose.yml -f docker-compose.small.yml` to
**every** `docker compose` command. (If you also use the server file from
Section 8, list it too: `COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml:docker-compose.override.yml`.)

It runs two background workers instead of eight: `celery_worker` (readers'
translations, OCR, e-mail, notifications) and `celery_worker_scrape` (scraping,
picture compression, maintenance), so a big scrape never makes a translation
wait. It also uses 2 API workers, small database pools, and memory caps for
Postgres and Redis. The sizes are written in `docker-compose.small.yml` itself
(values in `.env` don't change them); edit that file to tune. Data is the
same, so you can switch between small and full at any time. In the small
profile there is no `celery_worker_email` or `celery_worker_compress`: look at
`celery_worker` and `celery_worker_scrape` instead. Add the swap file from
Section 1 before the first build.

Both setups recycle their workers: an API worker restarts after about
2000 requests, a background worker after 200 jobs or 400 MB, so memory doesn't
creep up over days. Tune with `GUNICORN_MAX_REQUESTS`,
`CELERY_MAX_TASKS_PER_CHILD`, `CELERY_MAX_MEMORY_PER_CHILD_KB` in `.env`
(0 turns a limit off).

Each API worker translates at most `PAGE_PROCESSING_CONCURRENCY` pages at the
same time (default 2); the rest wait their turn while the site keeps answering
other visitors. Raise it on a server with more CPU cores.

---

## 5. Alternative: run the app without Docker (developer setup)

Use this if you want to edit code with hot reload. You still need PostgreSQL
and Redis — the easiest way is Docker for just those two. This setup is for
development; production uses Section 4 and Section 8.

**1. Tools.** Node 22 (see `.nvmrc`; `jsdom` asks for 22.22.2 or newer),
Python 3.11 or 3.12, and, if you want OCR and backups to work on the host,
Tesseract and the PostgreSQL client:

```bash
# Node 22 (NodeSource; installs npm too)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version                      # v22.x

# Python
#   Ubuntu 24.04: its own python3 is 3.12 (the packages install and the API starts on it; Docker and CI use 3.11)
sudo apt-get install -y python3-venv python3-pip
#   Ubuntu 22.04: python3 is 3.10. Get 3.11 from the deadsnakes PPA, and use
#   "python3.11" instead of "python3" in step 3:
#     sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt-get update
#     sudo apt-get install -y python3.11 python3.11-venv

# OCR languages and database tools (same packages the Docker image installs)
sudo apt-get install -y tesseract-ocr tesseract-ocr-kor tesseract-ocr-jpn tesseract-ocr-jpn-vert \
  tesseract-ocr-chi-sim tesseract-ocr-chi-tra postgresql-client
tesseract --list-langs              # chi_sim chi_tra eng jpn jpn_vert kor osd
```

**2. Database and Redis in Docker, published to this machine only.**
`docker-compose.yml` doesn't publish their ports, so add them in a small
extra file next to it (Compose reads `docker-compose.override.yml`
automatically):

```bash
cat > docker-compose.override.yml <<'EOF'
services:
  db:
    ports: ["127.0.0.1:5432:5432"]
  redis:
    ports: ["127.0.0.1:6379:6379"]
EOF
python3 backend_fastapi/scripts/make_env.py --local && chmod 600 .env
docker compose up -d db redis
```

**3. Point `.env` at localhost** (instead of the Docker names `db` / `redis`).
This `.env` is then for the no-Docker setup; keep a separate copy for the
Docker stack:

```bash
sed -i \
  -e 's#@db:5432#@localhost:5432#' \
  -e 's#@redis:6379#@localhost:6379#' \
  -e 's#^REDIS_HOST=.*#REDIS_HOST=localhost#' \
  -e 's#^BACKEND_URL=.*#BACKEND_URL=http://127.0.0.1:8000#' \
  .env
```

**4. Python environment and migrations.**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend_fastapi/requirements.lock
dotenv -f .env run -- alembic upgrade head
dotenv -f .env run -- python backend_fastapi/scripts/seed_bootstrap_state.py
```

`dotenv -f .env run -- <command>` (installed with the Python packages) loads
`.env` for that one command. **Do not use `set -a; source .env`**: the shell
treats the file as a script, so a line with a space runs as a command
(`magic: command not found`) and the JSON line `CORS_ALLOWED_ORIGINS=["…"]`
silently loses its quotes, which breaks CORS. And without `dotenv` the API's
settings are not loaded from the repo's `.env` at all (they look for
`backend_fastapi/.env`), so it stops at start-up with *Field required*.

**5. Run each process in its own terminal** (in each: `cd ~/manga-website-v1.01`
and `source .venv/bin/activate`):

```bash
# Terminal 1 — API on http://127.0.0.1:8000
dotenv -f .env run -- npm run backend

# Terminal 2 — one worker consuming every queue
dotenv -f .env run -- celery -A backend_fastapi.app.core.celery_app:celery_app worker \
  -Q default,celery,scrape,compress,ocr,translation,email,maintenance,notifications -l info

# Terminal 3 — scheduler (REQUIRED for automatic new-chapter checks)
dotenv -f .env run -- celery -A backend_fastapi.app.core.celery_app:celery_app beat -l info

# Terminal 4 — website + gateway on http://localhost:3000 (this one needs no .env)
npm ci
npm run dev
```

Check: `curl http://127.0.0.1:8000/healthz` prints `{"ok":true}`, and
`curl http://localhost:3000/api/v1/version` answers through the gateway.

> The README's shorter worker command (`-Q scrape,celery`) only handles
> scraping. The full queue list above is needed for image compression,
> OCR, translation, e-mail and notifications.

The server-side tools in Section 6 work here too: replace
`docker compose exec backend python -m …` with
`dotenv -f .env run -- python -m …` (venv active). The scheduler leaves a
`celerybeat-schedule.db` file in the folder; it is not part of the project and
can be deleted when beat is stopped.

---

## 6. Create the first admin account (one-time Admin sign-in)

Nobody is admin on a fresh install, and on day one Google / Microsoft sign-in
and e-mail aren't set up yet (their keys live in the Secret Vault, which only
the admin can open). So the owner signs in **once** at `/admin-login` with
three things a thief who took your Gmail does **not** have:

1. **your e-mail**, matched against `MAIN_ADMIN_EMAIL_HASH` in `.env`;
2. **a one-time password**, matched against `MAIN_ADMIN_PASSWORD_HASH` in
   `.env` (only hashes are stored);
3. **a 6-digit code from an authenticator app on your phone** (Google
   Authenticator, Aegis, 1Password…), set up during that sign-in.

After that one sign-in **the page is gone**: `/admin-login` and its API answer
"not found", exactly like an address that never existed, and nothing on the
site links to it. The used password can never work again.

Set it up (the same steps with more detail: `guide/`, Steps 6–7):

1. Write the two lines into `.env`. No Python packages needed on the host
   (Ubuntu 24.04 refuses `pip install` outside a virtual environment, so this
   runs in a throw-away container). It asks for your e-mail and a password
   (12+ characters, typed twice; **nothing appears while you type**; press
   Enter without typing to get a generated one, shown once, write it down):

   ```bash
   docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
   ```

   It ends with `Done: both lines are now in .env`. Without `--write` it only
   prints the two lines. They start with `a2:` and contain no `$`, so they
   need no quotes and nothing (Compose, `source .env`) can mangle them. Older
   raw `$argon2id$…` lines still work if they were single-quoted.

2. `docker compose up -d --force-recreate`. **Not** `restart`: a restart keeps
   the old environment and the server never sees the new lines.
3. Wait about 30 seconds, then check:
   `docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap admin-status`
   must say both lines are `set` and `/admin-login: OPEN`.
4. Open **`https://your-site/admin-login`** (type it, there is no link; on a
   local trial `http://localhost:8080/admin-login`). Enter the e-mail and
   password, add the setup key it shows to your authenticator app
   (**+ → Enter a setup key**, type *Time based*), type the 6-digit code. On
   first sign-in you also complete the profile page like every new account,
   then land on `/admin` as the main admin.
5. The page is now gone (`admin-status` says `CLOSED`). You may delete the
   used password line (`sed -i '/^MAIN_ADMIN_PASSWORD_HASH=/d' .env`, then
   `docker compose up -d --force-recreate`); keep `MAIN_ADMIN_EMAIL_HASH`. Set
   up Google / Microsoft / e-mail in the Secret Vault (6.1); from then on sign
   in normally, and every admin page asks for the authenticator code.
   Until e-mail works, `cli_bootstrap login-link --email you@example.com`
   prints a sign-in link.

**On a public server do this sign-in over HTTPS** (Section 8) or through the SSH
tunnel from Section 4, never over plain `http://` on a public address.

**Why a stolen Gmail isn't enough:** someone who gets into your Gmail can at
most sign in as a normal reader. Once the one-time sign-in has been used (even
if you delete the password line afterwards), every admin page, Admin Settings
and the Secret Vault ask for the authenticator code, and the owner's
authenticator can't be replaced or removed from the website at all, only on
the server.

**Password not accepted?** Test what is in `.env`: the same `docker run …` line
with `--check .env` instead of `--write .env`:

```bash
docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --check .env"
```

It tells you whether the e-mail or the password doesn't match, or whether a
line is damaged.

**Entering the owner e-mail on the normal login page** (and pressing *Send magic
link*) while the one-time page is still open takes you straight to `/admin-login`;
no link is e-mailed. After the password has been used, the same e-mail is an
ordinary reader sign-in and `/admin-login` is gone for good.

**Lost your phone?** `docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email you@example.com`,
then a new one-time password (step 1), `up -d --force-recreate`, and
`/admin-login` sets up the new phone. A new password opens the page once more.

Other server-side tools:

- `cli_bootstrap login-link --email …` prints a one-time sign-in link without
  sending an e-mail (a normal session; admin pages still ask for the code).
- `cli_bootstrap geolock-off` switches Geolock off if you blocked your own
  country (Section 7).

(Non-Docker: same commands as in the last paragraph of Section 5.)

### 6.1 Move the remaining settings into the Secret Vault

1. Sign in through Admin sign-in (Section 6); that also set up your
   authenticator, which the vault requires.
2. Open **Admin → Secret Vault**, enter a 6-digit code to unlock it (10
   minutes), and set what you need — at minimum:
   - **Translation & OCR → Server OCR enabled = true** (then restart, 4.1);
   - **Email & magic links** (SMTP) if you want real login e-mails;
   - **Google / Microsoft sign-in** if you use them.
3. Once a value is in the vault you can delete that line from `.env`. Keep
   `.env` itself (and a private backup of it): without `INTEGRATIONS_SECRET`
   the vault cannot be decrypted.

### 6.2 Make sign-in mandatory (or not)

**Admin → Admin Settings → "Sign-in required"** (the owner, or an Admin you switched
*Admin Settings* on for, Section 6.3).

- **On:** visitors must sign in before they can browse or read. The server
  refuses catalogue, reader and community requests from guests too, not just
  the pages.
- **Off:** anyone can read; signing in is only needed for bookmarks sync,
  translation, comments and settings.

The sign-in page, sign-up, Admin sign-in (`/admin-login`), the admin area
and the server commands (Section 6) are never behind this switch, so turning
it on can't lock you out. It starts **off**.

---

### 6.3 Admins, sub-admins and automatic succession

There are four roles. **You (the owner)** hold everything; nobody can change,
demote or touch you. **Admins** (at most two) are your right hand. **Sub-admins**
(as many as the seats allow) are staff. **Users** are readers.

**Admin → Role Management** is where all of it happens.

- **Admins.** Pick a sub-admin who has an authenticator (Admin → Security) and
  press *Make Admin* (needs your code). An Admin starts with almost every power
  except **Admin Settings, the cache and "delete all manga"**, which stay off
  until you switch them on (switching a site-owner power on needs your code;
  switching off never does). Open an Admin in the list to switch any of their
  powers off or on. Only you can: an Admin can't change another Admin, themselves
  or you. An Admin's site-owner powers need their authenticator, and they enter a
  code to use them. You can demote an Admin to a user or a sub-admin at any time.
- **What an Admin can do to people.** An Admin has power over sub-admins and
  users only: appoint and remove sub-admins, change a sub-admin's powers (only
  powers they hold themselves), sign people out, and see **sub-admins' and
  users'** e-mail addresses, never another Admin's or yours. A sub-admin has
  power over users only.
- **Seats.** The two Admins share **50** sub-admin seats (25 each by default).
  Change an Admin's seats on their card; the total can't pass 50. An Admin can
  appoint only while they have seats left; removing a sub-admin frees the seat.
  Your own appointments cost no seat.
- **The ceiling.** *What sub-admins may hold* lists every everyday power. Tick one
  and no sub-admin can hold it: an Admin who tries to give it is refused, and a
  sub-admin who had it loses it until you untick it. Site-owner powers are always
  out of a sub-admin's reach.
- **Roles (presets).** Only you create new roles (named sets of powers, e.g. a
  comment moderator). Admins apply them to sub-admins; anything above the ceiling
  or above what the Admin holds is skipped.
- **Succession line.** Each Admin names up to two sub-admins, in order, on their
  card (you can set any line). If the Admin falls idle, the first one who is still
  a sub-admin, active and has an authenticator takes the seat **exactly as it is**
  (your restrictions, the seats and the sub-admins appointed), and the old Admin
  becomes a user. Or press *Hand seat over now* (needs your code) to do it
  without waiting; you can also demote an Admin and make anyone else an Admin.
- **Automatic succession** (bottom of the page, only you, off by default): choose
  the idle period (30-365 days, default 60) and confirm with your code. Every day
  the site checks each Admin. Switching it on never demotes anyone straight away;
  the idle clock starts then. If nobody in the line can serve, the idle Admin
  still becomes a user and the seat stays open for you to fill. Every change goes
  to your notifications and the audit log.
- Your own e-mail is never written in the code: it is the admin identity in
  `.env` (Section 6). Ownership never passes to anyone.

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
   # small profile: docker compose logs -f celery_worker_scrape
   ```
5. New chapters are then picked up automatically by **celery_beat** on the
   series' schedule (set per series in the admin panel).

If the preview finds nothing, the site isn't covered by a built-in parser: use
**Custom Parser** (below). Details and the list of supported/unsupported
sources: `backend_fastapi/README.md` and `deployment/runbook.md`. Only import
content you have the rights to host.

### Add a new source website (Custom Parser)

**The owner, or an Admin the Scraper AI is switched on for (Section 6.3).** Other
sub-admins don't see *Scraper AI API* or *Custom Parser*, and their previews
and imports never use the Scraper AI (only built-in and detected parsers). If a
sub-admin's preview says "ask the main admin", add the site as below.

1. Admin → Series → **Scraper AI API**: add a key and press **Test** (only
   needed for sites no built-in parser or auto-detection can read).
2. In your browser, open **one series** on that site that has **at least two
   chapters**. Copy the address of the page that shows its chapter list (not
   the homepage, a search page or a chapter).
3. Admin → Series → **Custom Parser**: paste it and click **Generate Parser**.
   The server tries, in order: the site's own parser, every known parser
   (catches moved domains), structure detection, then the Scraper AI (up to
   three attempts, each told exactly what failed). It must read a title, the
   chapter list and the pictures of two chapters before anything is saved.
4. Green: the parser is ready and the website approved; import as above.
   Red: read **What to do next** under the message, and open **What the
   scraper saw on the page** for the details (site type, lazy images, bot
   check...).
5. Sites behind a Cloudflare/CAPTCHA check, a login or payment, or with
   scrambled pictures (Shonen Jump+, Comic Days, Comic Walker, ...) cannot be
   added. The message says so; use another source for that series.

### Other features

| Feature | Needs |
| --- | --- |
| Browse, search, ratings, bookmarks, comments | API + DB (works out of the box) |
| Magic-link / Google / Microsoft login | E-mail or OAuth variables (Section 3.5) + the e-mail worker |
| Page translation overlay | Vault: *Server OCR enabled*; a translator (reader's own AI key in *Settings → AI & OCR Engines*, or a site default in Admin → API Management). Readers switch it on once in *Settings → Reading & Translation*. There each reader also picks text, outline and box colours (colour pickers), the text size (1-100, half steps, 100 = 70 px; also the quick control in the reader) and *Match the bubble's shape*: round, square and other bubbles are filled in their own shape; text drawn straight on the art stays where it was. |
| Translated chapter names | Same translator as the overlay. Source names like `522 원준 522화 2024-11-07` show as `Chapter 522`; real subtitles are translated and cached. |
| Notifications, storage alerts | The notifications and maintenance workers, beat |
| Ads, branding, announcements, maintenance mode | Admin → Site settings |
| Whole-site backups, download, restore, R2/B2 storage | Admin → Storage & Backups (Section 9.1). Main admin only |
| Geolock (block countries) | Admin → Geolock: press *Download free database (DB-IP)* once (or upload a MaxMind `GeoLite2-Country.mmdb`), tick countries, save. Behind Cloudflare you can use its country header instead. Main admin only |
| Backups | Section 9 |

---

## 8. Go live on a Linux server with a domain and HTTPS

Do these in order. Each step's commands are a separate block you can copy as
it is.

### Step 1 — Server and firewall

An Ubuntu 22.04/24.04 VM. Only **22, 80 and 443** may be reachable from the
internet (not 8000, 8080, 5432 or 6379). Set it in your cloud provider's
firewall / security group, and on the machine with `ufw`. **Allow SSH first, or
you lock yourself out** (`ufw enable` asks for a `y`):

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

`ufw` alone does **not** protect Docker's published ports; Step 5 fixes that.

### Step 2 — DNS

Create an `A` record `manga.example.com → <server IP>`, then wait until the
server sees it. This must print your server's IP:

```bash
getent hosts manga.example.com
```

### Step 3 — Install and configure

Install Docker and clone the repo on the server (Sections 1–2), then create the
`.env` (Section 3.1) and the domain lines (Section 3.3). Keep
`FORCE_HTTPS_REDIRECTS=true`. Caddy on the same machine needs nothing in
`TRUSTED_PROXY_CIDRS` (the default already covers it); if a load balancer or
another proxy sits in front, add its network range.

### Step 4 — Protect and back up `.env`

```bash
chmod 600 .env
mkdir -p ~/manga-backups && chmod 700 ~/manga-backups
cp .env ~/manga-backups/env-first && chmod 600 ~/manga-backups/env-first
```

Then copy that file off the server too (Section 9).

### Step 5 — Production mode and private ports

Create one small file next to `docker-compose.yml`. It is not part of the
repository, so `git pull` never touches it. It (a) switches every container to
`APP_ENV=production` (the compose file hard-codes `development`), and (b)
publishes the website and API ports on `127.0.0.1` only, so nothing but your
reverse proxy can reach them and `ufw` is no longer bypassed:

```bash
cat > docker-compose.override.yml <<'EOF'
# Server-only settings. Not part of the repository.
x-production: &production
  environment:
    APP_ENV: production

services:
  backend:
    <<: *production
    ports: !override
      - "127.0.0.1:8000:8000"
  web:
    ports: !override
      - "127.0.0.1:8080:8080"
  manga-stack-migrate: *production
  celery_beat: *production
  celery_worker: *production
  celery_worker_scrape: *production
  celery_worker_compress: *production
  celery_worker_ocr: *production
  celery_worker_translation: *production
  celery_worker_email: *production
  celery_worker_maintenance: *production
  celery_worker_notifications: *production
EOF
docker compose config > /dev/null && echo "compose OK"
```

Compose picks the file up by itself. On a small server (Section 4.2) list it
explicitly in `.env` instead, because naming files disables the automatic
loading:
`COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml:docker-compose.override.yml`.
The small profile switches off the extra workers named in the file; those
lines are then harmless. If Compose says *unknown tag `!override`*, your Docker
Compose is too old: update Docker (Section 1).

### Step 6 — Start

```bash
docker compose up -d --build
curl -I http://localhost:8080        # must answer on the server itself
```

### Step 7 — HTTPS with Caddy

The compose `web` container speaks plain HTTP on `127.0.0.1:8080`, so put a TLS
reverse proxy in front. Simplest is Caddy on the host: it fetches and renews
Let's Encrypt certificates by itself and sends `X-Forwarded-Proto`, which the
backend uses to avoid redirect loops.

```bash
sudo apt-get install -y caddy          # Ubuntu 24.04: from Ubuntu's own repository
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
manga.example.com {
    reverse_proxy 127.0.0.1:8080
}
EOF
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
curl -I https://manga.example.com
```

Ports 80 and 443 must be open and DNS (Step 2) must already point at the
server, or the certificate request fails (`sudo journalctl -u caddy -n 50`).
*"Unable to locate package caddy"* (Ubuntu 22.04): add Caddy's own repository
first, see <https://caddyserver.com/docs/install#debian-ubuntu-raspbian>.

Prefer nginx + certbot? The repo's `deployment/manga-site.conf` and
`deployment/renew_certificates.md` are a *reference*: the config points at the
Docker names (`backend:8000`) and a static folder, so adapt it before use.

### Step 8 — Start on boot

The containers use `restart: unless-stopped`, and Docker's installer already
enables the Docker service. Check it, and prove it with a reboot:

```bash
systemctl is-enabled docker            # enabled
sudo reboot
# after logging in again:
cd ~/manga-website-v1.01 && docker compose ps
```

Do not run `backend_fastapi/deployment/setup-server.sh` unless you have read it:
besides Docker it **turns off SSH password and root login** (you are locked out
without an SSH key), installs a package (`docker-compose-plugin`) that only
exists in Docker's own repository, and expects the project in `/var/www/manga`.
You don't need it for this guide.

### Step 9 — First sign-in and test

Open `https://manga.example.com`, do the one-time admin sign-in (Section 6) at
`https://manga.example.com/admin-login`, then run an import (Section 7).

### Updating later

Follow [Section 12](#12-updating-safely-and-rolling-back): back up, read
what's new in `AUDIT_LOG.md`, then rebuild (Section 4.1).

### 8.1 If your domain is taken down: move to a new one

The site address, allowed origins and the Google / Microsoft / magic-link
return addresses all come from one value, **Website domain**, in the Secret
Vault. The data, accounts and settings stay as they are.

1. **Buy/pick the new domain** and at its registrar create an `A` record
   `new-domain.com → <server IP>` (and `www` too if you want it). With
   Cloudflare, add the site there and point the record at the server.
2. **HTTPS for the new name** on the server:
   - Caddy (Section 8 step 7): add the name to the Caddyfile and reload. It
     fetches the certificate by itself:

     ```bash
     sudo sed -i 's/^manga.example.com {/manga.example.com, new-domain.com, www.new-domain.com {/' /etc/caddy/Caddyfile
     sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
     sudo systemctl reload caddy
     ```

   - nginx + certbot: add the name to both `server_name` lines in
     `/etc/nginx/sites-available/manga-site.conf`, then
     `sudo certbot --nginx -d new-domain.com -d www.new-domain.com` and
     `sudo systemctl reload nginx`.
   - The Docker `web` container uses `server_name _;` and needs no change.
3. **Switch** (a few clicks): Admin → Secret Vault → unlock with your
   authenticator code → **Website domain** card → type `new-domain.com` →
   **1. Check**. When all three ticks are green (DNS, HTTPS, "it is this
   site"), click **2. Switch to this domain**. It applies within seconds,
   with no restart: links in e-mails, sign-in callbacks and CORS use the new
   address. (DNS still propagating? Tick "Switch anyway".)
4. **Sign-in providers:** the card lists the new return addresses. Add them
   in the Google Cloud console (OAuth client → Authorized redirect URIs) and
   in Azure (App registration → Authentication). Until you do, Google /
   Microsoft sign-in fails on the new domain; magic links work right away.
5. Tell your readers (announcement, social links in the footer).

**Can't reach the admin page at all?** Do the switch from the server:

```bash
docker compose exec backend python -m backend_fastapi.scripts.set_site_domain new-domain.com
# undo / go back to FRONTEND_URL from .env:
docker compose exec backend python -m backend_fastapi.scripts.set_site_domain --clear
```

and sign in at `/admin-login` on the new domain (Section 6). A value you set
explicitly in the vault for one of the derived keys (e.g. `FRONTEND_URL`)
wins over the domain; remove it if the switch seems to have no effect. If a
bad vault value ever stops the site from starting, set
`VAULT_PRELOAD_DISABLED=true` in `.env`, recreate the containers
(`docker compose up -d --force-recreate`), fix it in the vault, and remove the
flag again.

---

## 9. Backups (do this before you add content)

Three things hold your site's state:

| What | Where | Back it up with |
| --- | --- | --- |
| Database | `db-data` volume | `pg_dump` through the `db` container (below), or Admin → Storage & Backups |
| Chapter images, covers, backups | `app-storage` volume | `tar` through the `backend` container (below), or Admin → Storage & Backups |
| **Your `.env`** (esp. `EMAIL_ENCRYPTION_KEY`, `INTEGRATIONS_SECRET`) | the server | copy it somewhere safe and private — without these keys, encrypted data cannot be recovered |

Restore procedure: Section 12.3, `backend_fastapi/deployment/backups.md` and
`deployment/runbook.md`.

> The ready-made scripts `backend_fastapi/deployment/backup_postgres.sh`,
> `backup_storage.sh` and the `manga-backup.*` systemd units are written for a
> database the host can reach on `localhost:5432` and a pictures folder at
> `/app/storage`. In the Docker setup neither is true (the database port isn't
> published and the pictures live in a volume), so use the commands below or
> the admin panel (9.1) instead.

### Nightly backup with cron

```bash
cat > ~/manga-backup.sh <<'EOF'
#!/usr/bin/env bash
# Database + pictures + .env, kept 14 days. Run from cron.
set -euo pipefail
cd "$HOME/manga-website-v1.01"
dest="$HOME/manga-backups"
mkdir -p "$dest" && chmod 700 "$dest"
stamp=$(date +%F-%H%M)
docker compose exec -T db pg_dump -U manga -Fc manga > "$dest/db-$stamp.dump"
docker compose exec -T backend tar czf - -C /app/storage . > "$dest/storage-$stamp.tgz"
cp .env "$dest/env-$stamp" && chmod 600 "$dest/env-$stamp"
find "$dest" -type f -mtime +14 -delete
EOF
chmod +x ~/manga-backup.sh
~/manga-backup.sh && ls -lh ~/manga-backups                 # run it once by hand first
(crontab -l 2>/dev/null; echo '30 3 * * * $HOME/manga-backup.sh >> $HOME/manga-backup.log 2>&1') | crontab -
crontab -l
```

That keeps copies on the same server, which does not survive losing the
server. **Copy `~/manga-backups` off the machine** too, for example
`rsync -av ~/manga-backups/ you@other-host:manga-backups/` from another computer,
or use the admin panel's S3-compatible storage (9.1). The `.env` copies hold
every secret: store them like passwords.

### 9.1 From the admin panel: Storage & Backups

**Admin → Storage & Backups** (main admin only) does the same from the
website, and is the easiest way to keep the site safe:

1. **Set a backup password** first (at least 10 characters) and write it down
   **off the server**. Every backup is then encrypted; without the password
   no backup can be restored, here or on a new server.
2. **Weekly backup** is on by default: Sunday 03:00 UTC, the newest 2 kept,
   pictures included. Change the day, hour, how many to keep and whether
   pictures go in. A backup with pictures is about as big as your pictures
   folder; it is refused (not half-made) when the disk lacks room.
3. **Back up now** makes one immediately. **Download** saves any backup to
   your computer (or Google Drive from there).
4. **Connect storage** to copy every backup off the server: any
   S3-compatible storage. Paste the endpoint, bucket, region and an access key
   limited to that bucket, press **Test connection**, then **Connect**.
   Examples: Cloudflare R2 `https://<account-id>.r2.cloudflarestorage.com`,
   region `auto`; Backblaze B2 `https://s3.<region>.backblazeb2.com`, region
   e.g. `us-west-004`. **Disconnect** forgets the keys; files already there
   stay. Old backups are pruned there too.
5. **Restore**: press Restore on a backup, type `RESTORE`. A database-only
   safety copy of the current site is made first (it appears in the list). Then
   restart so the restored database is upgraded if it came from an older
   version: `docker compose up -d --force-recreate`.

**Moving to a new server:** install the site (Sections 1–6) with the **same
`.env`** (above all `EMAIL_ENCRYPTION_KEY` and `INTEGRATIONS_SECRET`), sign in,
open Storage & Backups, then either **Upload a backup** from your computer or
connect the same storage and **Bring to this server**, and Restore it with
the backup password.

Backups live in the `app-storage` volume under `backups/` (never served to
visitors). Put `BACKUP_DIR` on another disk in `.env` if the main one is small.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `permission denied … /var/run/docker.sock` | You are not in the `docker` group yet: log out and back in after `usermod` (Section 1), or run `newgrp docker`, or prefix commands with `sudo`. |
| `docker: 'compose' is not a docker command` | The Compose plugin is missing (Ubuntu's `docker.io` lacks it). Use Docker's installer (Section 1) or `sudo apt-get install -y docker-compose-v2` on 24.04. |
| `unknown tag !override` / `yaml: unknown tag` | Docker Compose older than v2.24. Update Docker (Section 1) and check `docker compose version`. |
| `Set EMAIL_ENCRYPTION_KEY to a Fernet key` | There is no `.env`, or you are in the wrong folder (`cd ~/manga-website-v1.01`), or the variable is empty. Section 3.1. |
| Backend exits at startup about `FORCE_HTTPS_REDIRECTS` | You're in production mode with it `false`. Enable TLS, or use development mode (Section 3.4). |
| Site loads but login/redirects loop on plain `http://localhost` | `FORCE_HTTPS_REDIRECTS` is still `true`; set `false` for local only. |
| The site still runs in development mode on the server | `docker-compose.yml` hard-codes `APP_ENV: development`; add the server file from Section 8 step 5 and `docker compose up -d --force-recreate`. |
| `password authentication failed` (DB) or Redis `NOAUTH` | Passwords in `DATABASE_URL` / `REDIS_URL` / `CELERY_*` don't match `POSTGRES_PASSWORD` / `REDIS_PASSWORD`. After changing the DB password on an existing volume, run `docker compose down -v` (deletes data) or change it inside Postgres. |
| `ModuleNotFoundError: psycopg` | `DATABASE_URL` must start `postgresql+psycopg2://`. |
| Imports stay "queued" forever | Workers or beat not running: `docker compose ps`; for the non-Docker setup, start the worker with **all** queues (Section 5). |
| Chapter has no pictures / slow | Check the compress worker logs (`celery_worker_compress`, small profile: `celery_worker_scrape`); ensure enough disk (`docker system df`, `df -h`). |
| Build dies with `Killed` / exit code 137 / `npm ci` stops | Out of memory on a small server. Add the swap file (Section 1) and run `docker compose up -d --build` again. |
| `no space left on device` | `df -h /` and `docker system df`. Free space with `docker image prune -f` (old images) and `docker builder prune -f` (build cache). Cap the logs (Section 1). `docker compose down -v` would delete your data: never use it to free space. |
| Ports 8000/8080 answer from the internet although `ufw` blocks them | Docker bypasses `ufw` for published ports. Add the server file from Section 8 step 5 (binds them to `127.0.0.1`) and `docker compose up -d --force-recreate`. |
| `pip install` says `externally-managed-environment` (Ubuntu 24.04) | Python packages must go into a virtual environment: `python3 -m venv .venv && source .venv/bin/activate` (Section 5). Don't use `--break-system-packages`. |
| `apt install python3.11`: *Unable to locate package* | Ubuntu 24.04 ships Python 3.12 (works) and 22.04 ships 3.10; get 3.11 from the deadsnakes PPA (Section 5) or use the Docker setup. |
| Non-Docker: `magic: command not found`, or CORS errors after `source .env` | Don't `source .env`; use `dotenv -f .env run -- <command>` (Section 5). |
| Caddy: no certificate / `ERR_SSL_PROTOCOL_ERROR` | DNS must point at this server and ports 80/443 must be open: `getent hosts manga.example.com`, `sudo ufw status`, `sudo journalctl -u caddy -n 50`. |
| Custom Parser: "answered with a bot check" | The site shows Cloudflare/CAPTCHA to servers. It cannot be added; use another source for the series. |
| Custom Parser: "No parser could read a title and a chapter list" | You pasted a homepage, list or chapter. Paste one series page with 2+ chapters (Section 7, *Add a new source website*). |
| Custom Parser: "naver.com is Naver's portal" | Use the series page on `comic.naver.com` (`.../webtoon/list?titleId=...`). |
| Custom Parser: "Scraper AI judged this site cannot be scraped" | The AI found a login, paywall or scrambled images. Use another source. |
| Sub-admin: no *Scraper AI API* / *Custom Parser* buttons, or preview says "ask the main admin" | The Scraper AI is a site-owner power. Give it in Role Management (Section 6.3), or add the site yourself with Custom Parser (Section 7). |
| Sub-admin gets "forbidden" on Admin Settings / API Management / Role Management / Vault / Backups / Geolock | These are site-owner powers: only you, and Admins you left them on for, can open them (Section 6.3). A sub-admin never can. |
| "There can be only 2 Admins" | Demote one (Role Management) or hand a seat over first. |
| "You have no sub-admin seats left" | Remove a sub-admin, or the owner adds seats on your card. |
| "The site owner doesn't allow sub-admins to hold …" | The owner's ceiling blocks that power; only the owner can lift it. |
| An Admin's powers show *paused* or they are asked for a code | They need an authenticator (Admin → Security) and must enter a code to use site-owner powers. Intended. |
| An Admin became a user on their own | Automatic succession: they were idle longer than the chosen days. Your notifications say who took over from their line; undo it in Role Management. |
| `$argon2id...` value turns into garbage | Wrap values containing `$` in single quotes in `.env`. Admin hash lines made by `make_admin_hash.py` start with `a2:` and have no `$`. |
| Translation/OCR overlay does nothing | Reader: *Settings → Reading & Translation* must be on. Server: vault *Server OCR enabled* = true and restarted (4.1). |
| Translation is a plain box instead of the bubble's shape | Expected for text drawn on the art, bubbles with a gap in the outline, bubbles cut by the page edge, or two separately-read lines in one bubble. Also check the reader's *Match the bubble's shape* switch. Pages translated before the update keep boxes until their cached result is cleared (Admin Settings → cache) |
| Translated text too small or too big | Reader: *Settings → Reading & Translation → Text size* (1-100) or the size control in the reader. Long lines still shrink to fit their bubble |
| Sub-admin sees only their own entries in the audit log | Intended. Give them *See the full audit log* in Role Management |
| Reader says "Text was found but not translated" | OCR works but nothing translates: add an AI key in *Settings → AI & OCR Engines* (press **Test connection**), or a site default in Admin → API Management. |
| `tesseract: not found` / OCR "engine not available" | The backend image is old: rebuild it (Section 4.1) and check `docker compose exec backend tesseract --list-langs`. Non-Docker: install the packages in Section 5. |
| Korean/Chinese pages read as garbage | Set the series' *Text language on pages* (Series → layout) to the language actually printed on the pages. |
| Secret Vault / admin pages say "Set up your authenticator app" | Do the one-time Admin sign-in (Section 6); it sets up the authenticator. |
| `/admin-login` shows "Page not found" after the first sign-in | Expected: the page is gone after one use. Sign in with Google, Microsoft, a magic link or `cli_bootstrap login-link`. |
| `/admin-login` shows "Page not found" before any sign-in (older versions: greyed-out **Continue**) | The server doesn't see the admin lines. `cli_bootstrap admin-status` says why: *not set* → you used `restart`; run `docker compose up -d --force-recreate`. *DAMAGED* → an old raw hash pasted without quotes; make new lines (Section 6). |
| `/admin-login`: "Email, password or code is not right" | `make_admin_hash.py --check .env` (Section 6) tells you whether the e-mail or the password doesn't match. Make new lines if needed. Check Caps Lock and the keyboard language. |
| `/admin-login`: "Too many requests" | Ten wrong tries from one address lock the page for 15 minutes. Wait, then try again. |
| Authenticator code refused | The phone's clock is off. Turn on automatic date & time on the phone, then type a fresh code (each lasts 30 seconds). |
| Lost the phone with the authenticator | `cli_bootstrap reset-2fa --email you@example.com`, then a new one-time password and `/admin-login` (Section 6). |
| Visitors are sent to the login page | Admin Settings → *Sign-in required* is on (Section 6.2). |
| Someone can't open a second account with another Gmail spelling | Intended: `john.doe@gmail.com`, `johndoe+x@gmail.com` and `@googlemail.com` are one inbox and one account. |
| Update cards say "Just now" or show no time | Rebuild (Section 4.1). Old builds misread server times. A card without any chapter shows the series' added time. |
| Donation link or address refused | Links must be `https://` on the platform's own domain; addresses must match the chosen network. The message names the entry. |
| Site unreachable after switching the domain | DNS or HTTPS for the new name isn't ready. Run `set_site_domain --clear` on the server to go back (Section 8.1). |
| A Secret Vault value stops the site from starting | Set `VAULT_PRELOAD_DISABLED=true` in `.env`, recreate the containers, fix the value, then remove the flag. |
| Server slow, swapping, or containers killed for memory on a 1-2 GB server | Use the small profile (Section 4.2) and a swap file (Section 1). |
| Backup says "Not enough free disk" | Delete old backups, keep fewer, turn off *Include pictures*, or set `BACKUP_DIR` to a bigger disk. |
| Backup "Storage copy failed" | The archive is safe on the server. Press *Test connection* in Storage & Backups to see why (wrong key, bucket, region, or key not allowed to write). |
| Restore says "Wrong backup password" | Enter the password that was set when that backup was made. |
| Backup upload stops at 10 MB (own nginx in front) | Your outer proxy caps uploads. Copy the backups location from `deployment/manga-site.conf` (no size cap for `/api/v1/admin/backups/upload`). Caddy has no such cap. |
| You blocked your own country with Geolock | On the server: `docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap geolock-off`. |
| Geolock blocks nobody | Turn it on, tick countries, and install the country database (Geolock tab). Visitors on a local network or VPN aren't matched. |
| Port already in use (`port is already allocated`) | Another program uses 8080/8000/5432: `sudo ss -ltnp \| grep -E ':(8080\|8000\|5432)\b'`. Stop it, or change the published port in `docker-compose.yml`. |
| Windows: `exec ... no such file or directory` in a container | Line endings; clone inside WSL or run `git config core.autocrlf false` before cloning. |
| API docs (`/docs`) missing | Intentional in production; set `EXPOSE_API_DOCS=true` on a private deploy. |

---

## 11. Quick checklist

- [ ] Ubuntu 22.04/24.04; Docker installed, `docker compose version` is v2.24+ and `docker run --rm hello-world` works without `sudo`
- [ ] On a 1-2 GB server: swap file added, and `COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml` in `.env` (Sections 1 and 4.2)
- [ ] `.env` made with `make_env.py` (`--local` for a trial), `chmod 600 .env`, copy stored safely; domain lines set for production (Section 3.3); `docker compose config` passes
- [ ] `docker compose up -d --build`; all services healthy; `curl http://localhost:8000/healthz` answers `{"ok":true}`
- [ ] `docker compose exec backend tesseract --list-langs` lists `kor jpn chi_sim`
- [ ] Production: `ufw` allows only 22/80/443; `docker-compose.override.yml` from Section 8 step 5 in place (production mode, ports on `127.0.0.1`); Caddy serves `https://your-domain`
- [ ] `make_admin_hash.py --write .env`, `up -d --force-recreate`, `admin-status` says OPEN; first sign-in at `/admin-login` done (authenticator enrolled); `admin-status` now says CLOSED
- [ ] OCR, e-mail and sign-in settings entered in **Admin → Secret Vault**
- [ ] Sign-in required on/off chosen (Admin Settings); donation links added if wanted
- [ ] First series imported; new chapters arrive via beat
- [ ] Updating from before PR #33: provider keys that were saved in a **custom header** (e.g. Azure `api-key`) were publicly readable; rotate them at the provider and save the new key in Admin → API Management
- [ ] Scraper AI key tested (Admin → Series → Scraper AI API) before adding new source sites with Custom Parser (main admin only)
- [ ] Backups: nightly `~/manga-backup.sh` in cron and copied off the server; in **Admin → Storage & Backups** set a backup password (kept off the server), check the weekly schedule, and connect R2/B2 storage
- [ ] Geolock set if needed (Admin → Geolock; install the country database first)
- [ ] Admins (optional): at most two trusted sub-admins with an authenticator, made Admins in Role Management; set their seats, the sub-admin ceiling and each Admin's succession line; automatic succession on if you want idle Admins replaced (Section 6.3)
- [ ] `AUDIT_LOG.md` read; a backup taken before every update (Section 12)

More detail: `README.md`, `backend_fastapi/README.md`, `deployment/README.md`,
`deployment/runbook.md`, `deployment/key-rotation.md`.

---

## 12. Updating safely and rolling back

Do this every time you update a live site.

### 12.1 Before updating

```bash
cd ~/manga-website-v1.01

# 1. Note where you are now (write these two lines down).
git log -1 --oneline                                   # code version
docker compose exec backend alembic current            # database version

# 2. Back up the database, the images and .env. With the script from Section 9:
~/manga-backup.sh

# 3. Fetch the update and read what changed since your version.
git fetch origin
git log --oneline --first-parent HEAD..origin/main     # the PRs you're about to get
git diff HEAD..origin/main -- AUDIT_LOG.md .env.example GUIDE.md
```

No `~/manga-backup.sh` yet? Do step 2 by hand instead (the same three commands
as in Section 9):

```bash
mkdir -p ~/manga-backups && chmod 700 ~/manga-backups
docker compose exec -T db pg_dump -U manga -Fc manga > ~/manga-backups/db-$(date +%F-%H%M).dump
docker compose exec -T backend tar czf - -C /app/storage . > ~/manga-backups/storage-$(date +%F-%H%M).tgz
cp .env ~/manga-backups/env-$(date +%F-%H%M) && chmod 600 ~/manga-backups/env-*
```

In that diff, look for:

- **new `.env` keys** in `.env.example`: add them before restarting;
- **Database** lines in the new `AUDIT_LOG.md` entries: a migration marked **lossy** makes the backup in step 2 essential;
- **Settings** lines: new switches or vault values you may want to set.

### 12.2 Update

```bash
git pull --ff-only
docker compose build --pull
docker compose up -d --force-recreate          # runs database migrations first
docker compose logs manga-stack-migrate | tail -n 20
docker compose ps
```

`git pull --ff-only` stops with a message instead of merging if you changed a
tracked file by hand. Your `docker-compose.override.yml` and `.env` are not
tracked, so they never block it. Then do the **Check** steps listed in the new
`AUDIT_LOG.md` entries.

### 12.3 Roll back

Pick the smallest step that fixes it (details in `AUDIT_LOG.md` §3):

1. **Switch it off**: many features have a switch (Admin Settings, Secret Vault).
2. **Go back to the previous code version** (keeps the database):

   ```bash
   git checkout <the version you wrote down in 12.1>
   docker compose build --pull && docker compose up -d --force-recreate
   ```

   Newer database columns are ignored by older code. The migration service
   will report the database is ahead, which is expected until you update again.
   To return to the latest code later: `git checkout main && git pull --ff-only`.
3. **Also undo database changes**: before step 2, run
   `docker compose run --rm manga-stack-migrate alembic downgrade <database version you wrote down>`.
4. **Lossy migration, or data looks wrong**: restore the backup from 12.1:

   ```bash
   docker compose stop backend celery_beat $(docker compose config --services | grep '^celery_worker')
   docker compose exec -T db pg_restore -U manga -d manga --clean --if-exists < ~/manga-backups/db-<date>.dump
   # pictures too, only if they were lost or damaged:
   docker compose run --rm --no-deps -T --entrypoint tar backend xzf - -C /app/storage < ~/manga-backups/storage-<date>.tgz
   docker compose up -d --force-recreate
   ```

   (More detail: `backend_fastapi/deployment/backups.md`.)

To undo one change permanently, revert its merge commit on `main`
(`git revert -m 1 <merge sha>`, listed in each `AUDIT_LOG.md` entry), push,
and update as in 12.2.

### 12.4 Keeping this guide useful

Whenever the site changes, the same pull request:

- adds an entry to `AUDIT_LOG.md` (what, why, files, database, settings, check, **undo**);
- updates this guide where installing, configuring, updating or running the site changed: the section itself, the [Troubleshooting](#10-troubleshooting) table and the [Quick checklist](#11-quick-checklist).

The PR template (`.github/pull_request_template.md`) and `CLAUDE.md` list
these as required steps.
