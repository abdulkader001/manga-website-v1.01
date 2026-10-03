# Test the site on your own computer

This guide runs the whole website on **your own computer**, with no domain and
nothing public: only you can see it, and you can delete it at any time. Use it to
see the site working, to test every feature, and to check a change before it goes
to the real server. When you are happy, [`GUIDE.md`](GUIDE.md) puts the same site
on a Linux server with your domain.

It runs at **`http://localhost:8080`**. Time: about 30-40 minutes, most of it
waiting for the first build.

Contents

1. [Pick your way](#1-pick-your-way)
2. [Get the computer ready](#2-get-the-computer-ready)
3. [Install Docker and download the site](#3-install-docker-and-download-the-site)
4. [Create the settings file and start the site](#4-create-the-settings-file-and-start-the-site)
5. [Check that it works](#5-check-that-it-works)
6. [Become the owner](#6-become-the-owner)
7. [Test every part of the website](#7-test-every-part-of-the-website)
8. [What to send when something looks wrong](#8-what-to-send-when-something-looks-wrong)
9. [Everyday commands](#9-everyday-commands)
10. [Troubleshooting](#10-troubleshooting)
11. [Start again from zero](#11-start-again-from-zero)
12. [When you are happy: go live](#12-when-you-are-happy-go-live)

---

## 1. Pick your way

| Your situation | Use | Notes |
| --- | --- | --- |
| **Windows PC, and you want the same Linux as the real server** | **A. Ubuntu in a VMware virtual machine** | **The way this was checked**: Ubuntu 26.04 in a VMware VM, Docker 29.8, Compose v5.6. The commands are exactly the ones you will use on the server, so you rehearse the real thing. **Recommended.** |
| Windows 10/11, the quickest way | B. Windows with Docker Desktop | Same site, commands typed in PowerShell. Not the same as the server. |
| Mac (Intel or Apple Silicon) | C. macOS with Docker Desktop | Terminal commands. |
| A Linux PC or laptop | D. Linux directly | Same commands as A, without the virtual machine. |

The main text below is written for **A and D** (Linux commands). Where B and C
differ, a table or a box shows the exact commands.

You need: **8 GB RAM or more in the computer** (the virtual machine gets 4 GB of
it), **40 GB of free disk**, internet, a Google account, and a phone with an
authenticator app (Google Authenticator, Microsoft Authenticator, Aegis,
1Password...).

> **How to read this guide.** Grey boxes are commands. Copy **one box at a time**
> into the terminal, press **Enter**, and wait until the prompt comes back before
> the next one. Lines starting with `#` are explanations; the terminal ignores
> them. Never paste a value that is clearly an example (`you@example.com`): put
> your own on the first line of the box.

---

## 2. Get the computer ready

### A. Ubuntu in VMware (Windows PC)

1. **Install VMware Workstation Player / Pro or VMware Fusion** (free for personal
   use from VMware's website), and download the **Ubuntu Desktop ISO** (22.04,
   24.04 or 26.04) from <https://ubuntu.com/download/desktop>.
2. **Create the virtual machine:** *Create a New Virtual Machine* → *Installer disc
   image file (iso)* → pick the Ubuntu ISO. Give it:
   - **Memory: 4 GB** (4096 MB) or more; **Processors: 2** or more;
   - **Disk: 40 GB**, one file or split (either is fine);
   - **Network: NAT** (the default).
3. **Install Ubuntu** in the window: *Install Ubuntu* → normal installation →
   *Erase disk and install Ubuntu* (it only erases the virtual disk) → make a user
   and a password. Restart when it asks.
4. **Optional but very handy: copy and paste between Windows and the VM.** In the
   VM, open a terminal (`Ctrl+Alt+T`) and run:

   ```bash
   sudo apt-get update
   sudo apt-get install -y open-vm-tools-desktop
   sudo reboot
   ```

   After the reboot you can copy a command in Windows and paste it into the VM's
   terminal with `Ctrl+Shift+V`.
5. **Take a snapshot** now (*VM → Snapshot → Take Snapshot*, name it "clean
   Ubuntu"). If you ever want to start over completely, you can go back to it in
   one click.

**Use the VM's own browser** (Firefox on the Ubuntu desktop) for everything below.
Then `localhost` means the VM itself, which is exactly what the site and Google
sign-in expect. (Browsing from Windows to the VM's address works for looking at
the site, but Google sign-in does not accept an IP address.)

> **The Windows key in the VM.** Windows often swallows the Windows key. Use the
> Ubuntu menu with the mouse (bottom-left *Show Applications*), and `Ctrl+Alt+T`
> for a terminal. **On the site itself**, right-click on a series card opens it in
> a new tab and Shift + right-click opens it in a new window (the normal browser
> right-click menu is blocked on the site: Shift or the Windows key instead of
> plain right-click is the reliable way to get a new window).

### B. Windows with Docker Desktop

Open **PowerShell** (Start menu → type *PowerShell*). Then:

```powershell
winget install -e --id Git.Git
winget install -e --id Docker.DockerDesktop
```

Restart the PC. Start **Docker Desktop**, accept the terms (let it install or
update WSL if it asks), and wait until it says **Engine running**. In Docker
Desktop → Settings → Resources give it at least **4 GB memory**. Close PowerShell
and open a **new** one. (No `winget`? Download Git from <https://git-scm.com/download/win>
and Docker Desktop from <https://www.docker.com/products/docker-desktop/>.)
*"Virtualization must be enabled"* means: turn on Intel VT-x / AMD-V (SVM) in the
PC's BIOS/UEFI.

### C. macOS

Open **Terminal** (⌘ + Space, type *Terminal*). Then:

```bash
xcode-select --install
```

(Click **Install**; "already installed" is fine.) Install **Docker Desktop** from
<https://www.docker.com/products/docker-desktop/> (pick Apple Silicon or Intel),
drag it into Applications, start it, wait until the whale says it is running, and
give it at least **4 GB** in Settings → Resources.

### D. Linux

Nothing to prepare. Ubuntu 22.04/24.04/26.04 or Debian 12, 2 CPU cores, 4 GB RAM,
40 GB free disk.

---

## 3. Install Docker and download the site

### A and D (Ubuntu / Debian)

Open a terminal and run:

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
sudo usermod -aG docker "$USER"
```

**Now restart the computer or the virtual machine** (`sudo reboot`). This makes the
last command take effect; in a VM a reboot is the surest way. Then check:

```bash
groups
docker --version
docker compose version
docker run --rm hello-world
```

You should see `docker` in the first line, two version numbers and "Hello from
Docker!". *"permission denied ... docker.sock"* means `docker` is not in the
`groups` line yet: Docker **is** installed, you just haven't rebooted since
`usermod`. Reboot and check again. **Don't reinstall Docker.**

> ⚠ **Don't install anything else for Docker.** Never run `apt-get install
> docker.io docker-compose-v2` after the installer above: it is a second copy of
> Docker that removes the first one and stops half-way with `trying to overwrite
> '/usr/libexec/docker/cli-plugins/docker-compose'`. Already did? Run *Repair a
> mixed install* in [`GUIDE.md` Section 2.3](GUIDE.md#23-docker), then reboot.

Download the site:

```bash
cd ~
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

Every command from now on runs **inside this folder**. In a new terminal, first
run `cd ~/manga-website-v1.01`.

### B. Windows (PowerShell)

Check the tools, then download the site (the first line keeps Linux line endings,
because the site's scripts run in Linux containers):

```powershell
git --version
docker --version
docker compose version
docker run --rm hello-world
```

```powershell
git config --global core.autocrlf false
```

```powershell
cd $HOME
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

Every command from now on runs inside `C:\Users\<you>\manga-website-v1.01`. In a
new PowerShell window, first run `cd $HOME\manga-website-v1.01`.

### C. macOS (Terminal)

```bash
git --version
python3 --version
docker --version
docker compose version
docker run --rm hello-world
```

```bash
cd ~
git clone https://github.com/abdulkader001/manga-website-v1.01.git
cd manga-website-v1.01
```

---

## 4. Create the settings file and start the site

### 4.1 Create `.env`

One command creates `.env` with new random secret keys and database/Redis
passwords that match inside the URLs. **`--local` means "this computer, plain
`http://localhost`"** (never use `--local` on a real server).

**A, C and D:**

```bash
python3 backend_fastapi/scripts/make_env.py --local
chmod 600 .env
```

**B (Windows PowerShell)** runs it in a throw-away Docker container, so you don't
need Python:

```powershell
docker run --rm -v "${PWD}:/w" -w /w python:3.11-slim python backend_fastapi/scripts/make_env.py --local
```

It prints `Created .../.env with new random secrets.` (On Windows, `notepad .env`
opens it; on macOS `open -e .env`.)

**Back up `.env` now** (password manager or a USB stick). Two keys in it,
`EMAIL_ENCRYPTION_KEY` and `INTEGRATIONS_SECRET`, unlock data in the database. Lose
them and that data can't be read again.

> It says *".env already exists, so nothing was changed"*? You (or an earlier try)
> already made one. Keep it, unless the site has never worked and you want to start
> clean: see [Start again from zero](#11-start-again-from-zero).

### 4.2 Build and start

```bash
docker compose up -d --build
```

(The same in PowerShell on Windows.) The first time this takes **5-20 minutes** and
prints hundreds of lines; that is normal. It builds the website and the API, then
starts the database, Redis, the database setup ("migrations"), the API, the
background workers and the web server. Watch until everything is up:

```bash
docker compose ps
```

On Linux you should see **13 services**: `backend`, `celery_beat`, `celery_worker`,
seven `celery_worker_...`, `db`, `redis`, `web`. For the first minute they say
`(health: starting)`: that is normal. Run `docker compose ps` again every minute
until every line says `(healthy)`. `manga-stack-migrate` (the database setup) is not
in the list because it ran once and stopped; `docker compose ps -a` shows it as
`Exited (0)`, which is correct, and its log ends with `[INFO] System state ready`:

```bash
docker compose ps -a
docker compose logs manga-stack-migrate | tail -5
```

> Paste **one command per line**. `docker compose ps docker compose ps -a` on one
> line fails with *"no such service: docker"*.

If something says `restarting` or `exited (1)`, look at its log, and find the
message in [Troubleshooting](#10-troubleshooting):

```bash
docker compose logs --tail 50 backend
docker compose logs --tail 50 manga-stack-migrate
```

> **A computer with less than 4 GB RAM** (a small VM): use the small profile and a
> swap file. See [`GUIDE.md` Section 7](GUIDE.md#small-server-1-gb-ram) and
> [Section 2.5](GUIDE.md#25-a-swap-file-servers-with-2-gb-ram-or-less); on a test
> machine the line to add to `.env` is
> `COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml` (there is no override
> file on a test computer).

---

## 5. Check that it works

```bash
curl http://localhost:8000/healthz
```

should print `{"ok":true}` (on Windows PowerShell type `curl.exe`, not `curl`).
Then open the site in a browser **on the same computer** (in method A: Firefox
inside the VM):

**<http://localhost:8080>**

You should see the home page (empty: no series yet). That is the site running.

---

## 6. Become the owner

Nobody is admin on a fresh install. There is **no admin password and no special
admin page**: you become the owner by signing in with Google, once, with the e-mail
you choose. Two things in `.env` make that work.

### 6.1 Create the Google client (for `localhost`)

1. Open <https://console.cloud.google.com/> and pick (or create) a project.
2. **APIs & Services → OAuth consent screen**: choose *External*, fill the app name
   and your e-mail, save. Under **Test users**, add the Gmail address you will sign
   in with (required while the app is in "Testing").
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized JavaScript origins: `http://localhost:8080`
   - Authorized redirect URIs: `http://localhost:8000/api/auth/google/callback`
     (it must match `GOOGLE_OAUTH_REDIRECT_URI` in `.env` exactly: `make_env.py
     --local` already wrote that line)
4. Copy the **Client ID** and the **Client secret**, and put them in `.env`:

   ```bash
   nano .env
   ```

   (`Ctrl+O`, Enter to save, `Ctrl+X` to leave. On Windows: `notepad .env`; on
   macOS: `open -e .env`.) Fill in `GOOGLE_OAUTH_CLIENT_ID=` and
   `GOOGLE_OAUTH_CLIENT_SECRET=`: no quotes, no spaces.

### 6.2 Write the owner line

This writes one line into `.env`: a hash of the e-mail you will use as the owner
(the address itself is stored nowhere). It runs in a throw-away Docker container.
It asks one question, **Admin e-mail:** the Google e-mail you will sign in with.

**A, C and D:**

```bash
docker run --rm -it -v "$PWD":/w -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
```

**B (Windows PowerShell):**

```powershell
docker run --rm -it -v "${PWD}:/w" -w /w python:3.11-slim sh -c "pip install -q --disable-pip-version-check --root-user-action=ignore 'cryptography>=45' && python backend_fastapi/scripts/make_admin_hash.py --write .env"
```

It ends with `Done: the line is now in .env`.

### 6.3 Re-create the containers so they read `.env`

```bash
docker compose up -d --force-recreate
```

> ⚠ `docker compose restart` is **not** enough. A restart keeps the old settings;
> only `up -d --force-recreate` reads `.env` again. This is the most common reason
> a correct setup "doesn't work".

After about 30 seconds, check that the server sees everything:

```bash
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap admin-status
```

You want:

```
MAIN_ADMIN_EMAIL_HASH: set
Google sign-in: set up
Owner: not claimed yet -- sign in with Google using the owner e-mail.
```

### 6.4 Sign in and set up your authenticator

1. Open <http://localhost:8080> → **Log in** → **Continue with Google**, and pick the
   Google account whose e-mail you used in 6.2.
2. The first time, the site asks you to **complete your profile** (display name,
   username, birth date), like every new account. Fill it in. You are now the owner
   (`admin-status` says `Owner: claimed`, and nobody else can ever claim the seat).
3. Open **Admin**. It asks you to set up an authenticator app. The page shows a
   **setup key**. In the app on your phone: **+** → **Enter a setup key** (not "scan
   QR code") → any account name (for example *Manga admin*), the key, type *Time
   based*. Type the **6-digit code** the app shows → **Continue**.

From then on every admin page asks for a fresh code. There is nothing one-time to
burn: if you sign out, just sign in with Google again.

**Lost your phone, or locked out?** Put your e-mail on the first line:

```bash
OWNER_EMAIL=you@example.com
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email "$OWNER_EMAIL"
```

then sign in with Google and open **Admin**: it asks you to set up the new phone.
**No Google yet?** A sign-in link without e-mail (admin pages still ask for the code):

```bash
OWNER_EMAIL=you@example.com
docker compose exec backend python -m backend_fastapi.scripts.cli_bootstrap login-link --email "$OWNER_EMAIL"
```

Open the printed link in your browser. (You cannot claim the owner seat without
Google.)

---

## 7. Test every part of the website

Go through this list in order and write down anything that looks wrong, feels slow,
or does something unexpected. Every item says what you should see.

**Guests start with everything open:** *Sign-in required* is **off**, so anyone can
browse and read. Use a **private window** for the "as a visitor" checks, and your
normal window for the owner checks.

### 7.1 As a visitor (private window, not signed in)

| # | Do this | You should see |
| --- | --- | --- |
| 1 | Open `http://localhost:8080` | The home page loads with no error |
| 2 | Open a series, then a chapter (after 7.2 has imported one) | Pages load in order; the chapter shows in the reader |
| 3 | Bookmark a series, open **My Library** | The series is listed under Bookmarks; it stays after a reload |
| 4 | Read a chapter, go back to the series | The chapter you read is dimmed; "continue" points at it |
| 5 | Use the search box | Results appear for part of a title |
| 6 | Open `http://localhost:8080/admin` | You are asked to sign in; you do **not** see admin pages |

### 7.2 Import a series (owner window)

1. **Admin → Series Management → Import & Scrape Manga.**
2. Enter the **MangaUpdates link** and the **source series URL** of a series **you
   have the rights to host**, choose the page layout, and click **Test & Live
   Preview**: it must show a title, a chapter count and page images.
3. Click **Start Auto-Scrape**. Watch it work:

   ```bash
   docker compose logs -f celery_worker_scrape celery_worker_compress
   ```

   (`Ctrl+C` to stop watching.) Chapters appear on the series page as they finish.
   Pictures are converted to WebP, so it takes a few minutes per chapter.

If the preview finds nothing, the site isn't covered by a built-in parser: use
**Admin → Series Management → Custom Parser** (see [`GUIDE.md` Section 20](GUIDE.md#20-appendix-the-admin-area)).
Some sites (Cloudflare checks, logins, scrambled pictures) cannot be added.

### 7.3 Readers and accounts

| # | Do this | You should see |
| --- | --- | --- |
| 1 | In the private window, sign in with a **second Google account** (add it as a Test user in the Google console first) | You get a normal reader account; there is no admin link |
| 2 | Bookmark a series and read a chapter while signed in | Both show in **My Library** |
| 3 | Now sign in with the **same** reader account in a *different* window kind: if you used the private window above, use your normal window (a private window and a normal window keep separate storage, like two devices) | The bookmark **and the dimmed chapters** appear there too: the account keeps them for you |
| 4 | In **My Library → History**, press **Clear** | History empties on this window and on the account; the other window, after a reload, shows no dimmed chapters |
| 5 | Sign out and read a chapter as a guest, then sign in | That chapter is sent to the account and stays dimmed |

### 7.4 The admin area (owner window)

| # | Do this | You should see |
| --- | --- | --- |
| 1 | **Admin → Site Functions**: switch **Comments** off, open a chapter in the private window, switch it on again | While it is off the comments box is gone; it returns when switched on |
| 2 | **Admin → Secret Vault**: unlock with your authenticator code | The vault opens for 10 minutes; settings are listed in groups |
| 3 | **Admin → Role Management** | You see yourself as owner; Admins, seats and presets are listed |
| 4 | **Admin → Storage & Backups**: set a backup password, press **Back up now** | A backup appears in the list; **Download** saves it |
| 5 | Switch **Sign-in required for everyone** on, open a private window, then switch it off | While on, a visitor lands on the login page; off, guests read again |
| 6 | **Admin → User Database**: open your reader account | You can see it; your owner account cannot be changed by anyone |

### 7.5 Translation and OCR (optional)

1. **Admin → Secret Vault → Translation & OCR**: set *Server OCR enabled* to true,
   then restart the API and workers:

   ```bash
   docker compose restart backend celery_beat $(docker compose config --services | grep '^celery_worker')
   ```

2. As a reader: **Settings → AI & OCR Engines**, add a free Google Gemini key and
   press **Test connection**; **Settings → Reading & Translation**, switch the
   translation overlay on.
3. Open a chapter in a language you can't read: the reader shows the translation
   over the speech bubbles.

If the page says *"Text was found but not translated"*, OCR works but no translator
key is set. If OCR is *"not available"*, rebuild with `docker compose up -d --build`.

### 7.6 Sign-in e-mail (optional)

Until SMTP is set in **Admin → Secret Vault → Email & magic links**, a magic link
requested on the site is **printed in the log** instead of being e-mailed:

```bash
docker compose logs -f celery_worker_email
```

(`Ctrl+C` to stop.) Open the printed link to finish signing in.

### 7.7 After you restart

Prove nothing is lost when the computer restarts: reboot it (or in method B, restart
Docker Desktop), wait a minute and run `docker compose ps`. Everything must come
back healthy, and the series and your account must still be there.

---

## 8. What to send when something looks wrong

Run these and copy their **output** (never copy `.env`: it holds your secrets):

```bash
cd ~/manga-website-v1.01
git log -1 --oneline
docker compose ps -a
docker compose logs --tail 80 backend
docker compose logs --tail 40 manga-stack-migrate
docker stats --no-stream
free -h
df -h /
```

Also write down: what you clicked, what you expected, what you saw instead, and
whether it happens in a private window too. A screenshot of the browser page and of
the browser's console helps a lot. **The site blocks the `F12` key, `Ctrl+Shift+I/J/C`,
`Ctrl+U` and right-click** (its "anti-tamper" guard), so open the console from the
browser's menu instead: Firefox ☰ → *More tools* → *Web Developer Tools* → *Console*;
Chrome/Edge ⋮ → *More tools* → *Developer tools* → *Console*.

`docker stats --no-stream` and `free -h` show how much memory and CPU the site uses;
that is how we will decide what server size you need.

---

## 9. Everyday commands

| Want to | Command |
| --- | --- |
| See what is running | `docker compose ps` |
| Stop the site (data is kept) | `docker compose down` |
| Start it again | `docker compose up -d` (Windows/macOS: Docker Desktop must be running) |
| Apply a change you made in `.env` | `docker compose up -d --force-recreate` |
| Watch the API log | `docker compose logs -f backend` (`Ctrl+C` to stop) |
| Get the newest version of the site | `git pull --ff-only`, then `docker compose build --pull`, then `docker compose up -d --force-recreate` |
| Memory and CPU per container | `docker stats --no-stream` |
| Disk used by Docker | `docker system df` |

The site starts by itself after a reboot (Docker restarts the containers). On
Windows/macOS: Docker Desktop → Settings → General → **Start Docker Desktop when you
sign in**.

After `git pull`, rebuild: restarting is not enough, because the code is baked into
the image.

---

## 10. Troubleshooting

| What you see | What it means and what to do |
| --- | --- |
| `permission denied ... /var/run/docker.sock` | Docker is installed; your terminal isn't in the `docker` group yet (`groups` doesn't list it). Reboot after `usermod`. Don't reinstall Docker. |
| `trying to overwrite '/usr/libexec/docker/cli-plugins/docker-compose'` or `N not fully installed or removed` | A second copy of Docker (`docker.io`, `docker-compose-v2`) was installed on top. Use *Repair a mixed install* in [`GUIDE.md` Section 2.3](GUIDE.md#23-docker). |
| `error during connect` / `cannot find the file specified` / `Cannot connect to the Docker daemon` (Windows, macOS) | Docker Desktop isn't running. Start it and wait for **Engine running**. |
| `no configuration file provided: not found` | You are not in the project folder: `cd ~/manga-website-v1.01` (Windows: `cd $HOME\manga-website-v1.01`). |
| `no such service: docker` | Two commands were pasted on one line. Paste one per line. |
| `(health: starting)` in `docker compose ps` | Normal for the first minute. Wait, then run it again. |
| `failed to solve: image "docker.io/library/manga-backend:latest": already exists` | An old copy of the code (it built the same image once per worker at the same time). `git pull --ff-only`, then `docker compose up -d --build`. Or: `docker compose build backend web` then `docker compose up -d`. |
| Build dies with `Killed` / exit code 137 / `npm ci` stops | Out of memory. Give the VM or Docker 4 GB or more, or use the small profile and a swap file (Section 4.2 note). |
| `exec ... no such file or directory` or `\r: not found` in a container log (Windows) | The files were downloaded with Windows line endings. Delete the folder, run `git config --global core.autocrlf false`, and clone again. |
| `invalid reference format` or `/w` errors in `docker run` (Windows) | Run it from PowerShell (not *cmd*), inside the project folder, and copy the line exactly, including the double quotes around `${PWD}:/w`. |
| `Set EMAIL_ENCRYPTION_KEY to a Fernet key` | There is no `.env`, or you are in the wrong folder. Go to the project folder, then Section 4.1. |
| `password authentication failed` (database) | The database was created with other passwords than the ones now in `.env` (for example `.env` was remade). If the site has no content yet: [Start again from zero](#11-start-again-from-zero). |
| `port is already allocated` | Another program uses port 8080 or 8000. Stop it, or change the left number of `ports:` in `docker-compose.yml`. |
| Site loads but sign-in keeps looping | On `http://localhost`, `FORCE_HTTPS_REDIRECTS` must be `false` (`make_env.py --local` does this). Fix the line, then `docker compose up -d --force-recreate`. |
| Signed in with Google but I'm not the owner | Run `admin-status` (Section 6.3). *"MAIN_ADMIN_EMAIL_HASH: not set"* → you used `restart`: run `docker compose up -d --force-recreate`. *"DAMAGED"* → redo 6.2. *"Owner: claimed"* → the seat is already taken; ownership never passes. Otherwise test `.env` with the `--check` line below and use exactly that Google address. |
| Google doesn't make me the owner, and I want to test `.env` | Same `docker run` line as 6.2 with `--check .env` instead of `--write .env` (inside the `sh -c` text). It says whether the e-mail matches or the line is damaged. |
| "Continue with Google" says not configured | The client ID/secret are missing in `.env`, or you didn't run `docker compose up -d --force-recreate` after adding them. |
| Google says `redirect_uri_mismatch` or `Access blocked` | The redirect address in the Google console must be exactly `http://localhost:8000/api/auth/google/callback`, and your Gmail must be a **Test user** while the app is in "Testing". Use `localhost`, not an IP address. |
| Authenticator code refused | The phone's clock is off. Turn on automatic date & time on the phone, then type a fresh code (each lasts 30 seconds). |
| Closed the browser at the setup-key step | No harm. Open **Admin** again: it shows a new setup key. Delete the half-made entry in the app. |
| Admin pages say **"Set up your authenticator app"** | Expected on the owner's first visit: open **Admin**, add the setup key and type the code. |
| Imports stay "queued" forever | Workers or beat not running: `docker compose ps`. |
| The site still opens in Firefox after you removed everything | It is the browser's stored copy, not a server. Open `about:serviceworkers`, **Unregister** `localhost:8080`; press `Ctrl+Shift+Delete`, choose **Everything**, tick **Cache** and **Cookies and Site Data**, and reload. |
| Anything else | Section 8 (what to send), and the troubleshooting tables in [`GUIDE.md` Section 17](GUIDE.md#17-troubleshooting). |

---

## 11. Start again from zero

Only when the test site has **no content you want to keep**. This deletes the
database, all uploaded images and your settings file.

**A, C and D:**

```bash
cd ~/manga-website-v1.01
docker compose down --volumes --rmi all --remove-orphans
rm .env
```

**B (Windows PowerShell):**

```powershell
cd $HOME\manga-website-v1.01
docker compose down --volumes --rmi all --remove-orphans
Remove-Item .env
```

Then continue from [Section 4.1](#41-create-env). (`--rmi all` also removes the
built images, so the next start rebuilds them; leave it off for a faster restart.)

In a **VMware VM** the quickest clean slate is the snapshot from Section 2: *VM →
Snapshot → Revert to "clean Ubuntu"*.

---

## 12. When you are happy: go live

When the test site does everything you want, [`GUIDE.md`](GUIDE.md) puts the same
site on a Linux server with your domain, HTTPS, a firewall and backups. Differences
you will meet there, so none of them is a surprise:

| | This test | The live server |
| --- | --- | --- |
| Address | `http://localhost:8080` | `https://your-domain` |
| `.env` made with | `make_env.py --local` | `make_env.py` + your domain lines |
| HTTPS, firewall | not needed | required (Caddy, `ufw`) |
| `docker-compose.override.yml` | not needed | needed (production mode, private ports) |
| Google redirect address | `http://localhost:8000/api/auth/google/callback` | `https://your-domain/api/auth/google/callback` |
| Backups | not needed | required |
| Who can see it | only you | everyone |
