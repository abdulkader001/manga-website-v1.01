# Install on Linux (Ubuntu / Debian)

From an empty Linux machine to a running site with you signed in as the
admin. Works on a home PC, a laptop or a cloud server (Google Cloud, AWS,
Hetzner, DigitalOcean…) or a virtual machine (VMware, VirtualBox) running
**Ubuntu 22.04/24.04/26.04 or Debian 12**. Checked end to end on Ubuntu 26.04 in
a VMware VM.

Time: about 30 minutes, most of it waiting for the first build.
You need: 2 CPU cores, 4 GB RAM, 40 GB free disk, internet, and a phone with an
authenticator app (Google Authenticator, Microsoft Authenticator, Aegis…).

> **How to read this guide.** Grey boxes are commands. Copy one box at a time
> into the terminal, press **Enter**, and wait until it finishes (the prompt
> `$` comes back) before the next one. Lines starting with `#` are
> explanations; the terminal ignores them, so copying them is harmless.

**Already installed, and the admin sign-in "doesn't work"?** Go to
[Step 6](#step-6--tell-the-site-who-the-owner-is). The old admin password and
`/admin-login` page are gone: you now become the owner by signing in with Google.

---

## Step 1 — Install Git and Docker

Open a terminal (on a server: your SSH window) and run:

```bash
sudo apt-get update
sudo apt-get install -y git curl ca-certificates python3
```

```bash
# Docker Engine + the "docker compose" plugin (Docker's official installer)
curl -fsSL https://get.docker.com | sudo sh
```

```bash
# Let your user run Docker without "sudo"
sudo usermod -aG docker $USER
```

**Now restart the computer** (`sudo reboot`; on a server: close the SSH
window and connect again). This makes the last command take effect. Logging
out and in also works, but a reboot is the surest way, especially in a VM.

Check that everything works:

```bash
groups
docker --version
docker compose version
docker run --rm hello-world
```

You should see `docker` in the first line, two version numbers and a
"Hello from Docker!" message.

*"permission denied … docker.sock"* means `docker` is not in the `groups` line
yet: Docker **is** installed, you just haven't rebooted since `usermod`.
Reboot and check again.

> ⚠ **Don't install anything else for Docker.** Never run
> `apt-get install docker.io docker-compose-v2` after the installer above: it is
> a second copy of Docker that removes the first one and stops half-way with
> `trying to overwrite '/usr/libexec/docker/cli-plugins/docker-compose'`.
> Already did? Fix it with *Repair a mixed install* in
> [`GUIDE.md` §1](../GUIDE.md#1-install-the-prerequisites-ubuntu), then reboot.

---

## Step 2 — Download the website

```bash
cd ~
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

Every command from now on runs **inside this folder**. If you open a new
terminal later, first run `cd ~/manga-website-v1.01`.

---

## Step 3 — Create the settings file (`.env`)

One command creates `.env` with new random secret keys and matching
database/Redis passwords. You don't have to invent or paste any of them.

**Trying it on this computer** (you will open `http://localhost:8080`):

```bash
python3 backend_fastapi/scripts/make_env.py --local
```

**A real server with a domain name and HTTPS:** run it without `--local`,
then put your domain into the address lines as described in
[`GUIDE.md` §3.3](../GUIDE.md#33-variables-for-your-domain-production):

```bash
python3 backend_fastapi/scripts/make_env.py
nano .env        # edit the address lines; Ctrl+O, Enter to save, Ctrl+X to quit
```

It prints `Created …/.env with new random secrets.`

**Back up `.env` now** (copy it to a USB stick or password manager). Two keys
in it, `EMAIL_ENCRYPTION_KEY` and `INTEGRATIONS_SECRET`, unlock data in the
database. Lose them and that data can't be read again.

> It says *".env already exists, so nothing was changed"*? You (or an earlier
> attempt) already made one. Keep it, unless the site has never worked and you
> want to start clean: see [Start again from zero](#start-again-from-zero).

---

## Step 4 — Build and start the site

```bash
docker compose up -d --build
```

The first time this takes 5–15 minutes. It builds the website and the API,
then starts the database, Redis, the database setup ("migrations"), the API,
the background workers and the web server.

Watch until everything is up:

```bash
docker compose ps
```

You should see 13 lines: `manga-stack-backend`, `-db`, `-redis`, `-web`,
`-celery-beat`, `-celery-worker` and seven `manga-stack-celery_worker_…-1`.
Right after the start they
say `(health: starting)`: that is normal. Run `docker compose ps` again every
minute or so until every line says `(healthy)`.

`manga-stack-migrate` (the database setup) is not in that list because it ran
once and stopped. `docker compose ps -a` shows it as `Exited (0)`, which is
correct.

> Paste **one command per line**. `docker compose ps docker compose ps -a` on one
> line fails with *"no such service: docker"*.

If something says `restarting` or `exited (1)`, look at its log:

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

should print `{"ok":true}`. Then open the site in a browser:

- **On this computer:** <http://localhost:8080>
- **In a VM (VMware, VirtualBox), from your main computer:** run `hostname -I`
  inside the VM and open `http://THAT-ADDRESS:8080` on your main computer.
  Fine for testing at home; never do this on a public server.
- **On a server without a domain yet:** don't open port 8080 to the internet.
  From your own PC, open a private tunnel and browse to it as if it were
  local:

  ```bash
  # run this on YOUR PC, not on the server
  ssh -L 8080:localhost:8080 your-user@your-server-ip
  ```

  Keep that window open and visit <http://localhost:8080>.

You should see the home page (empty, no series yet).

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

**Guests can read straight away.** The site starts with *Sign-in required* **off**:
anyone can browse, read and bookmark. Signed-in readers also get an alert when a
bookmarked series has a new chapter.
When your Admins are ready and you want everyone to log in first, switch it on in
**Admin → Site Functions** (details: [`GUIDE.md` §6.2](../GUIDE.md#62-sign-in-required-off-at-the-start-you-switch-it-on-when-ready)).

---

## Step 8 — Set up normal sign-in

You sign in the same way as readers: **Google**, **Microsoft** or a **magic
link** by e-mail. Set them up in **Admin → Secret
Vault** (the vault asks for your authenticator code):

- **E-mail (magic links):** the SMTP settings of your mail provider
  (`EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS`).
- **Google / Microsoft:** see [`GOOGLE_LOGIN_SETUP.md`](../GOOGLE_LOGIN_SETUP.md)
  and [`GUIDE.md` §3.5](../GUIDE.md#35-optional-features-leave-blank-to-disable).

**Until e-mail is set up**, a magic link is not sent but printed in the log.
Either read it there:

```bash
docker compose logs -f celery_worker_email     # Ctrl+C to stop watching
```

or make a sign-in link directly on the server:

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap login-link --email you@example.com
```

Open the printed link in your browser. Admin pages then ask for the code from
your authenticator app.

---

## Step 9 — Everyday commands

| Want to | Command |
| --- | --- |
| See what is running | `docker compose ps` |
| Stop the site (data is kept) | `docker compose down` |
| Start it again | `docker compose up -d` |
| Apply a change you made in `.env` | `docker compose up -d --force-recreate` |
| Watch the API log | `docker compose logs -f backend` (Ctrl+C to stop) |
| Update a test copy to the newest code | `git pull --ff-only`, then `docker compose up -d --build` |
| Update a live site | see [`GUIDE.md` §12](../GUIDE.md#12-updating-safely-and-rolling-back) (backup first) |

The site starts by itself after a reboot (Docker restarts the containers).

---

## Lost your phone, or locked out

Lost the authenticator (new phone, reset phone):

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email you@example.com
```

then sign in with Google and open **Admin**: it asks you to set up the new phone
(Step 7). Only signed out? Sign in with Google again, or use `login-link` from
Step 8 if Google is not set up.

Just signed out and e-mail/Google sign-in isn't set up yet? Use `login-link`
from Step 8.

---

## Troubleshooting

| What you see | What it means and what to do |
| --- | --- |
| Signed in with Google but I'm not the owner | Run `admin-status` (Step 6). *"MAIN_ADMIN_EMAIL_HASH: not set"* → you used `restart`: run `docker compose up -d --force-recreate`. *"DAMAGED"* → redo Step 6. *"Owner: claimed"* → the seat is already taken; ownership never passes. Otherwise test `.env` with `make_admin_hash.py --check .env` (below) and use exactly that Google address. |
| Google doesn't make me the owner, and I want to test `.env` | Run `docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --check .env"`. It tells you whether the e-mail matches or the line is damaged. If not, redo Step 6. |
| Authenticator code refused | The phone's clock is off. Turn on *automatic date & time* on the phone, then type a fresh code (each lasts 30 seconds). |
| Closed the browser at the setup-key step | No harm. Open **Admin** again: it shows a new setup key. Delete the half-made entry in the app. |
| Admin pages say **"Set up your authenticator app"** | Expected on the owner's first visit: open **Admin**, add the setup key to your authenticator app and type the code (Step 7). |
| `permission denied … /var/run/docker.sock` | Docker is installed; your terminal isn't in the `docker` group yet (`groups` doesn't list it). Reboot after `usermod` (Step 1). Don't reinstall Docker. |
| `trying to overwrite '/usr/libexec/docker/cli-plugins/docker-compose'` or `N not fully installed or removed` | A second copy of Docker (`docker.io`, `docker-compose-v2`) was installed on top of the first. Run *Repair a mixed install* in [`GUIDE.md` §1](../GUIDE.md#1-install-the-prerequisites-ubuntu). |
| `failed to solve: image "docker.io/library/manga-backend:latest": already exists` | Old copy of the code (it built the same image once per worker at the same time). `git pull --ff-only`, then Step 4 again. Or, without updating: `docker compose build backend web` and then `docker compose up -d`. |
| `(health: starting)` in `docker compose ps` | Normal for the first minute. Wait, then run `docker compose ps` again. |
| `no such service: docker` | Two commands were pasted on one line. Paste one per line. |
| `git pull` asks for a GitHub username | Press **Ctrl+C** (Enter would skip the pull and run the next commands on the old code). See the matching row in [`GUIDE.md` §10](../GUIDE.md#10-troubleshooting). |
| `Set EMAIL_ENCRYPTION_KEY to a Fernet key` | There is no `.env`, or you're in the wrong folder. `cd ~/manga-website-v1.01`, then Step 3. |
| `password authentication failed` (database) | The database was created with other passwords than the ones now in `.env` (e.g. `.env` was remade). If the site has no content yet: [Start again from zero](#start-again-from-zero). |
| Site loads but sign-in keeps looping | On `http://localhost`, `FORCE_HTTPS_REDIRECTS` must be `false` (`make_env.py --local` does this). Fix the line, then `docker compose up -d --force-recreate`. |
| `port is already allocated` | Another program uses port 8080 or 8000. Stop it, or change the left number of `ports:` in `docker-compose.yml`. |
| Anything else | `docker compose logs --tail 100 backend` and the table in [`GUIDE.md` §10](../GUIDE.md#10-troubleshooting). |

---

## Start again from zero

Only when the site has **no content you want to keep**. This deletes the
database, all uploaded images and your settings file:

```bash
cd ~/manga-website-v1.01
docker compose down -v
rm .env
```

Then continue from [Step 3](#step-3--create-the-settings-file-env).

---

## Going live on a domain

For a public site: point your domain at the server, put HTTPS in front
(Caddy or nginx + Let's Encrypt), and only open ports 80/443. Full steps:
[`GUIDE.md` §8](../GUIDE.md#8-go-live-on-a-linux-server-with-a-domain-and-https).
Do the owner's first Google sign-in (Step 7) over HTTPS or through the SSH tunnel
from Step 5, never over plain `http://` on a public address.
