# Install guides

Pick the guide for the computer that will run the site:

| Your computer | Guide |
| --- | --- |
| Windows 10 / 11 | [INSTALL-WINDOWS.md](INSTALL-WINDOWS.md) |
| macOS (Intel or Apple Silicon) | [INSTALL-MACOS.md](INSTALL-MACOS.md) |
| Linux (Ubuntu / Debian, a home PC or a cloud server) | [INSTALL-LINUX.md](INSTALL-LINUX.md) |

All three follow the same 9 steps. Only the install commands and the way you
type a few commands differ. Each guide goes from an empty computer to a
running site with you signed in as the admin.

**Already installed, and the admin password "doesn't work"?** Jump to
**Step 6** in your guide. It replaces the old admin lines in `.env` with new
ones that can't be damaged, and explains every reason the old ones failed.

---

## The words used in the guides

| Word | Meaning |
| --- | --- |
| **Terminal** | The window where you type commands. Windows: *PowerShell*. macOS: *Terminal*. Linux: *Terminal* or your SSH window. |
| **Project folder** | The `manga-website-v1.01` folder you download in Step 2. Run every command from inside it. |
| **`.env`** | The settings file in the project folder. It holds the site's secret keys and the admin identity. Never share it or upload it anywhere. |
| **Docker** | The program that runs the site's parts (website, API, database, workers) in "containers", the same way on every computer. |
| **Authenticator app** | A phone app that shows a new 6-digit code every 30 seconds: Google Authenticator, Microsoft Authenticator, Aegis, 1Password… |

---

## How the site owner (admin) signs in

The admin sign-in at `/admin-login` is **one-time only**:

1. On the server you make two lines for `.env`: a hash of your **e-mail** and a
   hash of a **one-time password**. The site stores only these hashes, never
   the e-mail or password themselves.
2. You open `http://<your-site>/admin-login` once and enter the e-mail and
   password. The page shows a setup key; you add it to your authenticator app
   and type the 6-digit code.
3. You are now the main admin. **From that moment the page is gone.**
   `/admin-login` shows the normal "Page not found", like an address that never
   existed. Nothing on the site links to it, and the used password can never
   work again, even if someone finds it in your notes.
4. From then on you sign in like everyone else (magic link, Google or
   Microsoft, once you set them up). Every admin page also asks for the
   authenticator code, so someone who steals your Gmail still can't get in.

The page only comes back if someone with access to the server puts a **new**
one-time password in `.env` (for example after you lose your phone). That new
password also works once.

---

## The helper tools (all run from the project folder)

| Command | What it does |
| --- | --- |
| `backend_fastapi/scripts/make_env.py --local` | Creates `.env` with fresh random secrets (refuses to overwrite an existing one). |
| `backend_fastapi/scripts/make_admin_hash.py --write .env` | Asks for your e-mail and one-time password and writes the two admin lines into `.env`. |
| `backend_fastapi/scripts/make_admin_hash.py --check .env` | Tests an e-mail and password against what is in `.env` ("why isn't my password accepted?"). |
| `python -m backend_fastapi.scripts.cli_bootstrap admin-status` (inside the backend container) | Says whether `/admin-login` is open, used up, or not set up, and whether the server can see the two lines. |
| `python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email …` | Removes a lost authenticator. |
| `python -m backend_fastapi.scripts.cli_bootstrap login-link --email …` | Prints a one-time sign-in link without sending an e-mail. |

The guides show the exact command for your system: through Docker, so you
don't have to install Python yourself.

For running the site on a public domain with HTTPS, backups and updates, see
[`../GUIDE.md`](../GUIDE.md) after you finish your install guide.
