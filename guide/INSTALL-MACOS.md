# Install on macOS

From an empty Mac to a running site with you signed in as the admin. Works on
Intel and Apple Silicon (M1/M2/M3/M4) Macs with macOS 13 or newer.

Time: about 30 minutes, most of it waiting for the first build.
You need: 8 GB RAM (16 GB is more comfortable), 40 GB free disk, internet, and
a phone with an authenticator app (Google Authenticator, Microsoft
Authenticator, Aegis…).

> **How to read this guide.** Open **Terminal** (Spotlight: ⌘ + Space, type
> *Terminal*, Enter). Grey boxes are commands: copy one box at a time, paste
> it into Terminal (⌘ + V), press **Enter**, and wait until the prompt comes
> back before the next one. Lines starting with `#` are explanations; Terminal
> ignores them.

**Already installed, and the admin sign-in "doesn't work"?** Go to
[Step 6](#step-6--tell-the-site-who-the-owner-is). The old admin password and
`/admin-login` page are gone: you now become the owner by signing in with Google.

---

## Step 1 — Install Git and Docker Desktop

**Git and Python 3** come with Apple's command-line tools:

```bash
xcode-select --install
```

A window asks to install the tools: click **Install** and wait. If it says
they are *already installed*, that's fine too.

**Docker Desktop:**

1. Download it from <https://www.docker.com/products/docker-desktop/>. Pick
   **Apple Silicon** or **Intel** (Apple menu → *About This Mac* → *Chip*
   tells you which).
2. Open the downloaded `.dmg` and drag **Docker** into **Applications**.
3. Start **Docker** from Applications, accept the terms, and wait until the
   whale icon in the menu bar says **Docker Desktop is running**.
4. Docker → **Settings → Resources**: give it at least **4 GB memory**. Click
   *Apply & restart*.

(With Homebrew you can instead run `brew install --cask docker`, then do 3–4.)

Check in Terminal:

```bash
git --version
python3 --version
docker --version
docker compose version
docker run --rm hello-world
```

You should see version numbers and "Hello from Docker!".
*"Cannot connect to the Docker daemon"* means Docker Desktop isn't running
yet: start it and wait for the whale.

---

## Step 2 — Download the website

```bash
cd ~
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

Every command from now on runs **inside this folder**. In a new Terminal
window, first run `cd ~/manga-website-v1.01`.

---

## Step 3 — Create the settings file (`.env`)

One command creates `.env` with new random secret keys and matching
database/Redis passwords:

```bash
python3 backend_fastapi/scripts/make_env.py --local
```

It prints `Created …/.env with new random secrets.` (`--local` means "this
Mac, plain `http://localhost`". For a public server with a domain use the
[Linux guide](INSTALL-LINUX.md) on that server.)

`.env` starts with a dot, so Finder hides it (⌘ + Shift + . shows hidden
files). To look at or edit it:

```bash
open -e .env      # opens it in TextEdit; save with ⌘ + S
```

**Back up `.env` now** (password manager or a USB stick). Two keys in it,
`EMAIL_ENCRYPTION_KEY` and `INTEGRATIONS_SECRET`, unlock data in the
database. Lose them and that data can't be read again.

> It says *".env already exists, so nothing was changed"*? Keep the one you
> have, unless the site has never worked and you want to start clean: see
> [Start again from zero](#start-again-from-zero).

---

## Step 4 — Build and start the site

```bash
docker compose up -d --build
```

The first time this takes 5–15 minutes. Then watch until everything is up:

```bash
docker compose ps
```

Wait until the services say `running` or `healthy` (run it again every minute
or so). `manga-stack-migrate` shows *exited (0)*: correct, it sets up the
database once and stops.

If something says `restarting` or `exited (1)`:

```bash
docker compose logs --tail 50 backend
docker compose logs --tail 50 manga-stack-migrate
```

and see [Troubleshooting](#troubleshooting).

---

## Step 5 — Check the site works

```bash
curl http://localhost:8000/healthz
```

should print `{"ok":true}`. Then open <http://localhost:8080> in Safari or
Chrome. You should see the (empty) home page.

---

## Step 6 — Tell the site who the owner is

There is **no admin password and no special admin page**. You become the site
owner by signing in with Google, once, using the e-mail you choose here. This
step writes one line into `.env`: a hash of that e-mail (the address itself is
stored nowhere). The command runs in a throw-away Docker container, so you
don't need to install anything:

```bash
docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
```

It asks one question, **Admin e-mail:** the Google e-mail you will use as the
site owner. It ends with `Done: the line is now in .env`.

You also need Google sign-in itself, because the owner uses it to get in.
Follow [`GOOGLE_LOGIN_SETUP.md`](../GOOGLE_LOGIN_SETUP.md) (Steps 1 and 2) to
get a client ID and secret and put `GOOGLE_OAUTH_CLIENT_ID` and
`GOOGLE_OAUTH_CLIENT_SECRET` in `.env`. They start in `.env`; you can move them
into **Admin → Secret Vault** later.

Now **recreate** the containers so they read the new `.env`:

```bash
docker compose up -d --force-recreate
```

> ⚠ `docker compose restart` is **not** enough. A restart keeps the old
> settings; only `up -d --force-recreate` reads `.env` again. This is the most
> common reason a correct setup "doesn't work".

After about 30 seconds, check the server sees everything:

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap admin-status
```

You want:

```
MAIN_ADMIN_EMAIL_HASH: set
Google sign-in: set up
Owner: not claimed yet -- sign in with Google using the owner e-mail.
```

---

## Step 7 — Sign in with Google and set up your authenticator

1. Open the site (<http://localhost:8080>) → **Log in** → **Continue with
   Google**, and pick the Google account whose e-mail you used in Step 6.
2. The first time, the site asks you to **complete your profile** (display
   name, username, birth date), like every new account. Fill it in and press
   **Enter Manga World**. You are now the owner (`admin-status` says
   `Owner: claimed`, and nobody else can ever claim the seat).
3. Open **Admin**. It asks you to set up an authenticator app. The page shows a
   **setup key**. In the authenticator app on your phone: **+** → **Enter a
   setup key** (not "scan QR code") → any account name (for example *Manga
   admin*), the key, type *Time based*. On a phone you can tap **Open in
   authenticator app** instead.
4. Type the **6-digit code** the app shows → **Continue**.

Admin pages stay shut until the authenticator is set up, and from then on
every admin page asks for a fresh code. There is nothing one-time to burn: if
you sign out, just sign in with Google again.

---

## Step 8 — Set up normal sign-in

You sign in like readers: **Google**, **Microsoft** or a **magic link** by
e-mail. Set them up in **Admin → Secret Vault** (it asks for your
authenticator code). E-mail needs your mail provider's SMTP settings; Google
and Microsoft: [`GOOGLE_LOGIN_SETUP.md`](../GOOGLE_LOGIN_SETUP.md) and
[`GUIDE.md` §3.5](../GUIDE.md#35-optional-features-leave-blank-to-disable).

**Until e-mail is set up**, get a sign-in link straight from the server:

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap login-link --email you@example.com
```

and open the printed link. (Magic links requested on the site are printed in
`docker compose logs -f celery_worker_email` until SMTP is set.)

---

## Step 9 — Everyday commands

| Want to | Command |
| --- | --- |
| See what is running | `docker compose ps` |
| Stop the site (data is kept) | `docker compose down` |
| Start it again | `docker compose up -d` (Docker Desktop must be running) |
| Apply a change you made in `.env` | `docker compose up -d --force-recreate` |
| Watch the API log | `docker compose logs -f backend` (Ctrl + C to stop) |
| Update to a new version | [`GUIDE.md` §12](../GUIDE.md#12-updating-safely-and-rolling-back) (backup first) |

---

## Lost your phone, or locked out

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email you@example.com
```

then sign in with Google and open **Admin**: it asks you to set up the new phone
(Step 7). Only signed out? Sign in with Google again, or use `login-link` from
Step 8 if Google is not set up.

---

## Troubleshooting

| What you see | What to do |
| --- | --- |
| Signed in with Google but I'm not the owner | Run `admin-status` (Step 6). *"MAIN_ADMIN_EMAIL_HASH: not set"* → you used `restart`: run `docker compose up -d --force-recreate`. *"DAMAGED"* → redo Step 6. *"Owner: claimed"* → the seat is already taken; ownership never passes. Otherwise test `.env` with `make_admin_hash.py --check .env` (below) and use exactly that Google address. |
| Google doesn't make me the owner, and I want to test `.env` | Run `docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --check .env"`. It tells you whether the e-mail matches or the line is damaged. If not, redo Step 6. |
| Authenticator code refused | Phone clock is off: turn on automatic date & time, then use a fresh code. |
| Closed the browser at the setup-key step | No harm. Open **Admin** again: it shows a new setup key. Delete the half-made entry in the app. |
| Admin pages say **"Set up your authenticator app"** | Expected on the owner's first visit: open **Admin**, add the setup key to your authenticator app and type the code (Step 7). |
| `Cannot connect to the Docker daemon` | Start Docker Desktop and wait for "running". |
| `Set EMAIL_ENCRYPTION_KEY to a Fernet key` | No `.env` or wrong folder: `cd ~/manga-website-v1.01`, then Step 3. |
| `password authentication failed` (database) | `.env` passwords differ from the ones the database was created with. Nothing to keep yet? [Start again from zero](#start-again-from-zero). |
| `port is already allocated` | Another app uses 8080 or 8000 (often AirPlay Receiver on 5000/7000, or another dev server). Quit it, or change the left number of `ports:` in `docker-compose.yml`. |
| Build is very slow or runs out of memory | Docker → Settings → Resources: more memory (6–8 GB). |
| Anything else | `docker compose logs --tail 100 backend` and [`GUIDE.md` §10](../GUIDE.md#10-troubleshooting). |

---

## Start again from zero

Only when nothing on the site is worth keeping. This deletes the database,
images and settings file:

```bash
cd ~/manga-website-v1.01
docker compose down -v
rm .env
```

Then continue from [Step 3](#step-3--create-the-settings-file-env).
