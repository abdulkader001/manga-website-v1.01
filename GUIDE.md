# Deployment Guide — Manga Reader

Step-by-step instructions to get the whole site running: website, API, database,
job workers (series import, chapter scraping, image compression, OCR,
translation, e-mail, notifications) and the admin account.

> This guide was written from the repo's own files (`docker-compose.yml`,
> `.env.example`, `server.ts`, `deployment/`, `backend_fastapi/`). Commands have
> not been run end-to-end on every OS, so treat the first run as a test and use
> the [Troubleshooting](#10-troubleshooting) table if something differs.
>
> **Two documents, kept up to date with every change:**
> - **`GUIDE.md`** (this file) is *how to run the site*.
> - **[`AUDIT_LOG.md`](AUDIT_LOG.md)** is *what was changed, why, and how to undo it*. It also has a one-page map of the site, the database migration ledger, and rollback steps.
>
> Updating an existing site? Go to [Section 12](#12-updating-safely-and-rolling-back).
>
> **First install? Use the step-by-step guide for your computer** in
> [`guide/`](guide/README.md): [Windows](guide/INSTALL-WINDOWS.md),
> [macOS](guide/INSTALL-MACOS.md), [Linux](guide/INSTALL-LINUX.md). They cover
> everything from installing Docker to the first admin sign-in, with every
> command spelled out. This file is the full reference behind them.

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
> (`MAIN_ADMIN_EMAIL_HASH`, `MAIN_ADMIN_PASSWORD_HASH`). **Everything else** — Google /
> Microsoft sign-in, SMTP and magic links, OCR and translation, API keys,
> Sentry, limits, image storage — is set later in the admin panel under
> **Admin → Secret Vault** (Section 6.1), encrypted in the database. A vault
> value overrides the same line in `.env`; removing it falls back to `.env`.
> You can still put those values in `.env` if you prefer — the vault is
> simply easier to change and never needs a file edit.

### 3.1 Generate the secrets

Run these and paste each output into the matching variable. **Every secret must
be different from the others.**

**Easiest:** on a new install, skip the `cp` above and let
`python3 backend_fastapi/scripts/make_env.py` (add `--local` for a trial on
`http://localhost`) create `.env` with all of these filled in and the
passwords matching inside the URLs. It never overwrites an existing `.env`.
By hand:

```bash
openssl rand -hex 32        # run 4 times: SECRET_KEY, JWT_SECRET_KEY,
                            #   MAGIC_LINK_SECRET, INTEGRATIONS_SECRET
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
every table) → API → 8 Celery workers → Celery beat →
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

> On a live site, follow [Section 12](#12-updating-safely-and-rolling-back):
> it adds the backup and "what's new" steps before these commands.

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

### 4.2 Small server (about 1 GB RAM, 1 CPU)

The default stack starts eight background workers and four API workers
(about 2.5 GB of memory). On a small server, add the small profile to
**every** `docker compose` command:

```bash
docker compose -f docker-compose.yml -f docker-compose.small.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.small.yml ps
```

It runs two background workers instead of eight: one for readers'
translations, OCR, e-mail and notifications, one for scraping, picture
compression and maintenance, so a big scrape never makes a translation wait.
It also uses 2 API workers, small database pools, and memory caps for Postgres
and Redis. The sizes are written in `docker-compose.small.yml` itself (values in
`.env` don't change them); edit that file to tune. Data is the same, so you can
switch between small and full at any time.

Both setups now recycle their workers: an API worker restarts after about
2000 requests, a background worker after 200 jobs or 400 MB, so memory doesn't
creep up over days. Tune with `GUNICORN_MAX_REQUESTS`,
`CELERY_MAX_TASKS_PER_CHILD`, `CELERY_MAX_MEMORY_PER_CHILD_KB` in `.env`
(0 turns a limit off).

Each API worker translates at most `PAGE_PROCESSING_CONCURRENCY` pages at the
same time (default 2); the rest wait their turn while the site keeps answering
other visitors. Raise it on a server with more CPU cores.

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

Set it up (the same steps, per OS and in more detail: `guide/`, Steps 6–7):

1. Write the two lines into `.env`. No Python needed on the host; it asks
   for your e-mail and a password (12+ characters, typed twice; press Enter
   without typing to get a generated one):

   ```bash
   docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
   ```

   (PowerShell: write `"${PWD}:/w"` instead of `"$PWD":/w`.) Without
   `--write` it only prints the two lines. They start with `a2:` and contain
   no `$`, so they need no quotes and nothing (Compose, `source .env`,
   PowerShell) can mangle them. Older raw `$argon2id$…` lines still work if
   they were single-quoted.

2. `docker compose up -d --force-recreate`. **Not** `restart`: a restart keeps
   the old environment and the server never sees the new lines.
3. Check: `docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap admin-status`
   must say both lines are `set` and `/admin-login: OPEN`.
4. Open **`https://your-site/admin-login`** (type it, there is no link).
   Enter the e-mail and password, add the setup key it shows to your
   authenticator app, type the 6-digit code. You land on `/admin` as the main
   admin.
5. The page is now gone (`admin-status` says `CLOSED`). You may delete the
   `MAIN_ADMIN_PASSWORD_HASH` line; keep `MAIN_ADMIN_EMAIL_HASH`. Set up
   Google / Microsoft / e-mail in the Secret Vault (6.1); from then on sign
   in normally, and every admin page asks for the authenticator code.
   Until e-mail works, `cli_bootstrap login-link --email you@example.com`
   prints a sign-in link.

**Why a stolen Gmail isn't enough:** someone who gets into your Gmail can at
most sign in as a normal reader. Once the one-time sign-in has been used (even
if you delete the password line afterwards), every admin page, Admin Settings
and the Secret Vault ask for the authenticator code, and the owner's
authenticator can't be replaced or removed from the website at all, only on
the server.

**Password not accepted?** `python backend_fastapi/scripts/make_admin_hash.py --check .env`
(or the same `docker run …` line with `--check .env` instead of
`--write .env`) tests an e-mail and password against `.env` and tells you
which one doesn't match, or whether a line is damaged.

**Lost your phone?** `docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email you@example.com`,
then a new one-time password (step 1), `up -d --force-recreate`, and
`/admin-login` sets up the new phone. A new password opens the page once more.

Other server-side tools:

- `cli_bootstrap login-link --email …` prints a one-time sign-in link without
  sending an e-mail (a normal session; admin pages still ask for the code).

(Non-Docker: same commands without `docker compose exec backend`, venv active.)

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

**Admin → Admin Settings → "Sign-in required"** (main admin only; it can't
be granted to a sub-admin).

- **On:** visitors must sign in before they can browse or read. The server
  refuses catalogue, reader and community requests from guests too, not just
  the pages.
- **Off:** anyone can read; signing in is only needed for bookmarks sync,
  translation, comments and settings.

The sign-in page, sign-up, Admin sign-in (`/admin-login`), the admin area
and the server commands (Section 6) are never behind this switch, so turning
it on can't lock you out. It starts **off**.

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
**Custom Parser** (below). Details and the list of supported/unsupported
sources: `backend_fastapi/README.md` and `deployment/runbook.md`. Only import
content you have the rights to host.

### Add a new source website (Custom Parser)

**Main admin only.** Sub-admins don't see *Scraper AI API* or *Custom
Parser*, can't be given them in Role Management, and their previews and
imports never use the Scraper AI (only built-in and detected parsers). If a
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
| Magic-link / Google / Microsoft login | E-mail or OAuth variables (Section 3.5) + `celery_worker_email` |
| Page translation overlay | Vault: *Server OCR enabled*; a translator (reader's own AI key in *Settings → AI & OCR Engines*, or a site default in Admin → API Management). Readers switch it on once in *Settings → Reading & Translation*. There each reader also picks text, outline and box colours (colour pickers), the text size (1-100, half steps, 100 = 70 px; also the quick control in the reader) and *Match the bubble's shape*: round, square and other bubbles are filled in their own shape; text drawn straight on the art stays where it was. |
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
   - Caddy (Section 8 step 6): add the name to the Caddyfile and reload. It
     fetches the certificate by itself:

     ```bash
     sudo sed -i 's/^manga.example.com {/manga.example.com, new-domain.com, www.new-domain.com {/' /etc/caddy/Caddyfile
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
`VAULT_PRELOAD_DISABLED=true` in `.env`, restart, fix it in the vault, and
remove the flag again.

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
| Custom Parser: "answered with a bot check" | The site shows Cloudflare/CAPTCHA to servers. It cannot be added; use another source for the series. |
| Custom Parser: "No parser could read a title and a chapter list" | You pasted a homepage, list or chapter. Paste one series page with 2+ chapters (Section 7, *Add a new source website*). |
| Custom Parser: "naver.com is Naver's portal" | Use the series page on `comic.naver.com` (`.../webtoon/list?titleId=...`). |
| Custom Parser: "Scraper AI judged this site cannot be scraped" | The AI found a login, paywall or scrambled images. Use another source. |
| Sub-admin: no *Scraper AI API* / *Custom Parser* buttons, or preview says "ask the main admin" | Intended: the Scraper AI is main-admin only. The main admin adds the site with Custom Parser (Section 7). |
| Sub-admin gets "forbidden" on Admin Settings / API Management / Role Management, or the API and "appoint/remove sub-admins" toggles are gone from Role Management | Intended: all three are main-admin only, including read access. Only the main admin appoints or removes sub-admins. |
| `$argon2id...` value turns into garbage | Wrap values containing `$` in single quotes in `.env`. Admin hash lines made by `make_admin_hash.py` start with `a2:` and have no `$`. |
| Translation/OCR overlay does nothing | Reader: *Settings → Reading & Translation* must be on. Server: vault *Server OCR enabled* = true and restarted (4.1). |
| Translation is a plain box instead of the bubble's shape | Expected for text drawn on the art, bubbles with a gap in the outline, bubbles cut by the page edge, or two separately-read lines in one bubble. Also check the reader's *Match the bubble's shape* switch. Pages translated before the update keep boxes until their cached result is cleared (Admin Settings → cache) |
| Translated text too small or too big | Reader: *Settings → Reading & Translation → Text size* (1-100) or the size control in the reader. Long lines still shrink to fit their bubble |
| Sub-admin sees only their own entries in the audit log | Intended. Give them *See the full audit log* in Role Management |
| Reader says "Text was found but not translated" | OCR works but nothing translates: add an AI key in *Settings → AI & OCR Engines* (press **Test connection**), or a site default in Admin → API Management. |
| `tesseract: not found` / OCR "engine not available" | The backend image is old: rebuild it (Section 4.1) and check `docker compose exec backend tesseract --list-langs`. |
| Korean/Chinese pages read as garbage | Set the series' *Text language on pages* (Series → layout) to the language actually printed on the pages. |
| Secret Vault / admin pages say "Set up your authenticator app" | Do the one-time Admin sign-in (Section 6); it sets up the authenticator. |
| `/admin-login` shows "Page not found" after the first sign-in | Expected: the page is gone after one use. Sign in with Google, Microsoft, a magic link or `cli_bootstrap login-link`. |
| `/admin-login` shows "Page not found" before any sign-in (older versions: greyed-out **Continue**) | The server doesn't see the admin lines. `cli_bootstrap admin-status` says why: *not set* → you used `restart`; run `docker compose up -d --force-recreate`. *DAMAGED* → an old raw hash pasted without quotes; make new lines (Section 6). |
| `/admin-login`: "Email, password or code is not right" | `make_admin_hash.py --check .env` tells you whether the e-mail or the password doesn't match. Make new lines if needed (Section 6). |
| Lost the phone with the authenticator | `cli_bootstrap reset-2fa --email you@example.com`, then a new one-time password and `/admin-login` (Section 6). |
| Visitors are sent to the login page | Admin Settings → *Sign-in required* is on (Section 6.2). |
| Someone can't open a second account with another Gmail spelling | Intended: `john.doe@gmail.com`, `johndoe+x@gmail.com` and `@googlemail.com` are one inbox and one account. |
| Update cards say "Just now" or show no time | Rebuild (Section 4.1). Old builds misread server times. A card without any chapter shows the series' added time. |
| Donation link or address refused | Links must be `https://` on the platform's own domain; addresses must match the chosen network. The message names the entry. |
| Site unreachable after switching the domain | DNS or HTTPS for the new name isn't ready. Run `set_site_domain --clear` on the server to go back (Section 8.1). |
| A Secret Vault value stops the site from starting | Set `VAULT_PRELOAD_DISABLED=true` in `.env`, recreate the containers, fix the value, then remove the flag. |
| Server slow, swapping, or containers killed for memory on a 1-2 GB server | Use the small profile (Section 4.2): `docker compose -f docker-compose.yml -f docker-compose.small.yml up -d`. |
| Port already in use | Another program uses 8080/8000/5432; stop it or change the published port in `docker-compose.yml`. |
| Windows: `exec ... no such file or directory` in a container | Line endings; clone inside WSL (Section 1) or run `git config core.autocrlf false` before cloning. |
| API docs (`/docs`) missing | Intentional in production; set `EXPOSE_API_DOCS=true` on a private deploy. |

---

## 11. Quick checklist

- [ ] Docker installed, `docker compose version` works
- [ ] `.env` created; 6 random secrets + 2 passwords + Fernet key set; URLs/passwords consistent
- [ ] `docker compose build --pull && docker compose up -d --force-recreate`; all services healthy (on a 1-2 GB server add `-f docker-compose.yml -f docker-compose.small.yml`, Section 4.2)
- [ ] `docker compose exec backend tesseract --list-langs` lists `kor jpn chi_sim`
- [ ] `make_admin_hash.py --write .env`, `up -d --force-recreate`, `admin-status` says OPEN; first sign-in at `/admin-login` done (authenticator enrolled); `admin-status` now says CLOSED
- [ ] OCR, e-mail and sign-in settings entered in **Admin → Secret Vault**
- [ ] Sign-in required on/off chosen (Admin Settings); donation links added if wanted
- [ ] First series imported; new chapters arrive via beat
- [ ] Updating from before PR #33: provider keys that were saved in a **custom header** (e.g. Azure `api-key`) were publicly readable; rotate them at the provider and save the new key in Admin → API Management
- [ ] Scraper AI key tested (Admin → Series → Scraper AI API) before adding new source sites with Custom Parser (main admin only)
- [ ] Domain + HTTPS in front (production)
- [ ] `.env` and backups stored safely off the server

More detail: `README.md`, `backend_fastapi/README.md`, `deployment/README.md`,
`deployment/runbook.md`, `deployment/key-rotation.md`.
- [ ] `AUDIT_LOG.md` read; a backup taken before every update (Section 12)

---

## 12. Updating safely and rolling back

Do this every time you update a live site.

### 12.1 Before updating

```bash
cd /path/to/manga-website

# 1. Note where you are now (write these two lines down).
git log -1 --oneline                                   # code version
docker compose exec backend alembic current            # database version

# 2. Back up the database, the images and .env (works with the Docker setup;
#    Section 9 has the scheduled/encrypted backup scripts).
mkdir -p ~/manga-backups
docker compose exec -T db pg_dump -U manga -Fc manga > ~/manga-backups/db-$(date +%F-%H%M).dump
docker compose exec -T backend tar czf - -C /app/storage . > ~/manga-backups/storage-$(date +%F-%H%M).tgz
cp .env ~/manga-backups/env-$(date +%F-%H%M)

# 3. Fetch the update and read what changed since your version.
git fetch origin
git log --oneline --first-parent HEAD..origin/main     # the PRs you're about to get
git diff HEAD..origin/main -- AUDIT_LOG.md .env.example GUIDE.md
```

In that diff, look for:

- **new `.env` keys** in `.env.example`: add them before restarting;
- **Database** lines in the new `AUDIT_LOG.md` entries: a migration marked **lossy** makes the backup in step 2 essential;
- **Settings** lines: new switches or vault values you may want to set.

### 12.2 Update

```bash
git pull
docker compose build --pull
docker compose up -d --force-recreate          # runs database migrations first
docker compose logs manga-stack-migrate | tail -n 20
docker compose ps
```

Then do the **Check** steps listed in the new `AUDIT_LOG.md` entries.

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
3. **Also undo database changes**: before step 2, run
   `docker compose run --rm manga-stack-migrate alembic downgrade <database version you wrote down>`.
4. **Lossy migration, or data looks wrong**: restore the backup from 12.1:

   ```bash
   docker compose stop backend celery_beat $(docker compose config --services | grep celery_worker)
   docker compose exec -T db pg_restore -U manga -d manga --clean --if-exists < ~/manga-backups/db-<date>.dump
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
