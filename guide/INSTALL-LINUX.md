# Install on Linux (Ubuntu / Debian)

From an empty Linux machine to a running site with you signed in as the
admin. Works on a home PC, a laptop or a cloud server (Google Cloud, AWS,
Hetzner, DigitalOcean…) running **Ubuntu 22.04/24.04 or Debian 12**.

Time: about 30 minutes, most of it waiting for the first build.
You need: 2 CPU cores, 4 GB RAM, 40 GB free disk, internet, and a phone with an
authenticator app (Google Authenticator, Microsoft Authenticator, Aegis…).

> **How to read this guide.** Grey boxes are commands. Copy one box at a time
> into the terminal, press **Enter**, and wait until it finishes (the prompt
> `$` comes back) before the next one. Lines starting with `#` are
> explanations; the terminal ignores them, so copying them is harmless.

**Already installed, and the admin password "doesn't work"?** Go to
[Step 6](#step-6--make-your-one-time-admin-password). It replaces the old
admin lines and explains why they failed.

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

**Now log out and log back in** (on a server: close the SSH window and connect
again). This makes the last command take effect.

Check that everything works:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

You should see version numbers and a "Hello from Docker!" message.
*"permission denied … docker.sock"* means you did not log out and back in yet.

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

Wait until the services say `running` or `healthy`. `manga-stack-migrate`
appears as *exited (0)*: that is correct, it runs once and stops. Run
`docker compose ps` again every minute or so until nothing says `starting`.

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

## Step 6 — Make your one-time admin password

This puts two lines into `.env`: a hash of your e-mail and a hash of a
one-time password. The command runs in a throw-away Docker container, so you
don't need to install anything:

```bash
docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
```

It asks three questions:

1. **Admin e-mail:** the e-mail you will use as the site owner.
2. **One-time admin password:** at least 12 characters. **Nothing appears on
   screen while you type; that is normal.** Press Enter. Or just press Enter
   without typing anything and it makes a strong password for you and shows it
   once. Write it down.
3. **Type it again:** the same password.

It ends with `Done: both lines are now in .env (old ones replaced).`

Now **recreate** the containers so they read the new `.env`:

```bash
docker compose up -d --force-recreate
```

> ⚠ `docker compose restart` is **not** enough. A restart keeps the old
> settings; only `up -d --force-recreate` reads `.env` again. This is the most
> common reason a correct password "doesn't work".

Check the server sees the lines (wait about 30 seconds after the previous
command):

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap admin-status
```

You want:

```
MAIN_ADMIN_EMAIL_HASH: set
MAIN_ADMIN_PASSWORD_HASH: set
/admin-login: OPEN -- the one-time password has not been used yet.
```

**Why the old lines failed (if you made some before):** an older version
printed hashes full of `$` signs. Docker Compose treats `$something` in `.env`
as "insert a variable here" and silently deleted those parts unless the line
was wrapped in single quotes exactly right. The new lines start with `a2:`
and contain no `$`, so nothing can damage them, quoted or not. And the old
page greyed out the **Continue** button whenever the server couldn't see the
lines; the new page doesn't do that.

---

## Step 7 — Sign in as the admin (once)

1. Open <http://localhost:8080/admin-login> (the same address as your site,
   plus `/admin-login`).
2. Type your **e-mail** and the **one-time password** → **Continue**.
3. The page shows a **setup key** (a long code of letters and numbers).
   - On your phone, open the authenticator app → **+** → **Enter a setup
     key** (not "scan QR code").
   - Account name: anything (for example *Manga admin*). Key: the setup key.
     Type: *Time based*.
   - On a phone you can tap **Open in authenticator app** instead.
4. Type the **6-digit code** the app shows → **Sign in**.

The first time, the site asks you to **complete your profile** (display
name, username, birth date), like every new account. Fill it in and press
**Enter Manga World**. Then you land on the admin panel (`/admin`). You are now the main admin.

**The sign-in page is now gone.** Check it:

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap admin-status
```

says `/admin-login: CLOSED -- the one-time password was used`, and opening
`/admin-login` in the browser shows *Page Not Found*.

Optional tidy-up: the used password line is dead, so you may delete it:

```bash
sed -i '/^MAIN_ADMIN_PASSWORD_HASH=/d' .env
docker compose up -d --force-recreate
```

Keep the `MAIN_ADMIN_EMAIL_HASH` line; it says who the owner is.

---

## Step 8 — Set up normal sign-in

After the one-time sign-in you sign in the same way as readers: a **magic
link** by e-mail, **Google** or **Microsoft**. Set them up in **Admin → Secret
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
| Update to a new version | see [`GUIDE.md` §12](../GUIDE.md#12-updating-safely-and-rolling-back) (backup first) |

The site starts by itself after a reboot (Docker restarts the containers).

---

## Lost your phone, or locked out

Lost the authenticator (new phone, reset phone):

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email you@example.com
```

then do **Step 6** again (a new one-time password) and **Step 7** (the page
is open again for that new password and sets up the new phone). The new
password also works only once.

Just signed out and e-mail/Google sign-in isn't set up yet? Use `login-link`
from Step 8. You don't need a new password for that.

---

## Troubleshooting

| What you see | What it means and what to do |
| --- | --- |
| `/admin-login` shows **Page Not Found** before you ever signed in | The server can't see the admin lines. Run `admin-status` (Step 6). *"not set"* → you used `restart`: run `docker compose up -d --force-recreate`. *"DAMAGED"* → old line with `$` signs: redo Step 6. |
| `/admin-login` shows **Page Not Found** after you signed in | Correct. The page is gone after one use. Sign in with a magic link / Google / `login-link`. |
| **"Email, password or code is not right."** | Test what is in `.env`: `docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --check .env"`. It tells you whether the e-mail and the password match. If not, redo Step 6. Check Caps Lock and the keyboard language. |
| **"Too many requests"** | Ten wrong tries from one address lock the page for 15 minutes. Wait, then try again. |
| Authenticator code refused | The phone's clock is off. Turn on *automatic date & time* on the phone, then type a fresh code (each lasts 30 seconds). |
| Closed the browser at the setup-key step | No harm: the password is used up only when the code is accepted. Start Step 7 again; it shows a new setup key. Delete the half-made entry in the app. |
| Admin pages say **"Set up your authenticator app"** | Your account has no authenticator. Do Step 6 + Step 7 (the one-time sign-in sets it up). |
| `permission denied … /var/run/docker.sock` | Log out and in again after `usermod` (Step 1), or prefix commands with `sudo`. |
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
Do the one-time admin sign-in (Step 7) over HTTPS or through the SSH tunnel
from Step 5, never over plain `http://` on a public address.
