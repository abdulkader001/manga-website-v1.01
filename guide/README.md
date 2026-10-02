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

**Already installed, and the admin sign-in "doesn't work"?** Jump to
**Step 6** in your guide. The old admin password and `/admin-login` page are
gone: you now become the owner by signing in with Google.

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

There is no admin password and no admin page. The owner is the first person
to sign in with Google using the e-mail you choose:

1. On the server you make one line for `.env`: a hash of your **e-mail**. The
   site stores only the hash, never the e-mail itself. Your Google client ID and
   secret also go in `.env` at first (you need Google to get in).
2. You sign in with Google using that e-mail. Google must say the address is
   verified, and the site must not have an owner yet. Your account becomes the
   owner, and nobody else can ever claim the seat.
3. Open **Admin**. It asks you to set up an authenticator app: add the setup key
   and type the 6-digit code. Every admin page then asks for a fresh code, so
   someone who steals your Google password still can't use the admin area.
4. Nothing is one-time, so nothing can burn out and lock you out. If you lose
   your phone, remove the old authenticator on the server (`reset-2fa`), sign in
   with Google and set up the new one.

---

## The helper tools (all run from the project folder)

| Command | What it does |
| --- | --- |
| `backend_fastapi/scripts/make_env.py --local` | Creates `.env` with fresh random secrets (refuses to overwrite an existing one). |
| `backend_fastapi/scripts/make_admin_hash.py --write .env` | Asks for your e-mail and writes the owner line (`MAIN_ADMIN_EMAIL_HASH`) into `.env`. |
| `backend_fastapi/scripts/make_admin_hash.py --check .env` | Tests an e-mail against what is in `.env` ("why doesn't Google make me the owner?"). |
| `python -m backend_fastapi.scripts.cli_bootstrap admin-status` (inside the backend container) | Says whether the server sees the owner line and Google sign-in, and whether the owner seat is claimed. |
| `python -m backend_fastapi.scripts.cli_bootstrap reset-2fa --email …` | Removes a lost authenticator. |
| `python -m backend_fastapi.scripts.cli_bootstrap login-link --email …` | Prints a one-time sign-in link without sending an e-mail. |

The guides show the exact command for your system: through Docker, so you
don't have to install Python yourself.

For running the site on a public domain with HTTPS, backups and updates, see
[`../GUIDE.md`](../GUIDE.md) after you finish your install guide.
