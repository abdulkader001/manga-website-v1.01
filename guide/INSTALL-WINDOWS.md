# Install on Windows 10 / 11

From an empty Windows PC to a running site with you signed in as the admin.
Every command is typed in **PowerShell**; you don't need Linux, WSL commands
or Python yourself (Docker runs those parts).

Time: about 40 minutes, most of it installing Docker and the first build.
You need: Windows 10 (22H2) or 11, 8 GB RAM (16 GB is more comfortable),
40 GB free disk, internet, and a phone with an authenticator app (Google
Authenticator, Microsoft Authenticator, Aegis…).

> **How to read this guide.** Grey boxes are commands. Open PowerShell (Start
> menu → type *PowerShell* → **Windows PowerShell**). Copy one box at a time,
> paste it with a **right-click** (or Ctrl + V), press **Enter**, and wait
> until the prompt `PS C:\…>` comes back before the next one. Lines starting
> with `#` are explanations; PowerShell ignores them.

**Already installed, and the admin sign-in "doesn't work"?** Go to
[Step 6](#step-6--tell-the-site-who-the-owner-is). The old admin password and
`/admin-login` page are gone: you now become the owner by signing in with Google.

---

## Step 1 — Install Git and Docker Desktop

In PowerShell:

```powershell
winget install -e --id Git.Git
```

```powershell
winget install -e --id Docker.DockerDesktop
```

Accept the prompts. (No `winget`? Download them by hand:
<https://git-scm.com/download/win> and
<https://www.docker.com/products/docker-desktop/>. Use the default options.)

**Restart the PC.**

After the restart:

1. Start **Docker Desktop** from the Start menu. Accept the terms. If it asks
   to install or update **WSL**, say yes and let it finish (it may ask for one
   more restart).
2. Wait until the bottom-left of the Docker window says **Engine running**.
3. Docker Desktop → ⚙ **Settings → Resources**: at least **4 GB memory** if
   that option is shown. *Apply & restart*.

Close PowerShell and open a **new** PowerShell window (so it finds `git`), then
check:

```powershell
git --version
docker --version
docker compose version
docker run --rm hello-world
```

You should see version numbers and "Hello from Docker!".

> *"error during connect"* or *"cannot find the file specified"* → Docker
> Desktop isn't running yet. Start it and wait for **Engine running**.
> *"Virtualization must be enabled"* → turn on *Intel VT-x / AMD-V (SVM)* in
> the PC's BIOS/UEFI settings, then start Docker again.

---

## Step 2 — Download the website

```powershell
# Keep Linux line endings: the site's scripts run inside Linux containers
git config --global core.autocrlf false
```

```powershell
cd $HOME
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

Every command from now on runs **inside this folder**
(`C:\Users\<you>\manga-website-v1.01`). In a new PowerShell window, first run
`cd $HOME\manga-website-v1.01`.

---

## Step 3 — Create the settings file (`.env`)

One command creates `.env` with new random secret keys and matching
database/Redis passwords. It runs in a throw-away Docker container:

```powershell
docker run --rm -v "${PWD}:/w" -w /w python:3.11-slim python backend_fastapi/scripts/make_env.py --local
```

It prints `Created /w/.env with new random secrets.` (`/w` is your project
folder as the container sees it.) `--local` means "this PC, plain
`http://localhost`". For a public server with a domain, use a Linux server and
the [Linux guide](INSTALL-LINUX.md).

To look at or edit `.env`:

```powershell
notepad .env
```

**Back up `.env` now** (password manager or a USB stick). Two keys in it,
`EMAIL_ENCRYPTION_KEY` and `INTEGRATIONS_SECRET`, unlock data in the
database. Lose them and that data can't be read again.

> It says *".env already exists, so nothing was changed"*? Keep the one you
> have, unless the site has never worked and you want to start clean: see
> [Start again from zero](#start-again-from-zero).

---

## Step 4 — Build and start the site

```powershell
docker compose up -d --build
```

The first time this takes 5–20 minutes. Then watch until everything is up:

```powershell
docker compose ps
```

Wait until the services say `running` or `healthy` (run it again every minute
or so). `manga-stack-migrate` shows *exited (0)*: correct, it sets up the
database once and stops. You can also watch the containers in the Docker
Desktop window.

If something says `restarting` or `exited (1)`:

```powershell
docker compose logs --tail 50 backend
docker compose logs --tail 50 manga-stack-migrate
```

and see [Troubleshooting](#troubleshooting).

---

## Step 5 — Check the site works

```powershell
curl.exe http://localhost:8000/healthz
```

should print `{"ok":true}` (type `curl.exe`, not `curl`). Then open
<http://localhost:8080> in Edge or Chrome. You should see the (empty) home
page.

---

## Step 6 — Tell the site who the owner is

There is **no admin password and no special admin page**. You become the site
owner by signing in with Google, once, using the e-mail you choose here. This
step writes one line into `.env`: a hash of that e-mail (the address itself is
stored nowhere). The command runs in a throw-away Docker container, so you
don't need to install anything:

```powershell
docker run --rm -it -v "${PWD}:/w" -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
```

It asks one question, **Admin e-mail:** the Google e-mail you will use as the
site owner. It ends with `Done: the line is now in .env`.

You also need Google sign-in itself, because the owner uses it to get in.
Follow [`GOOGLE_LOGIN_SETUP.md`](../GOOGLE_LOGIN_SETUP.md) (Steps 1 and 2) to
get a client ID and secret and put `GOOGLE_OAUTH_CLIENT_ID` and
`GOOGLE_OAUTH_CLIENT_SECRET` in `.env`. They start in `.env`; you can move them
into **Admin → Secret Vault** later.

Now **recreate** the containers so they read the new `.env`:

```powershell
docker compose up -d --force-recreate
```

> ⚠ `docker compose restart` is **not** enough. A restart keeps the old
> settings; only `up -d --force-recreate` reads `.env` again. This is the most
> common reason a correct setup "doesn't work".

After about 30 seconds, check the server sees everything:

```powershell
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

```powershell
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

To have the site come back after a reboot: Docker Desktop → Settings →
General → **Start Docker Desktop when you sign in**.

---

## Lost your phone, or locked out

```powershell
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
| Google doesn't make me the owner, and I want to test `.env` | Run `docker run --rm -it -v "${PWD}:/w" -w /w python:3.11-slim sh -c "pip install -q --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --check .env"`. It tells you whether the e-mail matches or the line is damaged. If not, redo Step 6. |
| Authenticator code refused | Phone clock is off: turn on automatic date & time, then use a fresh code. |
| Closed the browser at the setup-key step | No harm. Open **Admin** again: it shows a new setup key. Delete the half-made entry in the app. |
| Admin pages say **"Set up your authenticator app"** | Expected on the owner's first visit: open **Admin**, add the setup key to your authenticator app and type the code (Step 7). |
| `exec … no such file or directory` or `\r: not found` in a container log | The files were downloaded with Windows line endings. Delete the folder, run the `git config` line from Step 2, and clone again. |
| `error during connect` / `cannot find the file specified` | Docker Desktop isn't running. Start it, wait for **Engine running**. |
| `invalid reference format` or `/w` errors in `docker run` | Run it from PowerShell (not *cmd*), inside the project folder, and copy the line exactly, including the double quotes around `${PWD}:/w`. |
| `Set EMAIL_ENCRYPTION_KEY to a Fernet key` | No `.env`, or wrong folder: `cd $HOME\manga-website-v1.01`, then Step 3. |
| `password authentication failed` (database) | `.env` passwords differ from the ones the database was created with. Nothing to keep yet? [Start again from zero](#start-again-from-zero). |
| `port is already allocated` | Another program uses 8080 or 8000. Close it, or change the left number of `ports:` in `docker-compose.yml`. |
| Build is very slow | Normal on the first build. Keep the PC plugged in; give Docker more memory if Settings → Resources allows. |
| Anything else | `docker compose logs --tail 100 backend` and [`GUIDE.md` §10](../GUIDE.md#10-troubleshooting). |

---

## Start again from zero

Only when nothing on the site is worth keeping. This deletes the database,
images and settings file:

```powershell
cd $HOME\manga-website-v1.01
docker compose down -v
Remove-Item .env
```

Then continue from [Step 3](#step-3--create-the-settings-file-env).
