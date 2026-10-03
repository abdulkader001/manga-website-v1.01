# Go live: run the site on a Linux server

This guide takes you from an empty Linux server to the real website, on your
own domain, with HTTPS, a firewall and backups. Follow it from top to bottom.
Every command is written out; nothing is left to guess.

**Want to try the site on your own computer first** (no domain, nothing public)?
Use [`TEST_COMPUTER.md`](TEST_COMPUTER.md). Do that before this guide, and come
back here when you are happy with it.

Two documents are kept up to date with every change to the site:

- **`GUIDE.md`** (this file): how to run the site on a server.
- **[`AUDIT_LOG.md`](AUDIT_LOG.md)**: what was changed, why, and how to undo it.
  It also has a one-page map of the site, the database migration list and the
  rollback steps.

> **How these commands were checked.** The command blocks come from earlier
> versions of this guide, which were run for real on Ubuntu 24.04 (the `.env`
> generator, the owner tool, every database migration on PostgreSQL 16, the API,
> a worker on all nine queues, the scheduler, the web gateway, the Caddyfile
> with `caddy validate`, both Compose files with `docker compose config`) and,
> up to the first start, on **Ubuntu 26.04** in a VMware VM (Docker 29.8, Compose
> v5.6: the image build, all 13 services healthy, the migrations, Tesseract's
> languages and an update). **Not run for real:** Let's Encrypt, the Cloudflare
> steps and a full run on a rented server. Treat your first run as a test and
> use [Troubleshooting](#17-troubleshooting) if something differs.

Contents

0. [What you need](#0-what-you-need)
1. [How to copy commands so they match](#1-how-to-copy-commands-so-they-match)
2. [Prepare the server](#2-prepare-the-server)
3. [Point your domain at the server (DNS)](#3-point-your-domain-at-the-server-dns)
4. [Download the website](#4-download-the-website)
5. [Create the settings file (`.env`)](#5-create-the-settings-file-env)
6. [Google sign-in and the owner e-mail](#6-google-sign-in-and-the-owner-e-mail)
7. [Production mode and private ports](#7-production-mode-and-private-ports)
8. [Start the site](#8-start-the-site)
9. [HTTPS with Caddy, and start on boot](#9-https-with-caddy-and-start-on-boot)
10. [Become the owner](#10-become-the-owner)
11. [First settings after launch](#11-first-settings-after-launch)
12. [Hide the server's real IP address](#12-hide-the-servers-real-ip-address)
13. [Backups](#13-backups)
14. [Updating safely and rolling back](#14-updating-safely-and-rolling-back)
15. [Move to a new domain if yours is taken down](#15-move-to-a-new-domain-if-yours-is-taken-down)
16. [Everyday commands](#16-everyday-commands)
17. [Troubleshooting](#17-troubleshooting)
18. [Quick checklist](#18-quick-checklist)
19. [Start again from zero](#19-start-again-from-zero)
20. [Appendix: the admin area](#20-appendix-the-admin-area)

---

## 0. What you need

| Thing | Notes |
| --- | --- |
| **A Linux server** | Ubuntu 22.04, 24.04 or 26.04 (64-bit), or Debian 12. **2 CPU / 4 GB RAM / 40 GB disk** is comfortable. 1 GB RAM / 1 CPU works with the small profile ([Section 7](#small-server-1-gb-ram)). Chapter pictures take most of the disk: plan for your library. A cloud VM (Hetzner, DigitalOcean, AWS, Google Cloud...) is just Ubuntu. |
| **A domain name** | For example `manga.example.com`. You point it at the server in Section 3. |
| **A Google sign-in client for that domain** | You become the owner by signing in with Google. Section 6 says exactly what to create. |
| **A phone with an authenticator app** | Google Authenticator, Microsoft Authenticator, Aegis, 1Password... |
| **An SMTP account (optional at first)** | To e-mail readers their sign-in links. Can be added later in the Secret Vault. |
| **Another place to keep copies** | Your `.env` and your backups must exist somewhere other than this server. |

**What gets installed** (all inside Docker, so nothing else is installed on the
server):

| Piece | What it does |
| --- | --- |
| Web (`web`) | The React website, served by nginx on port 8080 (inside the server only) |
| API (`backend`) | FastAPI: sign-in, series, chapters, admin |
| PostgreSQL | All data |
| Redis | Cache, rate limits, job queue |
| Celery workers (8, or 2 on a small server) | Series import, scraping, WebP compression, OCR, translation, e-mail, notifications |
| Celery beat | The scheduler that checks series for new chapters |
| Storage volume | Chapter pages, covers, branding, avatars, backups |

**Imports and new chapters only work when the API, database, Redis, the workers
and beat all run.** If only the website ran, pages would load but nothing would
be imported.

**Where it cannot run:** Google AI Studio (it cannot run PostgreSQL, Redis or
long-running workers) and Google Cloud Shell (temporary, no public domain).

---

## 1. How to copy commands so they match

Almost every "the command doesn't work" report comes from the same few things.

**1. Copy one block at a time, and wait for the prompt.** Paste a block, press
Enter, wait until the `$` prompt comes back, read the last lines, then paste the
next block. Lines starting with `#` are comments; copying them is harmless.

**2. Never paste a placeholder.** `manga.example.com`, `you@example.com`,
`203.0.113.10` are examples. Every runnable block here that needs *your* value
sets it on its **first line** (for example `DOMAIN=manga.example.com`). Change
that line first.

**3. Be in the project folder.** Every `docker compose ...` command only works
inside the folder that holds `docker-compose.yml`:

```bash
cd ~/manga-website-v1.01
ls docker-compose.yml
```

It must print `docker-compose.yml`. *"no configuration file provided: not
found"* means you are in the wrong folder.

**4. One command per line.** `docker compose ps docker compose ps -a` pasted on
one line fails with *"no such service: docker"*.

**5. Use the names that really exist:**

| Thing | Real name |
| --- | --- |
| Project folder | `~/manga-website-v1.01` |
| Services (for `docker compose logs`, `exec`, `restart`, `up`) | `db`, `redis`, `manga-stack-migrate`, `backend`, `web`, `celery_beat`, `celery_worker`, `celery_worker_scrape`, `celery_worker_compress`, `celery_worker_ocr`, `celery_worker_translation`, `celery_worker_email`, `celery_worker_maintenance`, `celery_worker_notifications` (small profile: only `db`, `redis`, `manga-stack-migrate`, `backend`, `web`, `celery_beat`, `celery_worker`, `celery_worker_scrape`) |
| Containers (for plain `docker logs`) | `manga-stack-db`, `manga-stack-redis`, `manga-stack-backend`, `manga-stack-web`, `manga-stack-migrate`, `manga-stack-celery-beat`, `manga-stack-celery-worker`; the other workers are `manga-stack-celery_worker_scrape-1` and so on |
| Docker project, volumes | `manga-stack`; `manga-stack_db-data`, `manga-stack_app-storage` |
| Database | user **`manga`** (there is no `postgres` user), database `manga`: `docker compose exec db psql -U manga manga` |
| Files inside the backend container | `/app/backend_fastapi/...` (scripts in `/app/backend_fastapi/scripts/`), pictures in `/app/storage` |
| Settings file | `.env` in the project folder |

**6. Your Ubuntu version doesn't matter.** The containers bring their own Python
and Node. The only thing the server runs itself is one `python3` script
(`make_env.py`, standard library only). Don't install `python3.11`, `pip`, `nvm`
or `libpq-dev`.

**7. Keep secrets out of chats, tickets and screenshots.** `.env` holds your keys.
If you pasted one somewhere, make new ones (Section 19).

---

## 2. Prepare the server

Log in to the server from your own computer (use your server's IP and user):

```bash
ssh your-user@203.0.113.10
```

(Your hosting provider's welcome e-mail or dashboard shows the IP and the user.
On Windows 10/11 the same command works in PowerShell.)

### 2.1 Update, and install the basics

```bash
sudo apt-get update
sudo apt-get -y upgrade
sudo apt-get install -y git curl ca-certificates python3 ufw
```

Optional but recommended: let the server install security updates by itself.

```bash
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

(Answer **Yes** when it asks.)

### 2.2 Firewall

Only ports **22 (SSH), 80 and 443** may be reachable from the internet, never
8000, 8080, 5432 or 6379. Set the same in your provider's firewall / security
group if it has one, and on the machine with `ufw`. **Allow SSH first, or you
lock yourself out** (`ufw enable` asks for a `y`):

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

`ufw` alone does **not** protect Docker's published ports. Section 7 fixes that.

### 2.3 Docker

Docker Engine and the Compose plugin (Docker's official installer; it also
enables the Docker service at boot):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

**Reboot** so the group change takes effect (`sudo reboot`, then connect again
with `ssh`). Then check:

```bash
groups
docker --version
docker compose version
docker run --rm hello-world
```

`groups` must list `docker`. `docker compose version` must be **v2.24 or newer**
(Section 7 relies on it). The last command prints `Hello from Docker!`.

*"permission denied ... docker.sock"* does **not** mean the install failed: the
version lines prove Docker is installed. It means this terminal was opened
before you joined the `docker` group. Reboot and check again. **Don't reinstall
Docker** because of this message.

> ⚠ **Install Docker from one source only.** Docker's installer puts in
> `docker-ce` and `docker-compose-plugin`. Ubuntu's own `docker.io` and
> `docker-compose-v2` are a *second* copy. Installing them on top removes
> `docker-ce`, then stops half-way with `trying to overwrite
> '/usr/libexec/docker/cli-plugins/docker-compose'`.

Only if Docker's installer itself **failed** (it said your Ubuntu release is not
supported and `docker --version` says `command not found`), use Ubuntu's own
packages instead, then reboot and repeat the checks:

```bash
sudo apt-get install -y docker.io docker-compose-v2
sudo usermod -aG docker "$USER"
```

**Repair a mixed install** (you ran both the installer and the `docker.io`
packages, or `apt` says *"N not fully installed or removed"*). This puts back
Docker's official packages and removes Ubuntu's copy; it does not touch images,
volumes or your site's data:

```bash
sudo apt-get remove --purge -y docker.io docker-compose-v2 containerd runc
sudo dpkg --configure -a
sudo apt-get install -f -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
sudo reboot
```

### 2.4 Keep Docker's logs from filling the disk

By default container logs grow forever. Set a cap *before* the first start (it
applies to containers created afterwards; restarting Docker briefly stops
running containers):

```bash
test -f /etc/docker/daemon.json && echo "daemon.json exists: add the log-opts by hand" || {
  sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
  sudo systemctl restart docker
}
```

### 2.5 A swap file (servers with 2 GB RAM or less)

Building the images needs more memory than running the site. Without swap the
kernel may kill the build (`Killed`, exit code 137):

```bash
free -h                                  # is there already swap?
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 3. Point your domain at the server (DNS)

At your domain's registrar (or Cloudflare), create an **A record**
`manga.example.com` → your server's IP address. Wait until the server itself can
see it; this must print your server's IP (put your domain on the first line):

```bash
DOMAIN=manga.example.com
getent hosts "$DOMAIN"
```

Nothing printed yet? DNS is still spreading: wait a few minutes and run it again.
Do not continue until it prints the right IP, or HTTPS (Section 9) cannot get its
certificate.

---

## 4. Download the website

```bash
cd ~
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

Every command from here on runs **inside this folder**. In a new terminal, first
run `cd ~/manga-website-v1.01`.

---

## 5. Create the settings file (`.env`)

`.env` holds only the server's foundation: the database and Redis connection,
the site address, the signing and encryption keys and the owner identity. Your
Google client ID and secret also start here (you need Google to become the
owner). **Everything else** (e-mail, OCR, translation, API keys, limits) is set
later in **Admin → Secret Vault**, encrypted in the database.

### 5.1 Create it with fresh secrets

One command creates `.env` from `.env.example` with new random secrets and
database/Redis passwords that match inside the URLs. It never overwrites an
existing `.env`. **For a real server, run it without `--local`:**

```bash
python3 backend_fastapi/scripts/make_env.py
chmod 600 .env
```

You should see `Created .../.env with new random secrets.` The `chmod` makes the
file readable only by you: it holds every secret.

> **Don't make the secrets by hand.** Each password appears in several lines. A
> hand edit of only `POSTGRES_PASSWORD` leaves the old example password inside
> `DATABASE_URL`, and the result is `password authentication failed`.
> `make_env.py` fills all of them consistently.

### 5.2 Back it up now

Two keys in `.env`, `EMAIL_ENCRYPTION_KEY` and `INTEGRATIONS_SECRET`, unlock data
in the database. Lose them and every stored e-mail and API key becomes
unreadable.

```bash
mkdir -p ~/manga-backups && chmod 700 ~/manga-backups
cp .env ~/manga-backups/env-first && chmod 600 ~/manga-backups/env-first
```

Then copy that file **off the server** too: a password manager or an encrypted
USB stick. Never e-mail it.

### 5.3 Set your domain (and production mode)

Put your domain on the first line. This sets every address line and switches the
settings to production mode:

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

The result must match this table (fix by hand with `nano .env` if not; `Ctrl+O`,
Enter to save, `Ctrl+X` to leave):

| Variable | Value |
| --- | --- |
| `FRONTEND_URL` | `https://manga.example.com` |
| `BACKEND_URL` / `BACKEND_ORIGIN` | `http://backend:8000` (inside Docker) |
| `ALLOWED_ORIGINS` | `https://manga.example.com` |
| `CORS_ALLOWED_ORIGINS` | `["https://manga.example.com"]` |
| `MAGIC_LINK_REDIRECT_URL` | `https://manga.example.com/auth/magic-complete` |
| `GOOGLE_OAUTH_REDIRECT_URI` | `https://manga.example.com/api/auth/google/callback` |
| `MICROSOFT_OAUTH_REDIRECT_URI` | `https://manga.example.com/api/v1/auth/microsoft/callback` |
| `FORCE_HTTPS_REDIRECTS` | `true` (**leave it**: the backend refuses to start in production without it) |
| `APP_ENV` / `ENVIRONMENT` | `production` |

`APP_ENV=production` in `.env` alone does nothing in Docker, because
`docker-compose.yml` sets `APP_ENV: development` itself. Section 7 fixes that
without editing `docker-compose.yml`.

Behind a proxy or load balancer in front of Caddy (for example Cloudflare, Section
12)? Add its network ranges to `TRUSTED_PROXY_CIDRS` in `.env` so the site sees
the visitor's real address. Caddy on the same machine needs nothing.

### 5.4 Check the file

```bash
docker compose config > /dev/null && echo "compose file OK"
grep -nE '^[A-Z_]+=.*(example-|changeme|<generate)' .env || echo "no leftover placeholders"
ls -l .env
```

You should see `compose file OK`, `no leftover placeholders` and a line starting
with `-rw-------`. Then check that the passwords inside the URLs match the two
password lines (it prints only counts, never the passwords):

```bash
PGPW=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
RDPW=$(grep '^REDIS_PASSWORD=' .env | cut -d= -f2-)
echo "Database URL has the right password: $(grep -c "^DATABASE_URL=.*:${PGPW}@db:" .env)   (want 1)"
echo "Redis URLs have the right password:  $(grep -cE "^(REDIS_URL|CELERY_BROKER_URL|CELERY_RESULT_BACKEND)=.*:${RDPW}@redis:" .env)   (want 3)"
```

It must print `1` and `3`. Anything else: the file was edited by hand; make a
clean one (Section 19).

---

## 6. Google sign-in and the owner e-mail

There is **no admin password and no special admin page**. You become the owner
by signing in with Google, once, using the e-mail you choose. Two things in
`.env` make that work: a Google sign-in client, and a hash of your e-mail (the
e-mail itself is written nowhere on the server).

### 6.1 Create the Google client

1. Open <https://console.cloud.google.com/> and pick (or create) a project.
2. **APIs & Services → OAuth consent screen**: choose *External*, fill the app
   name and your e-mail, save. While the app is in "Testing", add the Gmail you
   will sign in with under **Test users**.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized JavaScript origins: `https://manga.example.com` (your domain)
   - Authorized redirect URIs: `https://manga.example.com/api/auth/google/callback`
     (it must match `GOOGLE_OAUTH_REDIRECT_URI` in `.env` exactly)
4. Copy the **Client ID** and the **Client secret**.
5. Put them in `.env`:

   ```bash
   nano .env
   ```

   Fill in `GOOGLE_OAUTH_CLIENT_ID=` and `GOOGLE_OAUTH_CLIENT_SECRET=` (no quotes,
   no spaces), save and leave.

### 6.2 Write the owner line

This runs in a throw-away container, so no Python packages are needed on the
server. It asks for your e-mail (the Google e-mail you will use as the owner):

```bash
docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
```

It ends with `Done: the line is now in .env`. The line (`MAIN_ADMIN_EMAIL_HASH=a2:...`)
contains no `$`, so nothing can mangle it.

---

## 7. Production mode and private ports

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

Compose picks the file up by itself. If it says *unknown tag `!override`*, your
Docker Compose is too old: update Docker (Section 2.3).

### Small server (1 GB RAM)

The default stack starts eight background workers and four API workers (about
2.5 GB of memory). On a small server use the small profile. One line in `.env`
makes it permanent, so every later `docker compose` command uses it. **Naming
files in `COMPOSE_FILE` switches off automatic loading, so the override file must
be listed too:**

```bash
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml:docker-compose.override.yml' >> .env
docker compose config --services      # db redis manga-stack-migrate backend web celery_beat celery_worker celery_worker_scrape
```

The small profile runs two background workers: `celery_worker` (readers'
translations, OCR, e-mail, notifications) and `celery_worker_scrape` (scraping,
picture compression, maintenance), 2 API workers, small database pools and memory
caps for Postgres and Redis. The sizes are written in `docker-compose.small.yml`
itself. Data is the same, so you can switch between small and full later. Add the
swap file from Section 2.5 before the first build.

Both setups recycle their workers (an API worker after about 2000 requests, a
background worker after 200 jobs or 400 MB), so memory doesn't creep up over
days. Tune with `GUNICORN_MAX_REQUESTS`, `CELERY_MAX_TASKS_PER_CHILD`,
`CELERY_MAX_MEMORY_PER_CHILD_KB` in `.env` (0 turns a limit off). Each API worker
translates at most `PAGE_PROCESSING_CONCURRENCY` pages at once (default 2).

---

## 8. Start the site

```bash
cd ~/manga-website-v1.01
docker compose up -d --build
```

The first build takes 5-15 minutes and prints hundreds of lines; that is normal.
It builds and starts, in order: PostgreSQL, Redis, the **migrations** (create
every table), the API, the workers, beat, and the web server. When the `$` prompt
comes back:

```bash
docker compose ps
```

You should see **13 services** (`backend`, `celery_beat`, `celery_worker`, seven
`celery_worker_...`, `db`, `redis`, `web`), all `Up`. For the first minute the
workers say `(health: starting)`: run the command again every minute until every
line says `(healthy)`. (On the small profile there are 7 lines.)
`manga-stack-migrate` is not in the list because it ran once and stopped:

```bash
docker compose ps -a
docker compose logs manga-stack-migrate | tail -5
```

It shows `Exited (0)`, and its log ends with `[INFO] System state ready`. Then:

```bash
curl http://localhost:8000/healthz
curl -I http://localhost:8080
```

The first prints `{"ok":true}`; the second starts with a line containing `200`.
Both answer **on the server itself only**: that is what Section 7 set up.

Prove the ports are private. Run this **from your own computer**, not the server
(use your server's IP); both must fail or time out:

```bash
SERVER_IP=203.0.113.10
curl -sS -m 6 "http://$SERVER_IP:8080/" || echo "8080: no answer (good)"
curl -sS -m 6 "http://$SERVER_IP:8000/healthz" || echo "8000: no answer (good)"
```

Something not `healthy` after three minutes? Read its log (the example uses
`backend`; use the service name from `docker compose ps`) and look the message up
in [Troubleshooting](#17-troubleshooting):

```bash
docker compose logs --tail 50 backend
```

---

## 9. HTTPS with Caddy, and start on boot

The `web` container speaks plain HTTP on `127.0.0.1:8080`, so a TLS reverse proxy
goes in front. Caddy on the server fetches and renews Let's Encrypt certificates
by itself and sends `X-Forwarded-Proto`, which the backend uses to avoid redirect
loops. Ports 80 and 443 must be open and DNS (Section 3) must already point at
the server, or the certificate request fails.

```bash
DOMAIN=manga.example.com
sudo apt-get install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$DOMAIN {
    reverse_proxy 127.0.0.1:8080
}
EOF
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
curl -I "https://$DOMAIN"
```

The last command must answer `200` over HTTPS. If not: `sudo journalctl -u caddy -n 50`.
*"Unable to locate package caddy"* (Ubuntu 22.04): add Caddy's own repository
first, see <https://caddyserver.com/docs/install#debian-ubuntu-raspbian>.

(Prefer nginx + certbot? `deployment/manga-site.conf` and
`deployment/renew_certificates.md` are a *reference*: the config points at the
Docker names and a static folder, so adapt it before use.)

### Start on boot

The containers use `restart: unless-stopped` and Docker's installer enables the
Docker service. Check it, and prove it with a reboot:

```bash
systemctl is-enabled docker            # enabled
sudo reboot
```

After you log in again:

```bash
cd ~/manga-website-v1.01
docker compose ps
```

Everything must come back by itself (healthy after a minute). Do **not** run
`backend_fastapi/deployment/setup-server.sh`: besides Docker it turns off SSH
password and root login (you would be locked out without an SSH key), installs a
package that only exists in Docker's own repository, and expects the project in
`/var/www/manga`.

Open `https://manga.example.com` in a browser: the home page with the padlock.
It is empty, and nobody is the owner yet.

---

## 10. Become the owner

Sections 6 and 8 already put the Google client and the owner line in `.env`
before the first start. Check that the server sees them (wait about 30 seconds
after the start):

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap admin-status
```

You want:

```
MAIN_ADMIN_EMAIL_HASH: set
Google sign-in: set up
Owner: not claimed yet -- sign in with Google using the owner e-mail.
```

If a line differs, you edited `.env` after the start: run
`docker compose up -d --force-recreate` (**not** `restart`: a restart keeps the
old settings) and check again.

1. **Over HTTPS only** (never over plain `http://` on a public address): open the
   site → **Log in** → **Continue with Google** and pick the Google account with
   the owner e-mail. Google must say the address is verified.
2. The first time, the site asks you to complete your profile (display name,
   username, birth date) like every new account. You are now the owner;
   `admin-status` says `Owner: claimed`, and nobody else can ever claim the seat.
3. Open **Admin**. It asks you to set up an authenticator app. In the app:
   **+** → **Enter a setup key** (type *Time based*), add the key shown, and type
   the 6-digit code. Admin pages stay shut until you have; from then on every
   admin page, Admin Settings and the Secret Vault ask for a fresh code.

**Why a stolen Gmail password isn't enough:** someone who gets into your Google
account can sign in as you, but every admin page still asks for the code on your
phone. The owner's authenticator can't be turned off from the website, only on
the server.

**Google doesn't make me the owner?** Test what is in `.env`:

```bash
docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --check .env"
```

It tells you whether the e-mail matches or the line is damaged. Use exactly that
Google address, and check `admin-status` doesn't already say `Owner: claimed`.

**Lost your phone?** Put your e-mail on the first line, then sign in with Google
and open **Admin**: it asks you to set up the new phone.

```bash
OWNER_EMAIL=you@example.com
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email "$OWNER_EMAIL"
```

**Need a sign-in link without e-mail** (a normal session; admin pages still ask
for the code)? Open the printed link in your browser:

```bash
OWNER_EMAIL=you@example.com
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap login-link --email "$OWNER_EMAIL"
```

Other server-side tools: `cli_bootstrap functions-reset` puts every Site Function
back to its default; `cli_bootstrap geolock-off` switches Geolock off if you
blocked your own country.

---

## 11. First settings after launch

All in **Admin**, as the owner. The Secret Vault asks for your authenticator code
and stays open 10 minutes.

1. **Secret Vault** (**Admin → Secret Vault**): set what you need.
   - **Email & magic links**: your SMTP settings (`EMAIL_BACKEND=smtp`,
     `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
     `EMAIL_FROM_ADDRESS`), so readers get sign-in links. Until then, links are
     printed in the log (`docker compose logs -f celery_worker_email`; small
     profile: `celery_worker`).
   - **Translation & OCR → Server OCR enabled = true**, then restart the API and
     workers:

     ```bash
     docker compose restart backend celery_beat $(docker compose config --services | grep '^celery_worker')
     ```

   - **Microsoft sign-in**, Sentry and the rest, if you use them. The Google
     client may be moved here too; then delete its lines from `.env`. Keep `.env`
     itself: without `INTEGRATIONS_SECRET` the vault cannot be decrypted.
2. **Branding and footer**: site name, logo, homepage heading, your own social
   links. Save them as the owner: what the server stores is what every visitor
   sees.
3. **Site Functions** (**Admin → Site Functions**, owner only): the on/off switch
   of every main function. **Sign-in required** starts **off** so guests can
   read. Leave it off while you set up; switch it on once your Admins are in
   place if you want every visitor to log in first. See [Section 20](#20-appendix-the-admin-area).
4. **Role Management**: Admins (at most two), sub-admins, seats, succession and
   tab access. See Section 20.
5. **Import your first series**: **Admin → Series Management → Import & Scrape Manga**. Only
   import content you have the rights to host. See Section 20.

---

## 12. Hide the server's real IP address

Anyone can look up which websites share an IP address ("reverse IP"), and
scanners test every address on the internet directly. If your server's real IP is
known, it can be attacked, bypassing everything in front of it. So keep it out of
sight. (This cannot be fixed inside the application.)

1. **Put a CDN / proxy in front** (Cloudflare's free plan is enough): point your
   DNS at it with the proxy switched on (orange cloud). Visitors then see
   Cloudflare's addresses, never yours. Add `TRUSTED_PROXY_CIDRS` in `.env` with
   the CDN's ranges so the site still sees the visitor's real address (see "Proxy
   / client-IP trust boundary" in `.env.example`), then
   `docker compose up -d --force-recreate`.
2. **Let only the CDN reach ports 80/443.** With `ufw`, allow 80/443 from the
   CDN's published ranges only (not from everywhere), keep 22 for yourself, deny
   the rest. Better still, use a **tunnel** (`cloudflared`): the server then opens
   no public port at all.
3. **Answer nobody who asks for the bare IP or an unknown name.** With Caddy only
   your domain is served; test it below.
4. **Don't leak the address elsewhere:**
   - no DNS record (including `mail.`, `ftp.`, old test names) that points at the
     real IP without the proxy;
   - send e-mail through your mail provider (SMTP in the Secret Vault), not from
     the server itself: e-mail headers show the sender's IP;
   - don't put the IP in any public page, repository or screenshot;
   - **if the real IP was ever public** (it was in DNS before you added the
     proxy), the old address stays known: ask your host for a new one.
5. **Test it** from another computer (use your real IP and domain):

   ```bash
   SERVER_IP=203.0.113.10
   DOMAIN=manga.example.com
   curl -sS -m 8 -o /dev/null -w "bare IP over http:  %{http_code}\n" "http://$SERVER_IP/" || echo "bare IP over http: no answer (good)"
   curl -sSk -m 8 -o /dev/null -w "bare IP over https: %{http_code}\n" "https://$SERVER_IP/" || echo "bare IP over https: no answer (good)"
   curl -sS -m 8 -o /dev/null -w "domain: %{http_code}\n" "https://$DOMAIN/"
   ```

   The first two should give no answer (or `000`/`444`); the domain should answer
   `200`. Also open `https://<server-ip>` in a browser: it must not show your site.

**Visitors' addresses inside the site** are a separate matter: the audit log and
the ad-click log keep them, and only the owner can see them (Section 20).

---

## 13. Backups

Do this before you add content. Three things hold your site's state:

| What | Where | Back it up with |
| --- | --- | --- |
| Database | `db-data` volume | `pg_dump` through the `db` container (below), or Admin → Storage & Backups |
| Chapter images, covers, backups | `app-storage` volume | `tar` through the `backend` container (below), or Admin → Storage & Backups |
| **Your `.env`** (above all `EMAIL_ENCRYPTION_KEY`, `INTEGRATIONS_SECRET`) | the server | copy it somewhere safe and private; without these keys encrypted data cannot be recovered |

The database user is **`manga`** and the database is `manga`; there is no
`postgres` user, so `pg_dumpall -U postgres` fails with *role "postgres" does not
exist*. The ready-made scripts in `backend_fastapi/deployment/` (`backup_postgres.sh`,
`backup_storage.sh`) assume a database on `localhost:5432` and pictures in
`/app/storage`; in this Docker setup neither is true, so use the commands below
or the admin panel.

### 13.1 Nightly backup with cron

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

That keeps copies on the same server, which does not survive losing the server.
**Copy `~/manga-backups` off the machine** too, for example (from another
computer, with your own user and host):

```bash
rsync -av your-user@203.0.113.10:manga-backups/ ~/manga-backups-copy/
```

The `.env` copies hold every secret: store them like passwords.

### 13.2 From the admin panel: Storage & Backups

**Admin → Storage & Backups** (the owner and Admins; never a sub-admin) does the
same from the website:

1. **Set a backup password** first (at least 10 characters) and write it down
   **off the server**. Every backup is then encrypted; without the password no
   backup can be restored, here or on a new server.
2. **Weekly backup** is on by default: Sunday 03:00 UTC, the newest 2 kept,
   pictures included. Change the day, hour, how many to keep and whether pictures
   go in. A backup with pictures is about as big as your pictures folder; it is
   refused (not half-made) when the disk lacks room.
3. **Back up now** makes one immediately. **Download** saves any backup to your
   computer.
4. **Connect storage** to copy every backup off the server: any S3-compatible
   storage (paste the endpoint, bucket, region and an access key limited to that
   bucket, press **Test connection**, then **Connect**). Examples: Cloudflare R2
   `https://<account-id>.r2.cloudflarestorage.com`, region `auto`; Backblaze B2
   `https://s3.<region>.backblazeb2.com`, region e.g. `us-west-004`.
5. **Restore**: press Restore on a backup, type `RESTORE`. A database-only safety
   copy of the current site is made first. Then restart so a restored database
   from an older version is upgraded: `docker compose up -d --force-recreate`.

**Moving to a new server:** install the site (Sections 2-9) with the **same
`.env`** (above all `EMAIL_ENCRYPTION_KEY` and `INTEGRATIONS_SECRET`), sign in,
open Storage & Backups, then either **Upload a backup** from your computer or
connect the same storage and **Bring to this server**, and Restore it with the
backup password.

Backups live in the `app-storage` volume under `backups/` (never served to
visitors). Put `BACKUP_DIR` on another disk in `.env` if the main one is small.
More detail: `backend_fastapi/deployment/backups.md` and `deployment/runbook.md`.

**Test a restore** at least once, on a spare machine, before you need it. A
backup you have never restored is a hope, not a backup.

---

## 14. Updating safely and rolling back

Do this every time you update a live site.

### 14.1 Before updating

```bash
cd ~/manga-website-v1.01

# 1. Note where you are now (write these two lines down).
git log -1 --oneline                                   # code version
docker compose exec backend alembic current            # database version

# 2. Back up the database, the images and .env (the script from Section 13.1):
~/manga-backup.sh

# 3. Fetch the update and read what changed since your version.
git fetch origin
git log --oneline --first-parent HEAD..origin/main     # the PRs you're about to get
git diff HEAD..origin/main -- AUDIT_LOG.md .env.example GUIDE.md TEST_COMPUTER.md
```

In that diff, look for:

- **new `.env` keys** in `.env.example`: add them before restarting;
- **Database** lines in the new `AUDIT_LOG.md` entries: a migration marked
  **lossy** makes the backup in step 2 essential;
- **Settings** lines: new switches or vault values you may want to set.

### 14.2 Update

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
`AUDIT_LOG.md` entries. The backend image is where Tesseract and its
Korean/Japanese/Chinese data live, so after `git pull` **rebuild**: restarting is
not enough. To check Tesseract:

```bash
docker compose exec backend tesseract --list-langs
```

It must list `chi_sim chi_tra eng jpn jpn_vert kor osd`. If the build ever seems
to reuse an old image: `docker compose build --pull --no-cache` and then
`docker compose up -d --force-recreate`.

### 14.3 Roll back

Pick the smallest step that fixes it (details in `AUDIT_LOG.md` §3):

1. **Switch it off**: many features have a switch (Site Functions, Secret Vault).
2. **Go back to the previous code version** (keeps the database). In 14.1
   `git log -1 --oneline` printed something like `178bb3d Merge pull request #37 ...`;
   the first word is the version. Put yours on the first line:

   ```bash
   OLD_VERSION=178bb3d
   git checkout "$OLD_VERSION"
   docker compose build --pull && docker compose up -d --force-recreate
   ```

   Newer database columns are ignored by older code. The migration service will
   report the database is ahead; that is expected until you update again. To
   return to the latest code later: `git checkout main && git pull --ff-only`.
3. **Also undo database changes**: before step 2, run this with the database
   version `alembic current` printed in 14.1 (for example `20261013_admin_succession`):

   ```bash
   DB_VERSION=20261013_admin_succession
   docker compose run --rm manga-stack-migrate alembic downgrade "$DB_VERSION"
   ```

4. **Lossy migration, or data looks wrong**: restore the backup from 14.1. See
   which backups you have:

   ```bash
   ls ~/manga-backups
   ```

   Put the date part of the one you want on the first line (`db-2026-10-02-1530.dump`
   → `2026-10-02-1530`):

   ```bash
   BACKUP_STAMP=2026-10-02-1530
   docker compose stop backend celery_beat $(docker compose config --services | grep '^celery_worker')
   docker compose exec -T db pg_restore -U manga -d manga --clean --if-exists < ~/manga-backups/db-$BACKUP_STAMP.dump
   docker compose up -d --force-recreate
   ```

   Only if the pictures were lost or damaged too (this works while the site runs):

   ```bash
   docker compose run --rm --no-deps -T --entrypoint tar backend xzf - -C /app/storage < ~/manga-backups/storage-$BACKUP_STAMP.tgz
   ```

To undo one change permanently, revert its merge commit on `main` (the merge
commit is listed in each `AUDIT_LOG.md` entry), push, and update as in 14.2:

```bash
MERGE_SHA=178bb3d
git revert -m 1 "$MERGE_SHA"
```

### 14.4 Keeping this guide useful

Whenever the site changes, the same pull request adds an entry to `AUDIT_LOG.md`
(what, why, files, database, settings, check, **undo**) and updates the guide
where installing, configuring, updating or running the site changed: the section
itself, the [Troubleshooting](#17-troubleshooting) table and the
[Quick checklist](#18-quick-checklist). The PR template and `CLAUDE.md` list these
as required steps.

---

## 15. Move to a new domain if yours is taken down

The site address, allowed origins and the Google / Microsoft / magic-link return
addresses all come from one value, **Website domain**, in the Secret Vault. The
data, accounts and settings stay as they are.

1. **Pick the new domain** and at its registrar create an `A` record
   `new-domain.com` → your server's IP (and `www` if you want it). With Cloudflare,
   add the site there and point the record at the server.
2. **HTTPS for the new name** (Caddy): add the name to the Caddyfile and reload; it
   fetches the certificate by itself:

   ```bash
   OLD_DOMAIN=manga.example.com
   NEW_DOMAIN=new-domain.com
   sudo sed -i "s/^$OLD_DOMAIN {/$OLD_DOMAIN, $NEW_DOMAIN, www.$NEW_DOMAIN {/" /etc/caddy/Caddyfile
   sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
   sudo systemctl reload caddy
   ```

3. **Switch** (a few clicks): **Admin → Secret Vault** → unlock with your
   authenticator code → **Website domain** card → type `new-domain.com` →
   **1. Check**. When all three ticks are green (DNS, HTTPS, "it is this site"),
   click **2. Switch to this domain**. It applies within seconds with no restart:
   links in e-mails, sign-in callbacks and CORS use the new address. (DNS still
   spreading? Tick "Switch anyway".)
4. **Sign-in providers:** the card lists the new return addresses. Add them in the
   Google Cloud console (OAuth client → Authorized redirect URIs) and in Azure
   (App registration → Authentication). Until you do, Google / Microsoft sign-in
   fails on the new domain; magic links work right away.
5. Tell your readers (announcement, social links in the footer).

**Can't reach the admin page at all?** Do the switch from the server:

```bash
NEW_DOMAIN=new-domain.com
docker compose exec backend python -m backend_fastapi.scripts.set_site_domain "$NEW_DOMAIN"
```

To undo it and go back to the `FRONTEND_URL` from `.env`:

```bash
docker compose exec backend python -m backend_fastapi.scripts.set_site_domain --clear
```

A value you set explicitly in the vault for one of the derived keys (for example
`FRONTEND_URL`) wins over the domain; remove it if the switch seems to have no
effect. If a bad vault value ever stops the site from starting, set
`VAULT_PRELOAD_DISABLED=true` in `.env`, recreate the containers
(`docker compose up -d --force-recreate`), fix it in the vault, and remove the
flag again.

---

## 16. Everyday commands

```bash
cd ~/manga-website-v1.01
docker compose ps                               # what is running
docker compose logs -f backend                  # watch the API (Ctrl+C to stop); also celery_worker_scrape, celery_beat, web, db
docker compose logs --tail 100 backend          # the last 100 lines
docker compose restart backend                  # restart one service
docker compose up -d --force-recreate           # re-read .env (restart does NOT)
docker compose exec db psql -U manga manga      # database shell (\q to leave)
docker stats --no-stream                        # memory and CPU per container
free -h                                         # memory of the whole server
df -h /                                         # disk
docker system df                                # disk used by images, volumes, build cache
docker compose down                             # stop (data kept in volumes)
```

`docker compose down -v` stops **and deletes the database and uploaded pictures**.
Never use it to "free space" or "fix" something on a live site.

---

## 17. Troubleshooting

Look for the exact words you see. Most of these are a mismatch between the
command and the machine, not a broken site.

### Errors people hit while following this guide

| What you see | What it means and what to do |
| --- | --- |
| `cd: /path/to/...: No such file or directory`, or `cd: .../backend: No such file or directory` | You pasted an example path. The project is `~/manga-website-v1.01`. There is no `backend` folder; the API code is in `backend_fastapi/`. |
| `no configuration file provided: not found` | `docker compose` was run outside the project folder. `cd ~/manga-website-v1.01 && ls docker-compose.yml`. |
| `could not translate host name "db"` or `Error -3 connecting to redis:6379` | A Python or Celery command ran on the server with the Docker `.env`, where `db` and `redis` are Docker-only names. Run it inside Docker: `docker compose exec backend ...`. |
| `[Errno 98] Address already in use` or `port is already allocated` (8000 or 8080) | Something already listens there. See what: `sudo ss -ltnp \| grep -E ':(8000\|8080)\b'`. |
| `role "postgres" does not exist` | The database user is `manga`: use `-U manga`. |
| `python: can't open file '/app/scripts/...'` | Scripts inside the container are under `/app/backend_fastapi/scripts/`. |
| `no such service: migrate` | The service is called `manga-stack-migrate`. Section 1 lists every real name. |
| `no such service: docker` | Two commands were pasted onto one line. Run each on its own line. |
| `docker compose ps` doesn't list `manga-stack-migrate` | Normal: it ran once and stopped. `docker compose ps -a` shows `Exited (0)`. |
| `docker compose ps` shows `(health: starting)` | Normal for the first minute. Wait and run it again; every line should then say `(healthy)`. |
| `failed to solve: image "docker.io/library/manga-backend:latest": already exists` | Your `docker-compose.yml` is older than the fix (it built the same image once per worker at the same time). `git pull --ff-only`, then `docker compose up -d --build`. Can't update yet? `docker compose build backend web`, then `docker compose up -d` (no `--build`). |
| `permission denied ... /var/run/docker.sock` | Docker is installed; you are not in the `docker` group in this terminal yet. Reboot (Section 2.3). Don't reinstall Docker. |
| `docker: 'compose' is not a docker command` | The Compose plugin is missing (Ubuntu's `docker.io` lacks it). Use Docker's installer (Section 2.3). |
| `trying to overwrite '/usr/libexec/docker/cli-plugins/docker-compose'` or `apt` says `N not fully installed or removed` | Two copies of Docker were installed. Use *Repair a mixed install* (Section 2.3). |
| `unknown tag !override` / `yaml: unknown tag` | Docker Compose older than v2.24. Update Docker (Section 2.3). |
| `git pull` asks `Username for 'https://github.com'` | Press **Ctrl+C** (Enter would skip the pull and run the next commands on the old code). GitHub answered as if the repository were private, or the address in `git remote -v` is wrong. GitHub doesn't take your account password: use a *personal access token*, or make the repository public. |

### All other problems

| Symptom | Cause / fix |
| --- | --- |
| `Set EMAIL_ENCRYPTION_KEY to a Fernet key` | There is no `.env`, you are in the wrong folder, or the variable is empty. Section 5.1. |
| `password authentication failed` (database) or Redis `NOAUTH` | The passwords in `DATABASE_URL` / `REDIS_URL` / `CELERY_*` don't match `POSTGRES_PASSWORD` / `REDIS_PASSWORD` (usually a hand-edited `.env`). Run the check at the end of Section 5.4 (it must print `1` and `3`); the clean fix is Section 19. |
| `ModuleNotFoundError: psycopg` | `DATABASE_URL` must start `postgresql+psycopg2://`. |
| Backend exits at start-up about `FORCE_HTTPS_REDIRECTS` | You're in production mode with it `false`. Set it `true` (it needs HTTPS in front: Section 9). |
| The site still runs in development mode on the server | `docker-compose.yml` hard-codes `APP_ENV: development`; add the file from Section 7 and `docker compose up -d --force-recreate`. |
| Ports 8000/8080 answer from the internet although `ufw` blocks them | Docker bypasses `ufw` for published ports. Add the file from Section 7 (binds them to `127.0.0.1`) and `docker compose up -d --force-recreate`. |
| Caddy: no certificate / `ERR_SSL_PROTOCOL_ERROR` | DNS must point at this server and ports 80/443 must be open: `getent hosts manga.example.com`, `sudo ufw status`, `sudo journalctl -u caddy -n 50`. |
| Login or redirects loop | `FORCE_HTTPS_REDIRECTS=true` but the request reached the site as plain HTTP: make sure Caddy is in front and you open `https://`. |
| Imports stay "queued" forever | Workers or beat not running: `docker compose ps`. |
| Chapter has no pictures / slow | Look at the compress worker (`celery_worker_compress`; small profile: `celery_worker_scrape`) and the disk (`docker system df`, `df -h`). |
| Build dies with `Killed` / exit code 137 / `npm ci` stops | Out of memory. Add the swap file (Section 2.5) and run `docker compose up -d --build` again. |
| `no space left on device` | `df -h /` and `docker system df`. Free space with `docker image prune -f` (old images) and `docker builder prune -f` (build cache). Cap the logs (Section 2.4). `docker compose down -v` would delete your data: never use it for this. |
| Server slow, swapping, or containers killed for memory on a 1-2 GB server | Use the small profile (Section 7) and a swap file (Section 2.5). |
| A Secret Vault value stops the site from starting | Set `VAULT_PRELOAD_DISABLED=true` in `.env`, recreate the containers, fix the value, then remove the flag. |
| Site unreachable after switching the domain | DNS or HTTPS for the new name isn't ready. Run `set_site_domain --clear` on the server to go back (Section 15). |
| Signed in with Google but I'm not the owner | `cli_bootstrap admin-status` says why. *MAIN_ADMIN_EMAIL_HASH not set* → you used `restart`: run `docker compose up -d --force-recreate`. *DAMAGED* → an old raw hash pasted without quotes: make a new line (Section 6.2). *Owner: claimed* → the seat is already taken (ownership never passes). Otherwise `make_admin_hash.py --check .env` tells you whether the e-mail matches. |
| "Continue with Google" says not configured | `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` are missing in `.env` (and the vault), or the container wasn't recreated. Section 6.1. |
| Google says `redirect_uri_mismatch` | The redirect address in the Google console must equal `GOOGLE_OAUTH_REDIRECT_URI` exactly (`https://your-domain/api/auth/google/callback`). |
| Authenticator code refused | The phone's clock is off. Turn on automatic date & time on the phone, then type a fresh code (each lasts 30 seconds). |
| Lost the phone with the authenticator | `cli_bootstrap reset-2fa` (Section 10). |
| Admin pages say "Set up your authenticator app" | Expected on the owner's first visit: open **Admin**, add the setup key and type the code. |
| `$argon2id...` value turns into garbage | Wrap values containing `$` in single quotes in `.env`. Owner lines made by `make_admin_hash.py` start with `a2:` and have no `$`. |
| Visitors are sent to the login page | *Sign-in required* is on. It starts **off**. Switch it in **Admin → Site Functions**. |
| A feature says "... is switched off on this site" | You switched that function off in **Admin → Site Functions**. Switch it on, or run `cli_bootstrap functions-reset`. |
| Translation/OCR overlay does nothing | Reader: *Settings → Reading & Translation* must be on. Server: vault *Server OCR enabled* = true and restarted (Section 11). |
| Reader says "Text was found but not translated" | OCR works but nothing translates: add an AI key in the reader's *Settings → AI & OCR Engines*, or a site default in Admin → API Management. |
| `tesseract: not found` / OCR "engine not available" | The backend image is old: rebuild it (Section 14.2). |
| Readers don't get "new chapter" alerts | Alerts go to **signed-in** readers who bookmarked the series. Check *Notifications* is on in **Admin → Site Functions**. |
| A reader on a new phone sees no dimmed (already read) chapters | Read chapters follow **signed-in** readers only and appear once the first sign-in on that phone has finished (a few seconds; reload the series page). History read **as a guest** in another browser never left that browser: sign in there once, or use **Library → Export / Import**. |
| Backup says "Not enough free disk" | Delete old backups, keep fewer, turn off *Include pictures*, or set `BACKUP_DIR` to a bigger disk. |
| Backup "Storage copy failed" | The archive is safe on the server. Press *Test connection* in Storage & Backups to see why. |
| Restore says "Wrong backup password" | Enter the password that was set when that backup was made. |
| You blocked your own country with Geolock | `docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap geolock-off`. |
| API docs (`/docs`) missing | Intentional in production; set `EXPOSE_API_DOCS=true` only on a private deploy. |
| Custom Parser: "answered with a bot check" | The site shows a Cloudflare/CAPTCHA check to servers. It cannot be added; use another source. |
| Custom Parser: "No parser could read a title and a chapter list" | You pasted a homepage, list or chapter. Paste one series page with 2+ chapters. |

---

## 18. Quick checklist

- [ ] Server: Ubuntu 22.04/24.04/26.04 or Debian 12; swap on a 1-2 GB server; `ufw` allows only 22/80/443; your provider's firewall too
- [ ] Docker installed from one source only (`dpkg -l | grep -E 'docker|containerd'` doesn't show both `docker-ce` and `docker.io`); `docker compose version` is v2.24+; `groups` lists `docker`; log cap set
- [ ] DNS: `getent hosts your-domain` prints the server's IP
- [ ] `.env` made with `make_env.py` (no `--local`), `chmod 600 .env`, domain lines set (Section 5.3), the `1` and `3` password check passes, a copy kept **off** the server
- [ ] Google client created for the domain; `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` and the owner line (`make_admin_hash.py --write .env`) are in `.env`
- [ ] `docker-compose.override.yml` from Section 7 in place (production mode, ports on `127.0.0.1`); the ports test from another computer fails (good)
- [ ] `docker compose up -d --build`; all services healthy; `curl http://localhost:8000/healthz` answers `{"ok":true}`
- [ ] `docker compose exec backend tesseract --list-langs` lists `kor jpn chi_sim`
- [ ] Caddy serves `https://your-domain` with the padlock; a reboot brings everything back
- [ ] `admin-status` says `Owner: claimed` after your first Google sign-in over HTTPS; authenticator set up in **Admin**
- [ ] SMTP, OCR (and any API keys) entered in **Admin → Secret Vault**; *Server OCR enabled* on and services restarted
- [ ] Site name, logo, homepage heading and footer links saved as the owner; a private window shows them and shows no pencil
- [ ] *Sign-in required* left off (guests read) or switched on once your Admins are set up (Admin → Site Functions)
- [ ] Tab access set for each Admin and sub-admin (Role Management); the server's real IP hidden behind a CDN or tunnel and the bare-IP test run (Section 12)
- [ ] First series imported; new chapters arrive via beat
- [ ] Backups: nightly `~/manga-backup.sh` in cron and copied off the server; in **Admin → Storage & Backups** a backup password set (kept off the server), weekly schedule checked, R2/B2 connected if you use them; **a restore tested once**
- [ ] A reader signs in on a second browser or phone: bookmarks and dimmed chapters follow the account
- [ ] Admins (optional): at most two trusted sub-admins with an authenticator made Admins; seats, sub-admin ceiling and succession lines set
- [ ] `AUDIT_LOG.md` read; a backup taken before every update (Section 14)

More detail: `README.md`, `backend_fastapi/README.md`, `deployment/README.md`,
`deployment/runbook.md`, `deployment/key-rotation.md`.

---

## 19. Start again from zero

Use this when the site never worked, when `.env` was edited by hand and the
passwords no longer match, after pasting a secret somewhere public, or to test
this guide on a clean machine. **It deletes the database, every uploaded picture
and your `.env`.** Back up first if there is anything worth keeping.

**Step 1 - Back up (skip it if the site never ran).** The database user is `manga`:

```bash
cd ~/manga-website-v1.01
mkdir -p ~/manga-backups && chmod 700 ~/manga-backups
docker compose exec -T db pg_dump -U manga -Fc manga > ~/manga-backups/db-before-reset.dump
cp .env ~/manga-backups/env-before-reset && chmod 600 ~/manga-backups/env-before-reset
```

If it says the service `db` is not running, there is nothing to back up.

**Step 2 - Remove this project's containers, volumes and images:**

```bash
cd ~/manga-website-v1.01
docker compose down --volumes --rmi all --remove-orphans
```

That removes only what belongs to this project. `docker system prune -a --volumes -f`
is not needed: it also deletes unused data of every *other* Docker project on the
machine.

**Step 3 - Check that it is really gone:**

```bash
docker ps -a
docker volume ls
ss -ltn | grep -E ':(8080|8000)\b' || echo "ports 8080 and 8000 are free"
```

You should see no containers, no volumes, and `ports 8080 and 8000 are free`.

**Step 4 - Delete the folder and begin again** (from Section 4):

```bash
cd ~
rm -rf ~/manga-website-v1.01
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd ~/manga-website-v1.01
python3 backend_fastapi/scripts/make_env.py
chmod 600 .env
```

Then continue at Section 5.3.

**The project folder is already gone but the site still answers.** Without the
folder `docker compose down` can't run. Remove by the project label instead:

```bash
docker ps -aq --filter label=com.docker.compose.project=manga-stack | xargs -r docker rm -f
docker volume ls -q --filter label=com.docker.compose.project=manga-stack | xargs -r docker volume rm
docker network ls -q --filter label=com.docker.compose.project=manga-stack | xargs -r docker network rm
docker rmi manga-backend:latest manga-stack-web
```

(The last line may say an image doesn't exist; that is fine.) Then check as in
Step 3. Keep the project in `~/manga-website-v1.01` and backups in
`~/manga-backups`, and run Step 2 *before* any clean-up of your home folder.

---

## 20. Appendix: the admin area

What you will use after launch. The details of each switch are on its own page in
the admin area; this is the map.

### Sign-in required (off at the start)

**The site starts open.** Guests can browse, read and keep bookmarks without an
account. Bookmarks and reading history are saved in the visitor's own browser, so
they work for guests too; **Library → Export / Import** moves them to another
device by hand. When a reader signs in, their bookmarked series and the chapters
they have read (chapter ids and the time they were opened, nothing else) are also
kept on their account: both follow the reader to a new phone or computer, and the
reader gets an alert in the bell when a bookmarked series has a new chapter.
Reading history is kept for as long as the account exists; it is deleted with the
account and included in the reader's data download.

When your Admins are in place and you want every visitor to log in first (less
scraping and load), switch on **Admin → Site Functions → "Sign-in required for
everyone"** (owner only).

- **Off (default):** anyone can browse and read. Signing in is needed only for
  comments, translation, notifications, settings and the admin area.
- **On:** every visitor lands on the login page and chooses **Google**,
  **Microsoft** or an **e-mail link** (no reader passwords). The server refuses
  catalogue, reader, community and sitemap requests from guests too, not just the
  pages. Search engines can't read the site while it is on.

The sign-in page, sign-up, the admin area and the server commands are never behind
this switch, so it can't lock you out.

### The four roles (Admin → Role Management)

**You (the owner)** hold everything; nobody can change, demote or touch you.
**Admins** (at most two) are your right hand. **Sub-admins** (as many as the seats
allow) are staff. **Users** are readers. Power over a person needs a strictly
higher tier.

- **Admins.** Pick a sub-admin who has an authenticator and press *Make Admin*
  (needs your code). An Admin starts with almost every power except **Admin
  Settings, the cache and "delete all manga"**, which stay off until you switch
  them on (switching a site-owner power on needs your code; switching off never
  does). An Admin can't change another Admin, themselves or you, and sees only
  sub-admins' and users' e-mail addresses.
- **Seats.** The two Admins share **50** sub-admin seats (25 each by default).
  Change an Admin's seats on their card; the total can't pass 50.
- **The ceiling.** *What sub-admins may hold* lists every everyday power; tick one
  and no sub-admin can hold it. Site-owner powers are always out of a sub-admin's
  reach.
- **Roles (presets).** Only you create new roles (named sets of powers).
- **Succession line.** Each Admin names up to two sub-admins, in order. If the Admin
  falls idle, the first eligible one takes the seat exactly as it is, and the old
  Admin becomes a user. **Automatic succession** (only you, off by default, your
  code to change): choose the idle period (30-365 days, default 60). Every change
  goes to your notifications and the audit log. *Hand seat over now* does it at
  once.

### Site Functions (owner only, can't be delegated)

**Admin → Site Functions** lists every main function of the website with an
on/off switch. There is no permission for it, so not even an Admin sees it. Every
switch is enforced on the server and the pages hide what is off.

| Group | Functions |
| --- | --- |
| Sign-in and access | Sign-in required for everyone, maintenance mode, new accounts, sign in with Google / Microsoft / an e-mail link |
| Reading and community | Comments, community (emojis and realms), chapter reports, notifications |
| Translation and OCR | OCR, translation |
| Site content | Ads, support and donation links, sitemap and RSS |
| Scraping | Scraping and importing (manual imports, re-scrapes, the Scraper AI and every scheduled scrape) |
| Privacy and security | Visitor IP addresses are for the owner only; record visitor IP addresses |

At least one sign-in method must stay on. Locked yourself out? On the server:
`docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap functions-reset`
(it also puts *Sign-in required* back to **off**).

### Tab access (owner only)

**Admin → Role Management → Tab access**: for each Admin and sub-admin, choose
which admin tabs they see. The server refuses those tabs' actions too, not only
the menu. A tab list never *gives* a power; it only takes tabs away. **Switch all
powers off** parks an Admin by name only without losing the seat; *Switch powers
back on* restores everything.

### Import a series and its chapters

1. **Admin → Series Management → Import & Scrape Manga**.
2. Enter the **MangaUpdates link** (title, description, genres, cover) and the
   **source series URL** (where chapters and images come from).
3. Choose the **Page Layout** (auto / vertical strips / book format / one page per
   chapter) and click **Test & Live Preview**: it must show a title, a chapter
   count and page images. Nothing is saved yet.
4. Click **Start Auto-Scrape**. The `scrape` and `compress` workers fetch every
   chapter and convert the pages to WebP. Follow it with
   `docker compose logs -f celery_worker_scrape celery_worker_compress` (small
   profile: `celery_worker_scrape`).
5. New chapters are then picked up automatically by beat on the series' schedule.

If the preview finds nothing, the site isn't covered by a built-in parser: use
**Custom Parser** (**Admin → Series Management → Custom Parser**): paste one series page that
shows its chapter list (2+ chapters) and click **Generate Parser**. Sites behind a
Cloudflare/CAPTCHA check, a login or payment, or with scrambled pictures cannot be
added. Only import content you have the rights to host.

### Other features

| Feature | Needs |
| --- | --- |
| Page translation overlay | Vault: *Server OCR enabled*; a translator (the reader's own AI key in *Settings → AI & OCR Engines*, or a site default in Admin → API Management). Readers switch it on once in *Settings → Reading & Translation*. |
| Notifications, storage alerts | The notifications and maintenance workers, and beat |
| Ads, branding, announcements, maintenance mode | Admin → Site settings |
| Geolock (block countries) | Admin → Geolock: press *Download free database (DB-IP)* once, tick countries, save. The owner and Admins; never a sub-admin |
