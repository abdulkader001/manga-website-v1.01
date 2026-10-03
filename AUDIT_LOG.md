# Audit Log — MangaWorld

This file records every change made to the website: **what** changed, **why**,
**where** in the code, what it did to the **database and settings**, how to
**check** it works, and how to **undo** it. It is the history book of the site.
`GUIDE.md` is the manual for running it.

**Rule:** every change that is merged adds an entry at the top of
[Change entries](#change-entries), in the same pull request as the change.
Use the [entry template](#entry-template). No entry, no merge.

Contents

1. [How the site is put together](#1-how-the-site-is-put-together) (read this first)
2. [Database migration ledger](#2-database-migration-ledger)
3. [How to undo a change](#3-how-to-undo-a-change)
4. [Change entries](#change-entries) (newest first)
5. [Open items and known limits](#5-open-items-and-known-limits)
6. [Entry template](#entry-template)

---

## 1. How the site is put together

| Part | What it is | Where |
| --- | --- | --- |
| Website | React 19 + Vite + Tailwind, served by the `web` container (nginx) | `src/` |
| API | FastAPI, under `/api/v1/...` | `backend_fastapi/app/` |
| Workers | Celery: scrape, compress, OCR, translation, e-mail, notifications, maintenance, plus `celery_beat` (schedules) | `backend_fastapi/app/tasks/` |
| Database | PostgreSQL. Schema changes only through Alembic migrations | `backend_fastapi/app/migrations/versions/` |
| Queue/cache | Redis | — |
| Deploy | `docker-compose.yml`. The one-shot `manga-stack-migrate` runs `alembic upgrade head` before the API starts | repo root |

### Where settings live (three layers)

| Layer | Holds | Who changes it | Undo |
| --- | --- | --- | --- |
| `.env` on the server | Foundation only: database/Redis, signing and encryption keys, `INTEGRATIONS_SECRET`, admin identity (`MAIN_ADMIN_EMAIL_HASH` only), the Google sign-in client (`GOOGLE_OAUTH_CLIENT_ID` / `_SECRET`, needed before the owner can open the vault; may be moved into it afterwards), starting site address | Whoever has the server | Edit the file and recreate the containers |
| **Secret Vault** (Admin → Secret Vault) | Everything else: Google/Microsoft sign-in, SMTP/magic links, OCR/translation, API keys, limits, Sentry, **website domain**, the **backup** schedule, password and storage keys (`BACKUP_*`, set from Storage & Backups), **Geolock** (`GEOLOCK_*`, set from Geolock) and the stored-picture settings (`PAGE_MAX_WIDTH`, `PAGE_KEEP_ORIGINALS`, `MIRROR_PAGE_IMAGES`) | Main admin only, with an authenticator code and a 10-minute unlock | Remove the value and it falls back to `.env`. `VAULT_PRELOAD_DISABLED=true` skips the vault if a bad value stops start-up |
| **Admin Settings** (database) | Site name/logo/footer, donations, session policy, the default reader mode | Main admin (an Admin only if the owner switched Admin Settings on) | Change it back in the page |
| **Site Functions** (database, Admin → Site Functions) | The on/off switch of every main website function: sign-in required (starts **off**), maintenance, new accounts, each sign-in method, comments, community, reports, notifications, OCR, translation, ads, support links, sitemap/RSS, scraping, and the two IP-privacy switches. **Owner only, never delegable** (no permission opens it) | The owner | Switch it back, or `cli_bootstrap functions-reset` |

### People and roles

- **Main admin**: one owner. Claims the seat by signing in with **Google** once, using the e-mail whose Argon2id hash is `MAIN_ADMIN_EMAIL_HASH` in `.env` (Google must report the address verified, and the site must have no owner yet). No admin password, no admin page, nothing one-time to burn. Ownership never passes: once an owner exists, a changed hash promotes nobody. Then they set up an authenticator in **Admin**; admin features stay shut until they have, and every admin page asks for a fresh code. A magic link or Microsoft sign-in with the owner's e-mail never promotes (it reaches the already-claimed account). Lost phone: `cli_bootstrap reset-2fa`, sign in with Google, enrol again.
- **Sub-admin**: a user with per-person permission toggles (Role Management). Sees only **their own** rows in the admin audit log unless granted *See the full audit log* (`view_full_audit`). Previews, imports and re-scrapes use the Scraper AI only for a sub-admin who holds it.
- **Admin** (`UserRole.CO_ADMIN`; at most **two**, `MAX_ADMINS`): the owner's right hand. Holds every power except Admin Settings, the cache and "delete all manga" (`ADMIN_OFF_BY_DEFAULT`) until the owner switches them on; only the owner changes an Admin's toggles (switching a site-owner power on needs the owner's authenticator code). Has power over sub-admins and users only (`permissions_service.assert_may_act_on`, `authorize_change`): never over another Admin, themselves or the owner. Sees sub-admins' and users' e-mail, never an Admin's or the owner's. Needs an authenticator and a fresh code to use site-owner powers (`dependencies/powers.py`). Appoints sub-admins from a shared pool of **50** seats (`SUB_ADMIN_POOL`; an equal share unless the owner sets it). Keeps a **succession line** of up to two sub-admins (`admin_successors`); only the owner makes, removes or hands over an Admin seat (`services/admin_roles.py`, `api/routers/roles_admins.py`). `UserRole.ADMIN` is only the old name of the owner tier.
- **Sub-admin**: per-person toggles set by an Admin or the owner, never above the owner's **ceiling** (`system_settings.sub_admin_blocked_permissions`) and never a site-owner power. Power over users only. Custom roles (presets) are created by the owner only.
- **Automatic succession** (owner only, off by default, owner's code to change): an Admin idle longer than the chosen days (default 60) becomes a user and the first eligible sub-admin in their line (still a sub-admin, active, with an authenticator) takes the seat as it is: the owner's restrictions, the seats and the appointees (`services/admin_succession.py`, daily job). The owner can hand a seat over at once. Ownership never passes to anyone; `/admin/demote-main` stays owner-only.
- **Owner-only pages, not delegable** (no permission opens them): **Site Functions** (the website's on/off switches) and Role Management → **Tab access** (which admin tabs each Admin / sub-admin sees, and "switch all powers off": the person keeps the title and the seat but nothing in the admin area answers them). An Admin can't see either, even one holding Role Management.
- **Visitors' IP addresses are for the owner only** (Site Functions → *Visitor IP addresses are for the owner only*, on by default): the audit log shows them to the owner alone; the legacy admin-token list is owner only; the ad-click log line no longer prints one. *Record visitor IP addresses* (on by default) can stop new entries storing one.
- **Error Report** (`view_error_reports`, Admin → Error Report): errors from the API, the workers and readers' browsers with a likely cause and fix. The owner and Admins hold it by default; a sub-admin only if granted. Browsers report to the open route `POST /errors/report` (rate-limited; no IP, account or query string stored; e-mails and tokens masked).
- **User (reader)**: signs in with a magic link, Google or Microsoft. **No passwords.** One inbox gives one account for life.

### Data that is deliberately *not* on the server

- Reading history and "where I stopped" live in the reader's browser (`localStorage` key `mw_library_v1`, `src/utils/library.js`), which stays the main copy and works for guests. For a **signed-in** reader the server also keeps which chapters they opened and when (`read_history` table: user, series, chapter, time; `src/components/HistorySync.jsx`, `api/routers/history.py`) so the dimmed chapters and "where I stopped" follow them to a new device. Nothing else about their reading is stored. Guests (and export/import) are unchanged.
- Bookmarks live in the browser too, keyed by series ID. For a **signed-in** reader the server also keeps the bookmarked series ids (`bookmarks` table, `src/components/BookmarkSync.jsx`) so new-chapter alerts reach them (`services/series_alerts.py`) and the list follows them to other devices. Guests' bookmarks stay in their browser only.

### Server-side tools (run with `docker compose exec backend python -m backend_fastapi.scripts.<name>`)

| Command | Does |
| --- | --- |
| `make_admin_hash.py [--write .env \| --check .env]` | Makes the `MAIN_ADMIN_EMAIL_HASH` line (`$`-free `a2:` form), writes it into `.env`, or checks an e-mail against `.env`. Needs only Python + `cryptography`; runs without the site (`guide/` shows the `docker run` form) |
| `make_env.py [--local]` | Creates a new `.env` with random secrets and matching DB/Redis passwords. Never overwrites an existing `.env`. Standard-library Python only |
| `cli_bootstrap admin-status` | Can the server see the owner line, is Google sign-in set up, and is the owner seat claimed |
| `cli_bootstrap admin-hashes` | Same as `make_admin_hash.py` (prints the line) |
| `cli_bootstrap reset-2fa --email …` | Removes a lost authenticator |
| `cli_bootstrap functions-reset` | Puts every Site Function back to its default (a switch locked you out) |
| `cli_bootstrap geolock-off` | Switches Geolock off (you blocked the country you are in) |
| `cli_bootstrap login-link --email …` | Prints a one-time sign-in link (no e-mail sent) |
| `set_site_domain new-domain.com` / `--clear` | Moves the site to a new domain when the admin page can't be reached |

---

## 2. Database migration ledger

Migrations run in this order. "Undo" is `alembic downgrade <the revision before>`
(see [§3](#3-how-to-undo-a-change)). **Lossy** means the downgrade can't bring
back what the upgrade removed, so restore a backup instead.

| Revision | PR | What it does | Downgrade |
| --- | --- | --- | --- |
| `20261004_vault_secrets` | #23 | New `vault_secrets` table (encrypted settings) | Drops the table. **Vault values are lost**; the site falls back to `.env` |
| `20261005_local_ocr_default_on` | #24 | Built-in OCR on by default; existing rows switched on | Default goes back to off (rows stay on) |
| `20261006_reader_overlay_settings` | #24 | Reader overlay columns (on/off, target language, colours, context AI, limits) | Drops the columns. Readers' overlay choices are lost |
| `20261007_three_roles` | #24 | Moderators become users; moderator columns dropped | **Lossy**: the columns come back empty and former moderators can't be identified |
| `20261008_chapter_title_translations` | #25 | `chapters.title_translations` cache | Drops the cache (it rebuilds itself) |
| `20261009_login_required` | #27 | `system_settings.login_required` (default off) | Drops it, so the site is open to guests |
| `20261010_email_identity` | #27 | Unique `users.email_identity_hash` (one inbox, one account), backfilled | Drops it. Gmail-alias duplicates become possible again |
| `20261011_admin_password_single_use` | #27 | `system_settings.admin_setup_password_used` | Drops it. The column is unused now (the one-time password is gone), so this changes nothing |
| `20261012_overlay_text_scale` | #33 | `user_processing_settings.overlay_font_size` becomes the 1-100 slider (pixels converted: 20 px → 28.5); new `overlay_outline_color`, `overlay_match_bubble` | **Lossy**: sizes go back to pixels rounded and capped at 10-40 px (a reader on 100 = 70 px gets 40 px); outline colour and bubble switch are dropped |
| `20261013_admin_succession` | #34 | `admin_activity_days` table (one row per admin per active day) and `system_settings.succession_enabled` / `succession_inactive_days` / `succession_enabled_at` | Drops them. **Lossy**: the activity history and the succession switch are gone (succession is off again) |
| `20261014_four_roles` | #35 | Adds role `CO_ADMIN` (Postgres enum value if native), `users.appointed_by` / `sub_admin_quota` / `admin_since`, `admin_successors`, `system_settings.sub_admin_blocked_permissions`; deletes site-owner overrides held by sub-admins (they can no longer hold them) | **Lossy**: Admins go back to sub-admins, and the new columns, succession lines and ceiling are dropped. The deleted overrides do not come back (re-promote in Role Management) |
| `20261015_login_required_default_on` | #41 | `system_settings.login_required` column default becomes **on**, and the existing row is set to on | **Lossy**: only the default goes back to off. The value the owner had before the upgrade is not kept, so existing rows stay on (turn it off in Admin Settings) |
| `20261016_site_functions_and_tab_access` | #41 | New table `site_functions` (owner's switches) and `users.visible_admin_tabs` / `users.powers_suspended` | **Lossy**: drops them. Every function goes back to its default and every Admin / sub-admin goes back to "follow my permissions", with no powers switched off |
| `20261017_login_required_default_off` | #42 | `system_settings.login_required` column default becomes **off** again, and the existing row is switched off (guests can read until the owner switches it on) | **Lossy**: only the default goes back to on. The value the owner had before the upgrade is not kept, so existing rows stay off (switch it on in Admin → Site Functions) |
| `20261018_cascade_series_children` | #50 (written for #48, shipped first in #50) | PostgreSQL: reading history, bookmarks and the OCR/translation caches are deleted with their chapter or series (`ON DELETE CASCADE`); `scraping_jobs.manga_id` and `translation_cache.ocr_cache_id` become empty instead (`SET NULL`) | Lossless: the rules go back to `NO ACTION`; no row is touched (rows already removed by deletes stay removed) |
| `20261019_error_reports` | #48 (from #49) | New table `error_reports` (Admin → Error Report: grouped errors with cause, fix, count, fixed flag) | **Lossy**: drops the table; the recorded errors are lost (nothing else depends on them) |
| `20261020_genres_ci_index` | #51 | PostgreSQL: index `ix_manga_genres_ci_gin` on `lower(genres::text)::jsonb`, used by the case-blind genre filter | Lossless: drops the index; the filter still works, only slower on big catalogues |

Check where a server is: `docker compose exec backend alembic current`.

---

## 3. How to undo a change

Always **back up first** (`GUIDE.md` §12.1 has copy-paste commands). Then pick the smallest undo that works.

**A. Switch a feature off (no code change)**. Many features have a switch:
sign-in required and the other Site Functions (Admin → Site Functions, owner only), donations (untick "Shown" or remove),
domain (Secret Vault → Website domain → *Go back to .env address*), vault
values (remove → `.env` value).

**B. Undo a whole pull request in git.** Every PR is one merge commit on `main`:

```bash
git log --oneline --first-parent main      # find the merge commit, e.g. 6412a23
git revert -m 1 6412a23                     # makes a new commit that undoes it
git push origin main                         # (or open a PR with the revert)
```

**C. Undo its database changes too.** Do this **before** deploying the
reverted code if the PR added migrations. Downgrade to the revision listed
just before that PR's first migration in [§2](#2-database-migration-ledger):

```bash
docker compose run --rm manga-stack-migrate alembic downgrade 20261008_chapter_title_translations
docker compose run --rm manga-stack-migrate alembic current   # confirm
```

Undoing only the code and keeping the new columns is usually safe: the old
code ignores columns it doesn't know. The **lossy** rows in §2 are the
exceptions; for those, restore the database backup taken before the update.

**D. Deploy the result:** `docker compose build --pull && docker compose up -d --force-recreate`.

---

## Change entries

### 2026-10-03 — PR #NN: the site no longer freezes when several readers arrive at once; lighter pages

Merge SHA: fill in when known (the next PR fills it in). Branch `claude/project-thread-v7ek3a`.

The owner said the site feels clunky and its responses are slow, and asked to look into it after PR #48. A load test on a local copy (PostgreSQL 16, Redis, 1,000 series with 150,000 chapters) found that the API **froze**: one worker stopped answering at 50 concurrent requests with the full-size pool, and at 12 with the small-server pool (4 + 4). One homepage visit sends about 12 API calls at once. A stack dump showed the event loop waiting for a database connection. Findings in `/mnt/project-files/speed/findings.md` (project files).

| Change | Why | Main files |
| --- | --- | --- |
| **The sign-in, "sign-in required", permission and site-function guards no longer block the API worker.** They are plain functions that FastAPI runs in its thread pool, and each gives its database connection back as soon as it has read (`release_connection`) | They were `async def` and queried the database on the event loop. Each request also held two to four connections at once, so a burst emptied the pool, the loop waited for a connection, and nothing could return one: the worker froze for up to a minute | `dependencies/auth.py`, `dependencies/site_access.py`, `dependencies/site_functions.py` |
| **Maintenance mode's database reads run off the event loop** (pure ASGI middleware) | Every 10 s its flag read ran on the loop and froze the worker in the same way | `services/maintenance.py` |
| **A full connection pool answers 503 "The server is busy" with `Retry-After: 2`**, logged without a traceback and written to the Error Report at most every 30 s. "Sign-in required" no longer turns a busy pool into "Sign in to read" | Under load guests were told to sign in, or got 500 errors | `bootstrap/exception_handlers.py`, `dependencies/site_access.py` |
| **Previous/next chapter come from two indexed one-row lookups** | Each page turn loaded every chapter id of the series (plan P3-12) | `api/routers/manga.py` |
| **Lighter per-request work**: the security-header, legacy-alias, forwarded-header and backpressure middlewares are pure ASGI (same behaviour, same order) | Ten `BaseHTTPMiddleware` layers cost about 4 ms per request; `/healthz` went from 4.0 to 2.4 ms | `bootstrap/middleware.py`, `bootstrap/backpressure.py` |
| **One `/ad-slots` request per page** (shared and kept for a minute) | Each ad box fetched it: 6 calls on the homepage, 9 in the reader | new `src/utils/adSlots.js`, `AdPlacement.js`, `GlobalAds.js` |
| **Service worker v2**: covers are served from its cache without a second download (at most 300 kept); chapter pages and other pictures are left to the browser's own cache; an offline navigation opens the app; the v1 cache (every picture ever opened, no limit) is deleted on activate | It downloaded every picture again even when it had it, and filled readers' devices (plan P2-6) | `public/sw.js` |
| **The reader fetches the pages near the screen only**: a page holds a screen's height until it loads | Images had no height before loading, so `loading="lazy"` fetched all 40 pages at once (now 3 at first) | `src/components/ChapterViewer.js`, `ChapterViewer.css` |
| Tests: no `async` dependency touches the database (scans the code); the guards are not coroutines; the user lookup leaves no open transaction; a full pool answers 503, not sign-in; previous/next with chapter 0 and duplicate numbers; backpressure through ASGI; the shared ad-slot load; the service worker's fetch and activate handlers. Docs: GUIDE §4.2, three troubleshooting rows and a checklist line; `map.md`, `plan.md` | Prove it and keep the docs true | `tests/test_request_concurrency.py`, `tests/test_backpressure.py`, `src/utils/adSlots.test.js`, `src/test/serviceWorker.test.js`, `GUIDE.md`, `map.md`, `plan.md` |

Measured on the local copy with one API worker and the small-server pool (4 + 4). **Before:** froze at 12 concurrent requests (guests got 401 "Sign in to read" and 500 errors). **After:** 50 concurrent guests and 50 concurrent signed-in readers got 5,520 answers out of 5,520 with 200 (p50 about 0.8 s at 50 at once; one worker's CPU is the limit, about 60 requests per second). In the browser the reader starts with 3 page downloads instead of 40.

- **Database:** none.
- **Settings:** none new. `SQLALCHEMY_POOL_SIZE`, `SQLALCHEMY_MAX_OVERFLOW` and `SQLALCHEMY_POOL_TIMEOUT` are unchanged and now described in GUIDE §4.2. No setting moved between `.env`, the vault and Admin Settings.
- **Check:** after `docker compose up -d --build`, open the homepage in three browsers at once: all load. In the browser's network tab the homepage makes one `ad-slots` request. `docker compose logs backend | grep database_pool_busy` stays empty in normal use. Locally: `pytest backend_fastapi/tests/test_request_concurrency.py backend_fastapi/tests/test_backpressure.py backend_fastapi/tests/test_middleware_order.py`, `npx vitest run src/utils/adSlots.test.js src/test/serviceWorker.test.js`.
- **Undo:** `git revert -m 1 <merge>` and rebuild. Nothing is lost. Readers' devices keep the v2 service worker until they next visit, and then get the old one back.

---

### 2026-10-03 — PR #51: the P1 bugs from `plan.md` (visitors never see sources, takedown removes pictures, Browse, genres, homepage lists, chapter 0, deployment, honest admin screens)

Merge `d3a1dc5` (filled in by the next PR). Branch `claude/project-thread-ev89fm` (restarted from `main` after #48 merged).

The owner said "go ahead" with the P1 group, in one PR. Owner's questions answered with the plan's recommendations: Q-2 A (a takedown deletes the series' pictures and the picture routes check it), Q-3 (visitors never see sources; staff still do), Q-5 (genres matched whatever their capitals), Q-9 (Docker + Caddy only).

| Change | Why | Main files |
| --- | --- | --- |
| **Visitors never see where content comes from (P1-1).** `/manga/batch` goes through the public `MangaBase` allow-list and the viewer filter (no source, last scrape error, who added it, scrape settings); public chapter routes drop `url` / `chapter_url`; pages and covers not yet stored here go out as an opaque, encrypted proxy token (`/images/proxy?t=…`, Fernet from `SECRET_KEY`) instead of a raw source address or readable base64. Staff still see sources. Old signed `?u=&r=&s=` links keep working | Guests could read every source address, scrape errors and an admin's user id | `api/routers/manga.py`, `schemas/manga.py`, `services/catalogue_service.py`, `services/image_proxy.py`, `api/routers/reader.py` |
| **"Read now" / "latest chapter" links carry their chapter (P1-5)**: `first_chapter_id`, `latest_chapter_id` in list and detail | The response model dropped them, so every "Read Now" opened the series page | `schemas/manga.py` |
| **Takedown removes the pictures and has a screen (P1-2).** *Taken down* deletes the series' stored pages, its cover (unless another series shares it) and its OCR/translation caches, points chapters back at their source pages (so a restore can compress them again), and is audited (`SET_TAKEDOWN`). The backend picture routes refuse pictures of a series that may not be hosted (staff excepted); compression and scheduled checks skip it. New **Takedown** panel in Admin → Series (status, reason, type the name to confirm, server errors shown) | nginx kept serving the files of a taken-down series; nothing on the site could take a series down | new `services/takedown.py`, `routers/admin.py`, `routers/reader.py`, `services/page_mirror_service.py`, `services/scheduled_checks_service.py`, new `src/pages/Admin/TakedownPanel.jsx`, `SeriesManagement.jsx`, `src/services/api.js` |
| **Browse filters the whole catalogue (P1-3, P1-4).** Search, sort, status, type, include/exclude genres and page come from the address and go to the server; *Hide NSFW* is sent as exclusions; the real total and page count show; Next stops on the last page; a change goes back to page 1. Removed the filters the server cannot do (tags, chapter range, rating, "50+ translated", hiatus), the fixed "Trending" badge and the 7004 count. The homepage link uses `sort=new` | Filters ran on the 50 series on screen; the navbar search and links were ignored | `src/components/BrowseManga.js`, `Homepage.js` |
| **Genre filter ignores capitals on PostgreSQL (P1-6)** (`lower(genres::text)::jsonb ? 'action'`, with an index) | Real genres are stored "Action"; `?genre=Action` found nothing | `services/manga_service.py`, migration `20261020_genres_ci_index` |
| **Homepage Most viewed / New ask the server for their own ranking (P1-7)** | They re-sorted the 50 most recently updated series | `src/components/Homepage.js` |
| **Chapter 0 (P1-8)**: Read Latest / First Chapter use the server's chapter ids, else chapter-number order where 0 counts; the label uses the chapter title helper | "Read Latest" opened chapter 0 | `src/components/MangaDetail.js` |
| **Docker + Caddy only (P1-9).** Removed `deployment/manga-site.conf`, `manga-frontend.service`, the certbot units and script, and the `manga-api/worker/beat/worker-compress.service` units; the README worker command lists every queue | The host nginx file failed `nginx -t`; the systemd worker skipped the e-mail queue; the README command sent no sign-in e-mail | `deployment/`, `backend_fastapi/deployment/`, `README.md`, `backend_fastapi/README.md` |
| **Admin screens say what the server did (P1-10).** API Management shows the server's error for a refused save, delete or connection test (no "saved locally", no fake "Connection OK"), and no longer keeps a browser copy of the providers (keys included); an old copy is deleted when the page opens. The footer editor shows the server's list after each change and an error when refused | The owner saw "saved" while nothing was stored | `src/pages/Admin/ApiManagement.jsx`, `src/services/apiRegistry.js` (removed), `src/components/FooterEditor.js` |
| Tests: a contract test calls every public GET as a guest and a reader against a series whose sources contain `source.invalid` (none may show it); proxy tokens; takedown files, routes, audit and mirroring; Title-Case genres on PostgreSQL; Browse, homepage, chapter 0, takedown panel, API Management and footer editor failures. Docs: GUIDE (takedown, Browse, Docker + Caddy only, four troubleshooting rows, checklist), deployment READMEs, `map.md`, `plan.md` tick-list; #48's merge SHA filled in | Prove it and keep the docs true | `tests/test_public_source_privacy.py`, `tests/test_takedown_pictures.py`, `tests/test_genre_filter.py`, `src/**/*.test.jsx`, `GUIDE.md`, `map.md`, `plan.md` |

- **Database:** new migration `20261020_genres_ci_index` (index only); see §2.
- **Settings:** none. No setting moved between `.env`, the vault and Admin Settings.
- **Check:** after `docker compose up -d --build` and the migrations: as a guest, `curl -s https://<domain>/api/v1/manga/batch?ids=<id>` shows no `source_url`; a chapter's `pages` are `/api/v1/images/proxy?t=…` or `/api/v1/manga/pages/…`; `/browse?genre=Action` lists Action series; Admin → Series → 🚫 → *Taken down* on a test series, then its page and cover addresses answer 404. Tests: `pytest backend_fastapi/tests` (also on PostgreSQL), `npx vitest run`.
- **Undo:** `alembic downgrade 20261019_error_reports` (drops the index only), then `git revert -m 1 <merge>` and rebuild. Pictures deleted by a takedown do not come back (re-scrape or *Compress pictures* after setting the series back to *Online*); the host-nginx files come back with the revert.

---

### 2026-10-03 — PR #48: the four P0 bugs from `plan.md` (live site behind Caddy, deleting series, sign-in landing)

Merge `ce4c71b` (filled in by PR #51). Branch `claude/project-thread-ev89fm`.

The owner asked to work through `plan.md` from P0 down. These are the four "fix before go-live" bugs, plus the small items the plan groups with them (P2-2, P2-3, the nginx half of P3-9). Owner's questions answered with the plan's recommendations: Q-1 (Caddy → web nginx → backend stays; only local and Docker addresses are trusted as proxies) and Q-4 (deleting a series removes what points at it, in the database).

| Change | Why | Main files |
| --- | --- | --- |
| **The API works behind Caddy (P0-1).** The web nginx now passes on Caddy's `X-Forwarded-Proto: https` instead of replacing it with its own `http`, but only when the request comes from this machine or the Docker network (`$fwd_proto`) | Every API call was answered `307 → https://…` and looped; pages loaded with nothing working | `deployment/nginx/nginx.conf`, `deployment/nginx/site.conf` |
| **Each visitor is one visitor again (P0-2).** nginx takes the visitor's address from the last `X-Forwarded-For` hop, only from loopback/private proxies (`set_real_ip_from`, `real_ip_recursive off`), so per-visitor limits, the sign-in cap and Geolock see real addresses. Tested with real nginx: two visitors arrive as two addresses, a spoofed first hop is ignored, `https` is kept | Everyone shared the Docker gateway's address: one rate-limit bucket for the whole site, Geolock blocked nobody | same |
| **No visitor address in any log line** (house rule, now that real addresses arrive): nginx's access log uses a format without the address and its error log keeps only critical lines (every error line prints `client: <address>`); Gunicorn's access log is off unless `GUNICORN_ACCESS_LOG` is set | Real addresses would otherwise be written to logs | `deployment/nginx/nginx.conf`, `backend_fastapi/deployment/gunicorn.conf.py`, `.env.example` |
| **The backend believes scheme, host and port only from its proxy (P2-2)**, like the client address (`TRUSTED_PROXY_CIDRS`). The Node gateway (`server.ts`) also takes the visitor's address and scheme from a private proxy only | A client reaching the backend port could claim `https` or another host | `bootstrap/middleware.py`, `server.ts` |
| **Microsoft sign-in has a per-address limit (P2-3)**: the same 30 per 10 minutes as Google, and nginx's sign-in rate limit now covers `/auth/microsoft` | It had none | `routers/account.py`, `site.conf` |
| **Deleting series works (P0-3).** Deleting a series, bulk delete, "Delete all manga" and "Purge all images" no longer fail with 500 once a reader opened a chapter or a page was translated. The database removes reading history, chapter bookmarks and OCR/translation caches with their chapter or series; one `delete_series` service also removes them explicitly (for a database that missed the migration), commits per series and deletes picture folders; purge deletes translations before their OCR rows | Foreign keys with no delete rule refused the delete on PostgreSQL | migration `20261018_cascade_series_children`, `models/{manga,translation_cache,scraping}.py`, new `services/series_delete.py`, `routers/admin.py`, `routers/site_admin.py`, `tasks/scraper_tasks.py` |
| **Google / Microsoft sign-in lands on the home page (P0-4).** The default `MAGIC_LINK_REDIRECT_URL` (`.env.example`, GUIDE, the vault's domain switch) is now the home page, and the old `/auth/magic-complete` address redirects there | Every provider sign-in, including the owner's first, ended on "Page Not Found" | `src/app.js`, `vault_keys.py`, `.env.example`, `GUIDE.md` |
| nginx tidy-up (P3-9, nginx part): one `Cache-Control` header per file (the `expires` lines sent a second one); `sw.js`, `favicon.ico`, `logo*.png` and `manifest.json` are revalidated instead of cached a year | An old service worker stayed on devices for a year | `site.conf` |
| Tests: forwarded headers from untrusted vs trusted peers; Microsoft limit; every delete path on PostgreSQL with and without the new rules (fail on the old code); sign-in landing (backend and frontend). Docs: GUIDE §8 step 7, five troubleshooting rows, checklist; `map.md` foreign-key table and flows; `plan.md` tick-list | Prove it and keep the docs true | `tests/test_series_delete_children.py`, `tests/test_middleware_order.py`, `tests/test_login_ip_rate_limit.py`, `tests/test_sign_in_landing.py`, `src/app.test.jsx`, `GUIDE.md`, `map.md`, `plan.md` |

Not in this PR (later groups of the plan): delete-all and bulk delete as background jobs with progress and cover files (P2-1), the `nginx -t` / harness CI job (P2-10).

- **Database:** none new here. The P0-3 commit and its migration `20261018_cascade_series_children` were written for this PR and shipped first in #50 (same commit, cherry-picked), so main already has them.
- **Settings:** `MAGIC_LINK_REDIRECT_URL` default is now `https://<domain>/` (old values keep working). `GUNICORN_ACCESS_LOG` is off when blank (it was `-`). No setting moved between `.env`, the vault and Admin Settings.
- **Check:** after `docker compose build && docker compose up -d`: `curl -sI https://<domain>/api/v1/config/site-access` answers `200`, not `307`; `docker compose logs web` shows no visitor addresses; sign in with Google and land on the home page; delete a series someone has read (Admin → Series). Locally: `pytest backend_fastapi/tests/test_series_delete_children.py backend_fastapi/tests/test_middleware_order.py backend_fastapi/tests/test_login_ip_rate_limit.py backend_fastapi/tests/test_sign_in_landing.py` on PostgreSQL; `npx vitest run src/app.test.jsx`.
- **Undo:** `docker compose run --rm manga-stack-migrate alembic downgrade 20261017_login_required_default_off`, then `git revert -m 1 <merge>` and rebuild. Nothing is lost; the redirect loop and the 500s come back.

---

### 2026-10-03 — PR #48 (part 2): Admin → Error Report: what went wrong, the likely cause and the fix

Merged into PR #48 (one combined PR, the owner's choice); merge `ce4c71b`, as #48. Branch `claude/project-thread-y77vpo` (draft PR #49 closed in favour of #48).

The owner asked for an admin tab that shows what errors are happening, what the real problem is and how to fix it. Errors from the API server, the background workers and readers' browsers are now saved (grouped: one entry per distinct error, with a count) and shown in **Admin → Error Report** with a plain-language *Likely cause* and *How to fix*.

| Change | Why | Main files |
| --- | --- | --- |
| **Errors are recorded**: unhandled API exceptions and 5xx API errors (exception handler), worker tasks that failed for good (Celery `task_failure`), and browser script errors / crashed pages (`window` error + unhandled rejection listeners and the error boundary, sent to `POST /errors/report`) | Until now errors only went to server logs (and Sentry if set up), which the owner doesn't read | `bootstrap/exception_handlers.py`, `core/celery_app.py`, `src/utils/errorReporter.js`, `src/components/ErrorBoundary.js`, `src/index.jsx` |
| **Plain-language diagnosis**: 30 rules (database missing a table, database down, Redis down, disk full, out of memory, provider key refused, rate limits, scraper blocked or layout changed, SMTP, missing setting, stale page after an update, browser network failure, code bugs, harmless notices) each naming the page, setting or command to use | "What's the genuine problem, what are the fixes" | `services/error_report_service.py` (`RULES`, `diagnose`) |
| **Admin → Error Report tab**: open / fixed / all, filter by where it happened, counts, first and last seen, technical details, *Mark fixed*, *Reopen*, *Clear fixed*; a fixed entry reopens when the error happens again | The owner's request | `src/pages/Admin/ErrorReport.jsx`, `api/routers/error_reports.py`, `core/admin_tabs.py`, `src/constants/adminFeatures.js`, `src/app.js` |
| **New power `view_error_reports`** (Observability): owner and Admins by default, sub-admins off (grantable) | Only the owner/Admins should read server internals | `core/permissions.py` |
| **Privacy**: no IP, account or query string stored; e-mails, IPs, tokens, passwords and URL credentials masked before saving; the browser route's rate limit is keyed on a hash of the address; at most 2,000 rows kept | House rule: visitor IPs never stored or logged | `services/error_report_service.py` (`scrub`), `api/routers/error_reports.py` |
| `POST /errors/report` added to the route audit's list of open routes (a decision: guests' browsers crash too) | `tests/test_route_audit.py` lists every open route | `backend_fastapi/tests/test_route_audit.py` |

- **Database:** new migration `20261019_error_reports` (table `error_reports`); see §2.
- **Settings:** none. Mark fixed / reopen / clear go to the admin audit log (`ERROR_REPORT_RESOLVE`, `ERROR_REPORT_REOPEN`, `ERROR_REPORT_CLEAR`).
- **Check:** after `alembic upgrade head`, open **Admin → Error Report** as the owner: it says "No open errors". In a browser console on the site run `setTimeout(() => { throw new Error("test") })`; refresh the tab and a *Reader's browser* entry appears with a cause and fix. An Admin sees the tab; a sub-admin doesn't unless given *Error Report*. Tests: `backend_fastapi/tests/test_error_reports.py`, `src/pages/Admin/ErrorReport.test.jsx`, `src/utils/errorReporter.test.js`.
- **Undo:** `alembic downgrade 20261018_cascade_series_children` (drops `error_reports`, **lossy**: the recorded errors are gone), then `git revert -m 1 <merge>`. Nothing else depends on the table.

---

### 2026-10-03 — PR #50: scraped chapters show their pages at full quality; re-scraping series works; chapter alerts appear

PR #50, merge `909e9c1`. Branch `claude/project-thread-hu9r1l`.

The owner reported: importing a wujinmh.com series stored the sidebar's pictures instead of the chapter pages ("covering images"); picture quality was poor; deleting a manga and re-scraping it from *Series & AI Scraper Management* both failed; *Notifications & Chapter Alerts* didn't work; reading a 50-chapter import failed with "Too many requests"; and the scraper sometimes got blocked. The source sites could not be opened from the build sandbox (its network allows no outside sites), so the scraper causes were found in the code and reproduced with saved page shapes in tests. Deleting a series is PR #48's fix (`plan.md` P0-3), carried here as the same commit so the two PRs don't conflict; see #48's entry.

| Change | Why | Main files |
| --- | --- | --- |
| **Script page lists win over `<img>` tags.** For SinMH (`chapterImages`) and qTcms (`qTcms_S_m_murl_e`) readers the page list in the script is read first; the `<img>` selector is used only when there is none. Structure detection (sites with no parser) does the same | wujinmh's parser looks for `img[data-original]` and read the script only "when the selector finds nothing", but the sidebar's lazy-loaded thumbnails of other series carry `data-original` too, so the real pages were never read | `scrapers/base_scraper.py`, `scrapers/script_images.py` (`cms_images`), `scrapers/autodetect.py` |
| **Built-in parsers whose page selector lists alternatives** (`a, b, c`) keep only the biggest group of pictures that share one container, and drop pictures in `nav`/`header`/`footer`/`aside`, logos/banners and images narrower than 150 px. A parser with one selector (admin or Scraper AI) is used as written | The same sweep-in happens on the other Chinese/Korean presets (`img.lazy`, …) | `scrapers/base_scraper.py`, `scrapers/autodetect.py` (`main_image_group`) |
| **Pictures keep the source's quality.** A JPEG/PNG/WebP page that needs no change (no wider than the cap, not a spread to cut or a strip to slice, no transparency or EXIF rotation) is stored byte for byte with its own extension and type. Pages that must change are re-encoded at quality 94/92/90 (was 90/86/82), under a 2000 px cap (was 1440). Downloads ask for the original format first. New vault setting `PAGE_KEEP_ORIGINALS` (on) turns the old always-WebP behaviour back on | Every page was re-encoded as lossy WebP and shrunk; image CDNs that see `image/webp` in `Accept` often send a recompressed copy too | `services/page_image_service.py`, `api/routers/reader.py` (served type follows the file), `vault_keys.py`, `.env.example` |
| **Fetching like a browser** (what gallery-dl and Mihon/Tachiyomi extensions do): current Chrome/Firefox User-Agents (were Chrome 119), one User-Agent per website instead of a random one per request, the usual `Accept` / `Accept-Language` headers; `Retry-After` honoured on 403/429/503 (capped at 60 s); picture downloads retried up to 3 times on 429/5xx or a dropped connection (a 404 is not retried); the largest `srcset` entry is taken instead of a small `src` fallback | Requests that look like a bot, or that retry before the site allows, are what get a scraper blocked; a page that hit a burst limit stayed on the source | `scrapers/http_client.py`, `scrapers/base_scraper.py`, `scrapers/parsing.py`, `services/page_image_service.py` |
| **Re-scrape from *Series & AI Scraper Management* works.** The button asks for the series name to be typed back and sends it; Delete now asks first. Mutation buttons use TanStack Query 5's `isPending` (the re-scrape / resolve / delete report and rating buttons never disabled, so a double click sent two requests) | The page sent no body and the server, which requires the typed name, answered 422 every time | `src/pages/Admin/SeriesManagement.jsx`, `src/services/api.js`, `src/pages/Admin/ChapterReports.jsx`, `src/components/MangaDetail.js` |
| **Chapter pictures have their own rate-limit allowance** (4 × the generic 300 a minute, per visitor) for `/images/proxy`, `/manga/pages/…` and `/manga/covers/…` | Pages not mirrored yet are one proxy request each; a long chapter used up the budget and the chapter's own API call then failed (*Chapter Load Error: Too many requests*) | `utils/rate_limiter.py` |
| **Notifications page and bell read the server's types.** *Chapter Alerts & Issues* lists `chapter.new`, `chapter.reported`, `chapter.fix_completed`, `chapter.fix_failed`, `chapter.repeatedly_broken`; the badges and *Inspect Chapter* follow the same types; chapter reports carry `report_type` | The page looked for categories `chapter_issue` / `chapter_release` that the server never sends, so the tab was always empty | `src/utils/notificationTargets.js`, `src/pages/NotificationsPage.js`, `src/components/NotificationBell.js`, `api/routers/reader.py` |
| **Reference sites.** The owner's 18 saved homepages (Chinese, Japanese, Korean) are kept, trimmed and compressed, in `scrapers/reference/pages/`. `scrapers/reference/sites.py` records for each site its series and chapter address patterns, how its reader delivers pictures, its obstacles and whether it can be read; `scrapers/reference/GUIDE.md` is a step-by-step recipe for adding a site. When the Scraper AI writes a parser for one of these sites, its prompt now carries those notes and the built-in parser as a starting point | The owner wants any AI, even a small one, to be able to build a strong parser for these sites from what the project already holds | `scrapers/reference/`, `services/scraper_ai_service.py` |
| **Series discovery from a homepage picks series, not list pages.** Links are grouped by address shape; list, filter and account pages are left out; the group with the most cover-wrapping links wins | On the saved pages it chose list pages on m.yueman1.cc (`/manhua/o/…`), category tabs on m.zymk.cn (`/book/N.html`) and volumes on mangaz.com | `services/parser_generation_service.py` |
| **mkzhan pages load again.** The image API now accepts chapter addresses without `.html` | The saved homepage shows chapters at `/<comic>/<chapter>/`; the parser only matched `/<comic>/<chapter>.html`, so no pages were found | `scrapers/presets.py` |
| **Per-site pacing (Scrapy's AutoThrottle).** Each site's wait moves halfway towards how long it takes to answer; a 429/503/403 doubles it (at least 5 s, at most 30 s). Never below the scraper's own minimum | A fixed pace ignores a site that is slowing down or pushing back, which is how a server gets blocked | `scrapers/throttle.py`, `scrapers/base_scraper.py` |
| Tests | Prove it | `tests/test_scraper_sidebar_images.py`, `tests/test_page_originals.py`, `tests/test_scraper_fetch_robustness.py`, `tests/test_rate_limiter_image_bucket.py`, `tests/test_reference_sites.py`, `tests/test_scraper_autothrottle.py`, `src/pages/NotificationsPage.test.jsx`, `src/pages/Admin/SeriesManagement.test.jsx`; `tests/test_page_mirroring.py` now covers the re-encoding path with `PAGE_KEEP_ORIGINALS=false` |
| Guide: troubleshooting rows, picture settings, checklist line; `backend_fastapi/README.md` picture section | Keep the docs true | `GUIDE.md` §3, §10, §11, `backend_fastapi/README.md` |

- **Database:** `20261018_cascade_series_children` from #48 (PostgreSQL only; lossless downgrade, see §2).
- **Settings:** new vault/`.env` key `PAGE_KEEP_ORIGINALS` (default `true`); `PAGE_MAX_WIDTH` default 2000 (an existing `.env` that says 1440 keeps 1440 until changed).
- **Check:** press *Rescrape & sync now* and type the name: the re-scrape starts. Re-scrape a wujinmh series and open a chapter: its pages, not covers; the stored files under `storage/pages/<series>/<chapter>/` are mostly `.jpg`/`.png` byte-identical to the source. Read a long chapter that isn't mirrored yet: no "Too many requests". Bookmark a series as a signed-in reader and run its check: the alert shows under *Notifications → Chapter Alerts & Issues*.
- **Undo:** `docker compose exec backend alembic downgrade 20261017_login_required_default_off`, then `git revert -m 1 <merge>`. Pictures stored as `.jpg`/`.png` in the meantime keep working only while this code is deployed; after a revert, re-mirror those series (Admin → Series → compress pictures) or set `PAGE_KEEP_ORIGINALS=false` and re-mirror before reverting.
- **Not done here:** chapters already stored with sidebar pictures stay wrong until re-scraped. Behind Caddy all visitors still share one rate-limit bucket (`plan.md` P0-2). jymk.cn has no built-in parser; it could not be looked at without network access. Sites behind a Cloudflare "checking your browser" page still need a browser-based fetcher, which this PR does not add.
---

### 2026-10-03 — Whole-site map and fix plan (documents only, nothing fixed)

PR #47, merge `7040e4d`. Branch `claude/site-map-and-fix-plan`.

The owner asked for the whole website to be mapped and every error, bug and path mismatch to be found, with a plan written **before** anything is fixed. This PR adds the two documents and changes no code, setting or database table. `plan.md` lists 41 findings (4 P0, 10 P1, 15 P2, 12 P3), eleven questions for the owner, and the order of work in nine pull requests; the owner decides what is fixed and when.

| Change | Why | Main files |
| --- | --- | --- |
| **`map.md` added**: how the site is put together (request path, middleware order, roles and powers, frontend routes, backend routers/services/tables, flows, config and deploy, tests and CI), a feature ledger, and appendices listing all 306 routes with who calls them, the 58 foreign keys with their delete rules, and the 44 background tasks | A fixing session can understand the whole site before it changes anything | `map.md` |
| **`plan.md` added**: findings with where/what/fix/proof, the owner's open questions with recommendations, the order of work (PR-1 to PR-9), the rules for the fixing session and the commands that reproduce each live finding | The owner wants a correct plan and to be asked before any fix | `plan.md` |

- **Database:** none (no migration).
- **Settings:** none.
- **Check:** open `map.md` and `plan.md` at the repository root. Nothing in the running site changes.
- **Undo:** `git revert -m 1 <merge>` (or delete the two files). Nothing else is affected.

---

### 2026-10-03 — A reader's read chapters follow them to a new phone

PR #45, merge `c66dc92`. Branch `claude/relaxed-wozniak-bsnxv1`.

The owner pointed out that a reader who signs in on a new phone gets their bookmarks but none of the dimmed (already read) chapters, because reading history lived only in the first browser. The owner's rule was changed for signed-in readers: the server now also keeps *which chapters they opened and when*. Nothing else about their reading is stored (no pages, scrolling or reading time). Guests are unchanged.

| Change | Why | Main files |
| --- | --- | --- |
| **Read chapters are kept on the account of a signed-in reader.** The browser stays the main copy (offline, guests). While signed in, each opened chapter is sent as it happens (`POST /history/read`); changes made while signed out or offline wait and go at the next sign-in. A browser that was never signed in sends everything it has once (a guest becoming a reader). After sending, the browser shows exactly the account's list, so the dimmed chapters and "where I stopped" appear on a new device. Chapters opened while that first sync ran are kept. A different account signing in on the same browser starts from its own list (the previous reader's history is not sent to it). Big libraries are sent in pieces of 2,000 | Owner's request | `src/components/HistorySync.jsx`, `src/utils/library.js`, `src/services/api.js`, `src/app.js` |
| **Clearing history reaches the account.** "Clear" and removing a series from History are sent to the account (waiting if signed out), so the cleared chapters do not come back. The Clear prompt says "on this device and your account" when signed in. A clear on one device reaches another device the next time it signs in or loads | Otherwise cleared chapters would return from the server | `src/components/BookmarkHistoryTab.jsx`, `src/utils/library.js` |
| **New endpoints** `POST /history/read` (one chapter) and `POST /history/sync` (changes in, the account's whole list out; up to 2,000 chapters per request). Sign-in required for readers' routes applies; guests get 401. Unknown chapters are ignored; a client time is never later than now and an older time never replaces a newer one. They use the existing `read_history` table and the existing account export and delete (history was already included) | The server side of the above | `api/routers/history.py`, `schemas/history.py`, `services/history_service.py`, `bootstrap/routers.py` |
| **The 90-day history clean-up is removed** (daily task `prune_history_task` and its beat entry): it would have deleted older read marks and re-lit chapters the reader had already read | The list must last as long as the account | `tasks/scraper_tasks.py`, `core/celery_app.py` |
| Side effects: the "active readers" counts in Admin (`site_admin.py`) and the 30-minute view de-duplication for signed-in readers (`catalogue_service.record_chapter_view`) read `read_history` and work for signed-in readers again, because rows are written again | They were reading a table nothing filled | none changed |
| Tests: upload and return, a new device gets the list, no duplicate rows, unknown chapters, older/future times, single chapter, clear one series / all, clear before the chapters sent with it, readers isolated, guests refused, size limit; in the page: guest sends nothing, first sign-in, new phone, live send and retry, clearing, upload failure keeps the list, different account, pieces, chapter opened mid-sync | Prove it | `tests/test_history_sync.py`, `src/components/HistorySync.test.jsx`, `tests/test_route_audit.py` |
| Wording: *My Library*, `CLAUDE.md` house rule, `GUIDE.md` §6.2 / troubleshooting / checklist, §1 and §5 of this file, roadmap item 41 | Keep the docs true | `CLAUDE.md`, `GUIDE.md`, `AUDIT_LOG.md`, `audit/ROADMAP.md` |

- **Database:** none. (Uses the existing `read_history` table. No unique constraint was added: two devices sending the same chapter at the same instant can leave two rows; reads treat them as one.)
- **Settings:** none. House rule in `CLAUDE.md` changed: signed-in readers' read chapters (ids and times) are kept on the server; guests' history stays in their browser.
- **Check:** sign in as a reader, open a chapter, then sign in as the same reader in a private window (or on a phone): that chapter is dimmed on the series page and *My Library → History* lists the series. `pytest backend_fastapi/tests/test_history_sync.py backend_fastapi/tests/test_route_audit.py`; `npx vitest run`.
- **Undo:** `git revert -m 1 <merge>`. Rows already in `read_history` stay (harmless; `DELETE FROM read_history` forgets them, or a reader's account deletion removes theirs). Without the clean-up task, old rows are no longer deleted after 90 days.

---

### 2026-10-03 — Linux test install: one image build, Docker install mix-ups, errors from a real run

PR #44, merge `ca12873`. Branch `claude/elegant-goldberg-1p4atv`.

The owner installed the site for testing on Ubuntu 26.04 in a VMware VM by following the guide and sent the two terminal logs. The site came up healthy in the end, but on the way: the first `docker compose up -d --build` failed, and the guide's Docker fallback broke the Docker install.

| Change | Why | Main files |
| --- | --- | --- |
| **The backend image is built once.** Only `backend` keeps `build:`; the migration job, the eight workers and beat run `manga-backend:latest` with `pull_policy: never` (a local image, never looked for on Docker Hub). Compose builds before it creates any container, so a plain `up -d` on a new machine still builds it first. The scale overlay's workers no longer build it either | Ten services built the same image in parallel; on Docker 29 (containerd image store) the exports collided: `failed to solve: image "docker.io/library/manga-backend:latest": already exists`. It happened on one fresh build and not the next | `docker-compose.yml`, `backend_fastapi/deployment/docker-compose.scale.yml` |
| **Docker install:** `permission denied … docker.sock` right after the installer is explained as "not in the group yet, reboot", not as a failed install; the `docker.io` + `docker-compose-v2` fallback is only for an installer that failed, with a warning that the two copies can't be mixed and a *Repair a mixed install* block (the commands that fixed the owner's VM) | The owner followed the fallback after the installer had worked; it removed `docker-ce` and stopped half-way on `trying to overwrite '/usr/libexec/docker/cli-plugins/docker-compose'` | `GUIDE.md` §1, `guide/INSTALL-LINUX.md` Step 1 |
| Troubleshooting rows for every message in the logs: the `already exists` build error (with the workaround for an old checkout), the `dpkg` overwrite, *"N not fully installed or removed"*, *"no such service: docker"* (two commands on one line), `(health: starting)` right after `up`, and `git pull` asking for a GitHub username. The Linux guide now says to reboot after `usermod`, checks `groups`, lists the 13 lines `docker compose ps` should show, and how to open the site in a VM from the main computer | Each one stopped or confused the owner | `GUIDE.md` §10 and §11, `guide/INSTALL-LINUX.md` |
| "How these commands were checked" now records the owner's real run (Ubuntu 26.04, Docker 29.8, Compose v5.6: build, all services healthy, migrations, Tesseract, the §4.1 update) | The image builds were marked "not run" | `GUIDE.md` |

- **Database:** none.
- **Settings:** none.
- **Check:** `docker compose config --format json` lists `build` only for `backend` and `web` (also with `-f docker-compose.small.yml` and with the scale overlay). On a machine without the image: `docker compose up -d --build` prints one `Image manga-backend:latest Built` and every service becomes `healthy`.
- **Undo:** `git revert -m 1 <merge>`. Nothing to migrate; the next `up -d --build` builds the image the old way.

---

### 2026-10-03 — New-chapter alerts for bookmarked series; logo and homepage heading owner-only; clean-up

PR #43, merge `485a1e5`. Branch `claude/funny-gauss-k12tkr` (restarted from `main` after #42 merged).

The owner asked that a new chapter reaches every reader who bookmarked the series, that the logo a visitor could "change" from the navbar be fixed, and for the follow-ups recommended after the bug test.

| Change | Why | Main files |
| --- | --- | --- |
| **New-chapter alerts reach readers who bookmarked the series.** A signed-in reader's bookmarks are now kept on their account as series ids (reading history still never leaves the browser): each change is sent as it happens, changes made while signed out wait and are sent at the next sign-in, and a browser's existing bookmarks are sent the first time its reader signs in. The account's list is then what the page shows, so bookmarks follow the reader to other devices. Guests' bookmarks stay in their browser | Owner's request; alerts went to server-side bookmarks that nothing created (BT-9) | `src/utils/library.js`, `src/components/BookmarkSync.jsx`, `src/app.js`, `src/components/MangaDetail.js`, `src/components/BookmarkHistoryTab.jsx` |
| Alerts come from **every** path that adds chapters to an existing series: the scheduled check and now also a scrape job (re-scrape, manual import of a known series). One helper; the chapter is written the way readers count ("Chapter 12", not "12.0"). A brand-new series alerts nobody | The scrape path never alerted anyone | `services/series_alerts.py`, `services/scheduled_checks_service.py`, `services/scraper_workflow_service.py` |
| **Logo and site name:** the pencil next to the logo (navbar and footer) showed to everyone, guests included, and an edit was kept in that visitor's browser, so they saw "their" logo. Now only the branding power sees the pencil, the change is saved on the server for everyone or not at all (with the reason when refused), and old browser copies are cleared | Owner's screenshot | `src/hooks/useBranding.js`, `src/components/Navbar.js`, `src/components/Footer.js`, `src/pages/Admin/AdminSettings.jsx` |
| **Homepage heading** is saved with the branding (`homepage_title`, `homepage_subtitle`), same for every visitor, branding power only (BT-12) | Admins' edits were visible only in their own browser | `api/routers/branding.py`, `schemas/branding.py`, `src/components/Homepage.js` |
| The homepage no longer starts with four made-up notices ("We are fixing server issue,, thanks"…) that showed until, or instead of, the real ones | Visitors saw fake notices | `src/components/Homepage.js` |
| Admin Settings → *Clear cache* said "✅ purged" when it failed | Wrong success message | `src/pages/Admin/AdminSettings.jsx` |
| **Readers looked signed out an hour after their last visit.** The access token lasts an hour and the refresh cookie two weeks, but on opening the site the page asked "who am I?" once and, on 401, showed the person as a guest without renewing. Now it renews once for someone who was signed in on this browser (guests never try), and forgets it when the renewal is refused | Found while testing live: everyone had to sign in again every hour | `src/contexts/AuthContext.js`, `src/services/api.js` |
| **Removed** the server's reading-history routes (`/history`, `/read_history`) and their browser client: nothing used them, and history stays in the browser by rule. The `read_history` table is left in place (no migration) | Clean-up (BT-10) | `api/routers/history.py`, `schemas/history.py` (deleted), `bootstrap/routers.py`, `src/services/api.js` |
| Tests: alerts reach only followers, the scrape path alerts and a new series doesn't, the heading saves and only the branding power may change it; bookmark sync (guest, first sign-in, live changes, failed upload keeps the list); navbar pencil hidden for guests and readers, saves on the server, shows why when refused; an expired access token is renewed on load, a guest never tries | Prove it | `tests/test_series_alerts.py`, `tests/test_branding_homepage_heading.py`, `src/components/BookmarkSync.test.jsx`, `src/components/Navbar.test.jsx`, `src/contexts/AuthContext.test.jsx` |

- **Database:** none. (Bookmarks use the existing `bookmarks` table; the heading lives in the branding setting.)
- **Settings:** none in `.env`. `CLAUDE.md` house rule on bookmarks updated: signed-in readers' bookmarked series ids are kept on the server for alerts; reading history never is.
- **Not done:** Tailwind 4 (roadmap item 40). Its upgrade tool needs the owner's permission to run here; the CI audit keeps ignoring only the `braces` advisory until then.
- **Check:** sign in as a reader, bookmark a series, then add a chapter (scheduled check or re-scrape): the reader's bell shows "Chapter N of … is available". In a private window there is no pencil next to the logo or on the homepage heading. `pytest backend_fastapi/tests/test_series_alerts.py backend_fastapi/tests/test_branding_homepage_heading.py`; `npx vitest run`.
- **Undo:** `git revert -m 1 <merge>`. Bookmarks already sent to accounts stay in the `bookmarks` table (harmless; delete rows to forget them).

---

### 2026-10-03 — Sign-in optional at the start; whole-site bug test; two clear guides

Merge commit `b101565` (PR #42). Branch `claude/funny-gauss-k12tkr`. Full report: `audit/bug-test-2026-10-03.md`.

The owner changed the sign-in rule: the site starts **open** (guests read and keep bookmarks in their browser) and the owner switches *Sign-in required* on later, once the Admins are in place. They also asked for a bug test of the whole website, guides that match the site (one for a local test without a domain, one for the live server), and the audit files brought up to date.

| Change | Why | Main files |
| --- | --- | --- |
| **"Sign-in required" starts off** (`LOGIN_REQUIRED_DEFAULT = False`, Site Functions default off). Migration `20261017_login_required_default_off` sets the column default to off and switches the existing site off. If the setting can't be read at all, guests are kept out (a database hiccup never opens a members-only site) | Owner's rule (2026-10-03) | `models/settings.py`, `dependencies/site_access.py`, `core/site_functions.py`, `migrations/versions/20261017_login_required_default_off.py` |
| Reader page showed **"Manga #7"** instead of the series title (the API sends `manga_title`) | Bug found live | `src/components/ChapterViewer.js` |
| Comments showed **every author as "Reader"** (the API sends `username`), never showed likes, showed removed comments as blank, and **hid posting errors** | Bug found live | `src/components/CommentSection.js` |
| The comments API sent each author's **masked e-mail** (`r***r@example.test`) to everyone, guests included, and decrypted an e-mail per comment | Privacy: e-mails are for the owner and Admins only | `services/comment_service.py`, `schemas/comments.py` |
| Guests saw the notification bell, which asked the server every 20 seconds and got 401 every time | Wasted requests on every guest tab | `src/components/Navbar.js` |
| An e-mail sign-in link was used twice (React runs the effect twice in development): the second call failed and threw the new session back to `/login` | Local testing (`npm run dev`) could not sign in by e-mail | `src/pages/MagicLinkConsume.js` |
| `favicon.ico`, `logo192.png`, `logo512.png` were missing: a 404 on every page, and the service worker's install failed, so offline caching never worked. The install now skips a missing file instead of failing | Bug found live | `public/`, `public/sw.js` |
| **Branding**: the navbar never read the site name/logo the owner saved, and the footer preferred the admin's own browser copy, so visitors saw "MangaWorld" in one place and "MGEKO.CC" (another site's name, with its Discord/X/Telegram/Reddit links) in the other. The saved branding now wins everywhere; the foreign defaults are gone | Visitors must see the owner's site | `src/components/Navbar.js`, `src/components/Footer.js`, `src/components/FooterEditor.js`, `src/pages/Admin/AdminSettings.jsx` |
| Guides: `guide/README.md` now starts with two paths, **A. local test (no domain)** and **B. live server**; new `guide/LIVE-SERVER.md` gives the live order and links to `GUIDE.md`; install guides and `GUIDE.md` §6.2, troubleshooting and checklist say sign-in starts off; the repository `README.md` points to the guides | Owner asked for a local and a live guide that match the site | `guide/`, `GUIDE.md`, `README.md` |
| Audit files: new bug-test report; roadmap item 29 (public browsing) closed by the owner's decision; old statements (2FA "off by default", the login gate, the pre-four-roles role design) marked as superseded; missing merge SHAs filled in | Keep the history true | `audit/`, `backend_fastapi/audit/`, `AUDIT_LOG.md` |
| **CI dependency audit**: a high advisory published on 2026-10-03 (GHSA-vfj7-8cjw-p6xm, `braces`, every version, no fix) turned the npm gate red on every branch. It reaches the site only through tailwindcss 3 at build time (`npm audit --omit=dev` is clean). The gate now reads `npm audit --json` and ignores just that advisory, with its reason, like the existing `--ignore-vuln` for pip-audit; any other high or critical advisory, or an audit that can't run, still fails | Keep the gate meaningful without a forced Tailwind 4 migration | `.github/workflows/ci.yml`, `.github/scripts/npm-audit-gate.mjs` |
| Tests: sign-in default off (no row, new row, Site Functions default), unreadable setting keeps guests out, migration 20261017 both ways; reader title, comment names/likes/errors, the sign-in link spent once under StrictMode | Prove it | `tests/test_login_required.py`, `tests/test_login_required_migration.py`, `tests/conftest.py`, `src/components/ChapterViewer.test.jsx`, `src/components/CommentSection.test.jsx`, `src/pages/MagicLinkConsume.test.jsx` |

- **Database:** `20261017_login_required_default_off` (added to §2; lossy to downgrade: the earlier value is not kept).
- **Settings:** none in `.env`. Site Functions → *Sign-in required* now starts off, and updating switches an existing site off. `cli_bootstrap functions-reset` also puts it back to off. `CLAUDE.md` house rule updated.
- **Behaviour changes to know:** after this update guests can read again until the owner switches the setting on. Comments no longer carry `user_email_masked`.
- **Check:** in a private window the home page, a series and a chapter open without signing in, and *Add to Bookmarks* works. Switch *Sign-in required* on in Admin → Site Functions: the same window now lands on the login page. `pytest backend_fastapi/tests/test_login_required.py backend_fastapi/tests/test_login_required_migration.py`; `npx vitest run`.
- **Undo:** switch *Sign-in required* on (no code change); or `git revert -m 1 <merge>` and `alembic downgrade 20261016_site_functions_and_tab_access` (the default goes back to on; existing rows stay as they are).

---

### 2026-10-03 — Site Functions, tab access, IP privacy, route audit and hardening

Merge commit `c2efe13` (PR #41). Branch `claude/nifty-fermat-53hmly`. Full report: `audit/site-functions-tab-access-and-hardening-2026-10-03.md`.

The owner asked for one page listing every main website function with an on/off switch (owner only), per-person admin tab access (owner only), the owner able to switch an Admin's powers off while the seat stays filled, visitors' IP addresses visible to the owner only, and a check that every route is connected properly.

| Change | Why | Main files |
| --- | --- | --- |
| **Admin → Site Functions**: 18 functions (sign-in required, maintenance, new accounts, three sign-in methods, comments, community, chapter reports, notifications, OCR, translation, ads, support links, sitemap/RSS, scraping, two IP-privacy switches), each enforced on the server (`FUNCTION_DISABLED`, 403) and hidden from the pages. **Owner only, no permission opens it.** The last sign-in method can't be switched off. `cli_bootstrap functions-reset` puts everything back | One place for the website's switches, for the owner alone | `core/site_functions.py`, `services/site_functions.py`, `dependencies/site_functions.py`, `api/routers/site_functions.py`, `bootstrap/routers.py`, `src/pages/Admin/SiteFunctions.jsx`, `src/hooks/useSiteFunctions.js`, `src/components/FunctionGate.jsx` |
| **Role Management → Tab access** (owner only, not delegable): which admin tabs each Admin / sub-admin sees, enforced in `has_permission` so the API refuses a hidden tab too; **Switch all powers off** keeps the title and seat. Seats: promotion resets, hand-over passes them on, leaving the tier clears them | A report moderator must not see the scraper or API tabs; an Admin can be parked without losing the seat | `core/admin_tabs.py`, `services/permissions_service.py`, `dependencies/auth.py`, `api/routers/roles_tabs.py`, `services/admin_roles.py`, `src/pages/Admin/TabAccessPanel.jsx` |
| **Visitors' IP addresses are for the owner only**: audit log (IP and operator e-mail), legacy admin-token list; the ad-click log line no longer prints an IP; *Record visitor IP addresses* can stop storing them | Hardening against IP exposure | `services/admin_service.py`, `utils/audit_logger.py`, `api/routers/ads.py`, `api/routers/admin.py` |
| **Route audit** and 12 fixes: System Health permission mismatch, `/admin/series` guard, User Database UI vs API, `/admin/users/all` open to any staff (and exposing the Google id), 11 staff-only routes now need their power, ad/support endpoints behind sign-in required, Admin Settings can no longer change maintenance/registration | "Check all the mismatches" | `tests/test_route_audit.py`, `tests/_support/route_table.py`, `tests/_support/frontend_scan.py`, `api/routers/admin.py`, `src/app.js`, `src/constants/adminFeatures.js` |
| Hardening guide for hiding the server's real IP, and catch-all nginx blocks for the bare IP | Reverse-IP lookups | `GUIDE.md` §8, `deployment/manga-site.conf` |

- **Database:** `20261016_site_functions_and_tab_access` (added to §2; **lossy** to downgrade).
- **Settings:** none in `.env`. Maintenance mode, new accounts and sign-in required move from Admin Settings to Site Functions (owner only). `CLAUDE.md` house rules updated.
- **Behaviour changes to know:** the User Database tab follows the `view_user_list` permission (an Admin sees it); System Health follows `view_system_health` (sub-admins don't have it by default, so they no longer see a tile that errored); a person with "powers off" gets 403 on every admin route.
- **Not run here:** a real Google sign-in, PostgreSQL locally (CI runs it), a browser, nginx syntax.
- **Check:** `GUIDE.md` §6.4, §6.5 and the table in the report (§7). `pytest backend_fastapi/tests/test_site_functions.py backend_fastapi/tests/test_tab_access.py backend_fastapi/tests/test_ip_privacy.py backend_fastapi/tests/test_route_audit.py`.
- **Undo:** Site Functions and Tab access can be reset in the app or with `cli_bootstrap functions-reset`; or `git revert` and `alembic downgrade 20261015_login_required_default_on` (drops the switches and tab lists).

---

### 2026-10-02 — Sign-in first: nobody sees the site before logging in

Merge commit `c2efe13` (PR #41). Branch `claude/nifty-fermat-53hmly` (restarted from `main` after #40 merged). **Reversed on 2026-10-03:** sign-in required starts off again (see the entry above).

The owner wants every visitor to log in first (Google, Microsoft or an e-mail magic link), with the login page in front even for a casual look, so there is less scraping and less load. The "Sign-in required" switch already existed but started **off**.

| Change | Why | Main files |
| --- | --- | --- |
| **"Sign-in required" is on by default** (`LOGIN_REQUIRED_DEFAULT`): a new settings row starts on, and with no row yet or an unreadable column the server answers guests with `LOGIN_REQUIRED` (fail closed) | Owner: login first, less scraping and load | `models/settings.py`, `dependencies/site_access.py` |
| **Migration `20261015_login_required_default_on`** sets the column default to on and **switches the existing site on** | Existing sites would otherwise stay open until someone found the switch | `migrations/versions/20261015_login_required_default_on.py` |
| **The page fails closed too**: a guest sees the site only if the server says plainly that the switch is off; if the answer can't be fetched they get the login page | The old check let guests through on any error | `src/components/AuthGuard.js` |
| The Admin Settings card explains the default; the owner can still turn it off | The owner stays in control of the site | `src/pages/Admin/AdminSettings.jsx` |
| Tests: default-on with no row, new row on, sign-in and admin stay reachable, the migration both ways, the guard when the setting can't be read. The shared test database runs with guests allowed (fixture `members_only_default` tests the real default) | Prove it | `tests/conftest.py`, `tests/test_login_required.py`, `tests/test_login_required_migration.py`, `src/components/AuthGuard.test.jsx` |

- **Not changed:** the reader sign-in methods stay Google, Microsoft and magic link. **No reader passwords** (owner's rule; an e-mail-and-password option was not added). Sign-in, sign-up, config, health and the admin area are never behind the switch. The static site files (JavaScript, CSS) stay public: they hold no content.
- **Side effect:** while it is on, guests (including search-engine crawlers) see only the login page and `sitemap.xml` / `rss.xml` answer guests with a sign-in error. Turn the switch off to be indexed.
- **Database:** `20261015_login_required_default_on` (added to §2).
- **Settings:** none in `.env`. Admin Settings → *Sign-in required* now starts on.
- **Check:** open the site in a private window: you land on the login page. Sign in and read. `GET /api/v1/manga/` as a guest answers 401 `LOGIN_REQUIRED`. `pytest backend_fastapi/tests/test_login_required.py backend_fastapi/tests/test_login_required_migration.py`.
- **Undo:** Admin Settings → *Sign-in required* off (no code change); or `git revert -m 1 <merge>` and `alembic downgrade 20261014_four_roles` (the default goes back to off; existing rows stay as they are).

---

### 2026-10-02 — Owner sign-in clean-up: guide order, leftovers of the admin password

Merge commit `7a53a77` (PR #40). Branch `claude/nifty-fermat-53hmly` (restarted from `main` after #39 merged). Follow-up to PR #39; documentation and comments only, no behaviour change.

The owner asked that everything that depended on the admin password hash works with the new Google sign-in, `GUIDE.md` included. A search of the whole repository (code, tests, scripts, compose and deployment files, CI, guides) found no remaining use of `MAIN_ADMIN_PASSWORD_HASH`, `/admin-login` or the password helpers. The leftovers were these:

| Change | Why | Main files |
| --- | --- | --- |
| §3.5 no longer lists Google sign-in as optional: it is needed first, in `.env`, because the vault opens only for the owner | A reader following "leave blank to disable" could never become the owner | `GUIDE.md` §3.5 |
| The "short version" (trial) and §8 Step 3 (production) now say the owner line and the Google client go in `.env` before the first sign-in, with the real domain in the redirect address | Both paths skipped the two things the new flow needs | `GUIDE.md` §0, §8 |
| Removed the last mention of `MAIN_ADMIN_PASSWORD_HASH` from the vault key notes and the "never in the vault" test list | Stale after #39 | `app/vault_keys.py`, `tests/test_secret_vault.py` |
| Filled in the merge SHA of PR #39 | Repository rule | `AUDIT_LOG.md` |

- **Checked and left as is:** `docker-compose.yml` still passes `.env` to every container (so `MAIN_ADMIN_EMAIL_HASH` and the Google client reach the backend); a stale `MAIN_ADMIN_PASSWORD_HASH` line in an old `.env` is ignored (settings allow extra keys, tested); `system/state` reports the owner by `is_main_admin`, unchanged; `system_settings.admin_setup_password_used` stays unused in the database.
- **Database:** none. **Settings:** none.
- **Check:** `GUIDE.md` §3.5, §0 and §8 Step 3 read in order; `pytest backend_fastapi/tests/test_secret_vault.py`.
- **Undo:** `git revert -m 1 <merge>`. Nothing else changed.

---

### 2026-10-02 — PR #39: owner signs in with Google; one-time admin password and `/admin-login` removed

Merge `d7074e8`. Commit `386aa6c`.

The owner asked for a simpler first login: put the Google client in `.env`, keep only a hash of the owner's e-mail there, and become the owner by signing in with Google using that e-mail. The one-time password and its page caused lock-out friction (a used password, a browser closed mid-way, a magic-link request that diverted to the page).

| Change | Why | Main files |
| --- | --- | --- |
| **The first verified Google sign-in with the e-mail matching `MAIN_ADMIN_EMAIL_HASH` makes the owner**, only while the site has no owner. Google must report the address verified. Closed registration does not block it. Ownership never passes: a changed hash later promotes nobody. Audited as `OWNER_SEAT_CLAIMED` | Google plus the e-mail match is the verification; nothing one-time to burn, so no lock-out | `core/admin_identity.py`, `services/oauth_service.py` |
| **Removed** `/admin-login` (page and `/api/v1/auth/admin/*`), `MAIN_ADMIN_PASSWORD_HASH`, the "used password" marker logic, and the magic-link diversion (`message: "admin_setup"`). A magic link or Microsoft sign-in with the owner's e-mail is now an ordinary sign-in and never promotes | Owner: no extra pages, nothing that can divert a normal login | `api/routers/admin_login.py` (deleted), `api/routers/auth.py`, `src/pages/AdminLogin.jsx` (deleted), `src/app.js`, `src/components/Login.js` |
| **The owner enrols the authenticator from Admin**, right after the first Google sign-in (it used to be possible only on the one-time page). Until enrolled, every admin feature answers `enrolment_required`; it applies whenever `MAIN_ADMIN_EMAIL_HASH` is set. The owner can't turn it off in the page, and `reset-2fa` on the server removes a lost one | The one-time page was the only place to enrol, so it had to go somewhere | `api/routers/admin_2fa.py`, `dependencies/auth.py`, `src/components/AdminSecondFactor.jsx`, `src/pages/Admin/AdminSecurity.jsx` |
| `make_admin_hash.py` and `cli_bootstrap admin-hashes` print/check only the e-mail line; `admin-status` reports the hash, Google sign-in and whether the owner seat is claimed; `reset-2fa` tells you to sign in with Google | Match the new flow | `scripts/make_admin_hash.py`, `scripts/cli_bootstrap.py` |
| Google client ID/secret start in `.env` (the vault can only be opened by the owner); the owner may move them into the vault afterwards. §1 and the guides say so | Chicken-and-egg: the owner needs Google to reach the vault | `.env.example`, `GUIDE.md`, `GOOGLE_LOGIN_SETUP.md`, `guide/*` |

- **Database:** none. `system_settings.admin_setup_password_used` (from `20261011_admin_password_single_use`) is now unused and left in place; a later migration can drop it.
- **Settings:** `.env`: `MAIN_ADMIN_PASSWORD_HASH` removed (ignored if still present); `MAIN_ADMIN_EMAIL_HASH` and `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` are what the owner needs. Already-claimed sites need no change: the owner keeps the seat and their authenticator.
- **Known limit:** the owner needs an authenticator only while `MAIN_ADMIN_EMAIL_HASH` is set (before, a marker in the database kept it required even after the hash was deleted). An owner who already enrolled is always asked for the code. Keep the hash line in `.env`.
- **Check:** `cli_bootstrap admin-status` says `Owner: not claimed yet` → sign in with Google using the owner e-mail → it says `Owner: claimed`; **Admin** asks for the authenticator; `/admin-login` shows "Page not found". `pytest backend_fastapi/tests/test_owner_google_sign_in.py backend_fastapi/tests/test_admin_second_factor.py backend_fastapi/tests/test_cli_bootstrap_script.py`.
- **Undo:** `git revert -m 1 <merge>`, then `docker compose up -d --build --force-recreate`. No migration to undo. After a revert the one-time page needs a new password hash (`make_admin_hash.py`).

---

### 2026-10-02 — GUIDE.md: commands that match the machine

Documentation only. Branch `claude/guide-fewer-mismatches`. Merge commit `306aa79` (PR #38).

Written from a real terminal log of an Ubuntu 26.04 machine (Python 3.14, no `python3.11`, `pip` or `nvm`) where many guide commands "didn't match".

| Change | Why | Main files |
| --- | --- | --- |
| New **"Read this first"** section: copy one block at a time; no `<placeholder>` in any runnable block (a block that needs your value sets it on its first line); be in the project folder; run the site one way only; the **real** service, container, volume, database-user and in-container path names; "You should see" lines; host Python/Node/pip are not needed for Docker | The log shows `cd: /path/to/manga-website`, `no configuration file provided`, `/app/scripts/…` (real: `/app/backend_fastapi/scripts/`), service `migrate` (real: `manga-stack-migrate`), `pg_dumpall -U postgres` (real user: `manga`) | `GUIDE.md` |
| **§5 rewritten as developer mode**, with a stop sign and a separate `.env.dev`; Node via `nvm` and Python 3.11 via `uv` (the route that worked in the log); Docker app stopped first; steps to go back | Developer mode was run after Docker with the Docker `.env`: `could not translate host name "db"`, Redis name errors, `Address already in use` on 8000 | `GUIDE.md` §5 |
| **§3.1 no longer shows hand-made secrets**; **§3.6 adds a password check** (prints `1` and `3`) | A hand edit of `POSTGRES_PASSWORD`/`REDIS_PASSWORD` leaves the old password in the URL lines (checked: the by-hand route prints `0` and `0`, `make_env.py` prints `1` and `3`) | `GUIDE.md` §3 |
| **§12.5 Start again from zero**: scoped `docker compose down --volumes --rmi all`, checks, re-clone, the case where the folder is already deleted (remove by project label), the browser still showing the site, restoring `~/.bashrc` | The user wiped `~/Desktop` (taking the project folder with it, so the containers kept running), then needed a clean redo | `GUIDE.md` §12.5 |
| Troubleshooting starts with the exact messages from the log | Look-up by the text on screen | `GUIDE.md` §10 |
| Rollback, domain move, `reset-2fa` and `login-link` blocks use named variables (`OLD_VERSION=`, `DB_VERSION=`, `BACKUP_STAMP=`, `NEW_DOMAIN=`, `OWNER_EMAIL=`) instead of `<…>` | Placeholders pasted literally fail | `GUIDE.md` §6, §8.1, §12.3 |
| §1: Docker fallback (`docker.io` + `docker-compose-v2`) for a brand-new Ubuntu release; `openssl` no longer installed (not used) | New releases may not be in Docker's installer yet | `GUIDE.md` §1 |

- **Database:** none.
- **Settings:** none. Developer mode makes an untracked `.env.dev` (added to `.git/info/exclude`) and `docker-compose.override.yml`.
- **Check:** every block of §3, §5 (Steps 3–6), §8.1 and the checks of §12.5 was extracted from the guide and run on Ubuntu 24.04 against a real PostgreSQL 16 and Redis: `make_env.py` (also on Python 3.13), the password check, the `.env.dev` copy, venv + `pip install` + all migrations to `20261014_four_roles` + the seed, API `/healthz`, one worker on nine queues, beat, `npm ci` + `npm run dev` (gateway `/api/v1/version`), `admin-status` through `.env.dev`, `caddy validate` of the variable form; `docker compose down` and `ps` flags exist; every link and `GUIDE.md#…` anchor resolves; every shell block passes `bash -n`; no `<…>` placeholder is left in a runnable block.
- **Not run:** Ubuntu 26.04 itself (not available in the sandbox; the `nvm` and `uv` steps are the commands that worked in the reported 26.04 log), the Docker image builds and `docker compose up/down` (no Docker daemon), and the removal-by-label block (syntax only).
- **Undo:** `git revert -m 1 <merge>`. Nothing else changed.

### 2026-10-02 — GUIDE.md rewritten for Ubuntu, commands checked

Documentation only. Merge commit `178bb3d` (PR #37).

| Change | Why | Main files |
| --- | --- | --- |
| Install steps are Ubuntu 22.04/24.04 commands end to end: Docker group and Compose version check, optional Docker log cap, swap file for small servers, `ufw`, Caddy, reboot test, `ss`/`journalctl`/`getent` for diagnosis | The old guide mixed in Windows/macOS and had gaps on a stock Ubuntu server | `GUIDE.md` |
| `.env`: `make_env.py` is the main way (then `chmod 600 .env`); one `sed` block sets the domain lines and production mode | The generated `.env` is world-readable; the old hand-edit table was easy to get wrong | `GUIDE.md` §3 |
| **Non-Docker setup no longer uses `set -a; source .env`.** It uses `dotenv -f .env run -- <command>`. Python and Node install steps now match each Ubuntu release (`python3.11` is not in 24.04; `pip` refuses system installs there) | `source .env` ran a line as a command (`magic: command not found`) and turned `CORS_ALLOWED_ORIGINS=["…"]` into `[http://…]`, which breaks CORS; and the API's settings loader looks for `backend_fastapi/.env`, not the repo's `.env`, so without the wrapper it stops with *Field required* | `GUIDE.md` §5 |
| **Server file `docker-compose.override.yml`** (created by the admin, not tracked): sets `APP_ENV=production` for all services and binds ports 8000/8080 to `127.0.0.1`. Replaces "edit `APP_ENV` in `docker-compose.yml`" | Docker publishes ports on every interface and bypasses `ufw`, so the API was open to the internet; editing the tracked file made `git pull` conflict | `GUIDE.md` §4, §8, §10 |
| Small profile made permanent with `COMPOSE_FILE=…` in `.env`; restart/stop commands ask Compose for the service list, so they work for both profiles | The old restart command named services the small profile switches off | `GUIDE.md` §4.1, §4.2, §12.3 |
| Backups section matches the Docker setup: `pg_dump` through the `db` container, `tar` through `backend`, a cron script, restore of the pictures with `--entrypoint tar` | `backup_postgres.sh` / `backup_storage.sh` expect a host-reachable database and `/app/storage`, neither true in Docker | `GUIDE.md` §9, §12 |
| Troubleshooting rows for the Ubuntu cases above, a warning about `setup-server.sh` (turns off SSH password and root login), stray checklist line fixed | Found while checking the commands | `GUIDE.md` §8, §10, §11 |

- **Database:** none.
- **Settings:** none required. Optional, per server: a `COMPOSE_FILE` line in `.env` and an untracked `docker-compose.override.yml`. Section 3.3's `sed` writes `APP_ENV=production` into `.env`.
- **Check:** each command block in the guide was extracted and run on Ubuntu 24.04 where possible: `make_env.py`, the domain `sed` (then the real settings loaded under `APP_ENV=production`), both Compose files and the override with `docker compose config` (Compose v5), all migrations to `20261014_four_roles` on PostgreSQL 16, API `/healthz`, one worker on all nine queues, beat, `npm ci` + `npm run dev` (gateway proxies `/api/v1/version`), the admin hash tool (`--write`, `--check`, then `admin-status` flips to OPEN), `apt` package names, `caddy validate` on both Caddyfile forms, the Python 3.12 install and API start. Every internal link and every `GUIDE.md#…` anchor used by `guide/` still resolves; every shell block passes `bash -n`.
- **Undo:** `git revert -m 1 <merge>`. Nothing else changed. A server that already made `docker-compose.override.yml` keeps working (Compose still reads it).

### 2026-10-02 — Four-role audit: pages and "delete all" follow the owner's switches

Branch `claude/eager-noether-0jg9xq`. Merge commit `7303c34` (PR #36).

| Change | Why | Main files |
| --- | --- | --- |
| "Delete all manga" no longer refuses an Admin the owner switched `purge_site_data` on for (it was a second, hidden owner-only check) | The toggle must mean what it says | `api/routers/site_admin.py` |
| System Health cache/purge buttons, Series Management (Scraper AI key, Custom Parser) follow the power toggles instead of "owner only", so an Admin the owner left them on for can use them | Pages hid features the server allowed | `src/pages/Admin/Health.jsx`, `src/pages/Admin/SeriesManagement.jsx` |
| User Database shows Owner / Admin / Sub-admin / User and never offers "Make Sub-Admin" on an Admin or the owner | The page only knew the old three roles | `src/pages/Admin/UserDatabase.jsx` |

- **Database:** none.
- **Settings:** none.
- **Check:** as an Admin with `purge_site_data` on, Health → "Purge Image CDN Buffers" works; with it off the button is disabled. `pytest backend_fastapi/tests/test_four_roles.py`.
- **Undo:** `git revert -m 1 <merge>`; nothing else changed.

### 2026-10-02 — Four roles: owner, Admin, sub-admin, user

Branch `claude/eager-noether-0jg9xq`. Merge commit `27eda94` (PR #35).

| Change | Why | Main files |
| --- | --- | --- |
| **Admin tier** (max two) replaces "deputies": almost every power by default except Admin Settings, cache and delete-all; only the owner switches an Admin's powers; Admins change sub-admins and users only and see only their e-mail | Owner wants a clear chain of command: owner > Admin > sub-admin > user | `core/permissions.py`, `services/permissions_service.py`, `services/admin_service.py`, `api/routers/admin.py`, `dependencies/auth.py` |
| **Seats**: Admins share 50 sub-admin seats (25 each, owner adjusts); **ceiling**: powers no sub-admin may hold; custom roles owner-only | Owner limits how many staff each Admin makes and what they can get | `services/admin_roles.py`, `api/routers/roles_admins.py` |
| **Succession lines**: each Admin names two sub-admins; idle (default 60 days, owner's switch) or owner hand-over gives the seat on as it is; old Admin becomes a user | Replaces "most active sub-admin inherits" | `services/admin_succession.py`, `services/admin_roles.py` |
| Community moderation (block, unblock, time out, remove a comment) follows the chain of command: only people of a lower tier | Same hierarchy everywhere | `services/moderation_service.py`, `services/comment_service.py` |
| Login: the owner's e-mail (matching `MAIN_ADMIN_EMAIL_HASH`) sent from the login page goes to `/admin-login` while that page is open; never once the password is used | Owner wants the first sign-in to flow from the normal login page | `api/routers/auth.py`, `src/components/Login.js` |
| Role Management page: Admins panel, ceiling, succession | UI for the above | `src/pages/Admin/RoleManagement.jsx`, `src/services/api.js`, `src/contexts/AuthContext.js` |

- **Database:** `20261014_four_roles` (added to §2). Existing deputies become plain sub-admins; the owner re-promotes them as Admins.
- **Settings:** none in `.env`. The owner's e-mail stays the admin identity in `.env`, never in code.
- **Check:** Role Management as owner: make an Admin (code), set seats, tick a ceiling, name a line; as the Admin: toggles for sub-admins work, another Admin's are refused. `pytest backend_fastapi/tests/test_four_roles.py`.
- **Undo:** `alembic downgrade 20261013_admin_succession` before deploying reverted code (Admins become sub-admins), then `git revert -m 1 <merge>`.

### 2026-10-02 — PR #34: Storage & Backups, Geolock, deputies and automatic succession

Branch `claude/great-faraday-nh2dwx`. Commits `c96b98e`, `2da5e86`, `c608f69` and the follow-ups. Merge commit `217f255`.

| Change | Why | Main files |
| --- | --- | --- |
| **Storage & Backups tab** (Admin, main admin only). One `.zip` per backup: database (`pg_dump`/SQLite), pictures and other uploads (optional), and a manifest. Weekly on a chosen day and hour (UTC), newest *N* kept, "Back up now", download, upload a backup made elsewhere, restore (types RESTORE; a database safety copy is made first). A backup password encrypts archives (`.zip.enc`, AES-256-GCM). Connect any S3-compatible storage (R2, B2, Wasabi, MinIO): tested with a write/read/delete before it is saved; every new backup is copied there and pruned there too; files in the storage can be brought back to the server. One job at a time, in the maintenance worker | Owner asked for backups made, kept, downloaded and restored from the website, with storage that plugs in and out | `app/services/backup_service.py`, `backup_crypto.py`, `s3_storage.py`, `app/api/routers/backups_admin.py`, `app/tasks/backup_tasks.py`, `src/pages/Admin/StorageBackups.jsx` |
| **Geolock tab** (Admin, main admin only). Tick countries that can't open the site; they get a 451 and a "not available in your country" page. Country from a GeoIP database on the server (free DB-IP Lite, downloaded from the tab, or an uploaded MaxMind `.mmdb`) or from Cloudflare's `CF-IPCountry` header. Saving a list that blocks the admin's own country asks first; `cli_bootstrap geolock-off` undoes a lockout | Owner asked to block chosen countries | `app/services/geolock.py`, `app/bootstrap/geolock_middleware.py`, `app/api/routers/geolock_admin.py`, `src/pages/Admin/Geolock.jsx`, `src/components/RegionGate.jsx` |
| **Deputies.** Every admin power is now a Role Management toggle. Site-owner powers (Secret Vault, Admin Settings, cache, purge, API Management, Scraper AI, Role Management, branding, donations, backups, geolock, e-mail reveal) are given only by the owner with their authenticator code, to at most two sub-admins who have an authenticator and enter a code to use them. Sub-admins can't pass them on, edit themselves, or change/reset/demote a deputy; demotion strips them. The owner's pages open to a deputy holding the matching power (routes and hub tiles) | Owner wants the site to keep running if they are away, without anyone being able to take it over | `app/core/permissions.py`, `app/services/permissions_service.py`, `app/dependencies/powers.py`, `app/services/admin_service.py`, 100 routes moved from "main admin" to `require_power(...)`, `src/pages/Admin/RoleManagement.jsx`, `src/app.js`, `src/constants/adminFeatures.js` |
| **Automatic succession** (owner only, off by default, owner's code to change). A deputy idle longer than the chosen days (30-365, default 60) becomes a user; the most active eligible sub-admin (admin 30+ days, active 20 of the last 30 days, admin work on 10 of them, authenticator) inherits exactly their site-owner powers. Activity is recorded by the server once a day. Switching it on never demotes anyone at once. Each change is audited and sent to the owner | Owner asked for idle deputies to be replaced automatically | `app/services/admin_succession.py`, `app/api/routers/roles_succession.py`, `app/tasks/roles_tasks.py` |
| nginx: backup and GeoIP uploads/downloads have no size cap or buffering (only those paths); the API's 5 s timeout doesn't apply to them | Archives can be many GB | `deployment/nginx/site.conf`, `deployment/manga-site.conf`, `app/bootstrap/timeout.py` |

- **Database:** `20261013_admin_succession` (added to §2). Backup and Geolock settings live in the Secret Vault; the backup list is read from the backup folder, so it survives a restore.
- **Settings:** new vault keys `BACKUP_SCHEDULE_ENABLED`, `BACKUP_WEEKDAY`, `BACKUP_HOUR_UTC`, `BACKUP_KEEP`, `BACKUP_INCLUDE_IMAGES`, `BACKUP_PASSWORD`, `BACKUP_S3_*`, `GEOLOCK_ENABLED`, `GEOLOCK_BLOCKED_COUNTRIES`, `GEOLOCK_COUNTRY_SOURCE`, all set from the two tabs. Optional `.env` paths `STORAGE_ROOT`, `BACKUP_DIR`, `GEOIP_DATABASE_PATH`. New dependency `maxminddb` (rebuild the backend image). Weekly backup is **on by default** (Sunday 03:00 UTC, keep 2, with pictures); it refuses to run when the disk lacks room.
- **Check:** Admin → Storage & Backups → Back up now; the archive appears, downloads and opens as a zip (unless a password is set). Admin → Geolock → Download free database, tick a country, save; `curl -H "CF-IPCountry: JP"` only matters in Cloudflare mode.
- **Undo:** `alembic downgrade 20261012_overlay_text_scale` (activity history lost), then `git revert` the merge commit and rebuild; reverting makes every site-owner power main-admin only again (stored grants stay in the table but do nothing). Backups already made stay in `<storage>/backups` (and the storage); the vault keys can be removed in Secret Vault. If a Geolock change locked you out: `cli_bootstrap geolock-off`.

### 2026-10-02 — PR #33: all 13 audit findings fixed; bubble-shaped translations, colour pickers, 1-100 text size

Merge `00390cd`. Commits `4a92b2e` … `773ab2f` (see below).

| Change | Why | Main files |
| --- | --- | --- |
| **F-89 (critical)** Public `GET /config/providers` (all aliases) now returns only which services exist and the built-in OCR flags. Every provider payload, the main admin's included, lists custom **header names only**, never values | Anyone could read a provider's header key, endpoint and key ending without signing in | `app/services/provider_registry.py`, `app/api/routers/config.py` (`55464cd`) |
| **F-91 (high)** Sub-admins see only their own audit-log rows (count and pages too) unless granted `view_full_audit`; 403 without `view_scope_audit` | Default sub-admins read the main admin's full trail with IPs | `app/api/routers/admin.py` (`275cde2`) |
| **F-93 (high)** Page OCR + translation runs in its own small thread pool (`PAGE_PROCESSING_CONCURRENCY`, default 2), not on the API worker's event loop | One page translation froze that API worker for everyone | `app/api/routers/processing.py`, `app/utils/bounded_threadpool.py`, `routers/ocr.py` (`40741cb`) |
| **F-94** Database work in 40 `async` handlers moved to the DB thread pool (or the handler made a plain `def`); an AST test keeps new ones out | Each query stalled the event loop | `app/api/routers/*` (`bd21281`) |
| **F-92** Library batch checks rights for the whole list in one pass; a taken-down series no longer fails the whole list with 451 | 12 queries for 3 series, ~400 for 200 | `app/services/content_rights.py`, `routers/manga.py` (`2476f9f`) |
| **F-96** `docker-compose.small.yml` for ~1 GB servers (2 workers instead of 8, solo pools, small DB pools, Postgres/Redis caps); API and background workers recycle after N requests/jobs or 400 MB; Redis eviction never touches queues | ~2.5 GB RAM at idle, no recycling | `docker-compose*.yml`, `deployment/gunicorn.conf.py`, `app/core/celery_app.py`, `scripts/start_celery_worker.sh` (`f900f43`) |
| **F-95** All 13 admin screens load on demand: reader bundle 680 kB → 449 kB | Every visitor downloaded the admin console | `src/app.js` (`2f17637`) |
| **F-97** Admin hub tiles match the routes: a sub-admin sees Health / Chapter reports only with the permission that opens them, and never main-admin tiles | Tiles bounced sub-admins back | `src/constants/adminFeatures.js`, `src/components/AuthGuard.js`, `src/app.js` (`a5375f9`) |
| **F-86, F-87, F-90** Background cache refreshes are kept alive and logged on failure; `ALGORITHM` must be HS256/384/512; `/system/stats` is main-admin only | Lost refreshes; unsafe JWT algorithms; metrics public | `app/utils/swr_cache.py`, `app/core/settings.py`, `routers/system_stats.py` (`4a92b2e`) |
| **Translation fills the bubble's own shape.** The server finds the closed speech bubble around each text (round, square or any outline) and the reader fills that shape and sets the text inside it. Text drawn straight on the art (no plain fill or no closed outline) keeps its own box and spot. Readers can switch it off (*Match the bubble's shape*) | Owner asked for translations drawn inside the exact bubble | `app/services/bubble_shape.py`, `app/services/ocr_normalize.py`, `src/components/OverlayBox.js`, `src/components/ReaderOverlay.js` (`5ff8754`) |
| **Colour pickers and outline colour.** Text, outline and box colours each get a picker: a square from white/grey to full colour to black, and a rainbow bar under it (plus hex, black and white buttons, keyboard) | Only black/white text was practical | `src/components/ColorPicker.js`, `src/settings/ReadingSettings.tsx` (`f655ab5`) |
| **Text size 1-100 in half steps** (100 = 70 px, was 10-40 px), in Settings and in the reader's quick control (slider and +/-; resizes at once, saved after a pause). Only the translated text on manga pages changes | Owner asked for bigger and finer sizes | `src/utils/overlayText.js`, `src/components/OverlayScaleControl.js`, `app/models/processing_settings.py` (`f655ab5`) |

- **Database:** `20261012_overlay_text_scale` (added to §2; downgrade is lossy for sizes above 40 px).
- **Settings:** new optional `.env` tuning knobs `PAGE_PROCESSING_CONCURRENCY`, `GUNICORN_MAX_REQUESTS`, `GUNICORN_MAX_REQUESTS_JITTER`, `CELERY_MAX_TASKS_PER_CHILD`, `CELERY_MAX_MEMORY_PER_CHILD_KB` (documented in `.env.example`). They sit beside `GUNICORN_WORKERS`/`CELERY_CONCURRENCY` because Gunicorn and Celery read them when the process starts, before the Secret Vault is loaded; none is a secret and all have defaults. New reader settings `overlay_outline_color`, `overlay_match_bubble`. API: `/config/providers` is smaller; audit-log endpoints are scoped for sub-admins.
- **Action after deploying:** rotate any provider key that was saved in a **custom header** (F-89).
- **Check:** `pytest backend_fastapi/tests/test_provider_secrets_not_public.py test_audit_log_search.py test_bubble_shape.py test_processing_settings.py test_overlay_text_scale_migration.py`; anonymous `curl https://<site>/api/v1/config/providers` shows only `availableServices` and `local`; open a chapter with translation on: round and square bubbles are filled in their own shape. Pages translated before this update keep plain boxes until their cached result is cleared (Admin Settings → cache) or re-processed.
- **Undo:** `alembic downgrade 20261011_admin_password_single_use` first (lossy for sizes above 40 px), then `git revert` the merge commit. Reverting brings the public provider details back: don't, without keeping the F-89 change.

### 2026-10-02 — PR #32: Test: Admin Settings destructive actions are main-admin only

PR #32, merge `3b91c35`. Commits `19c2d3b`, `77a197a`.

- **What:** a regression test proving a sub-admin holding every grantable toggle gets 403 on clear site cache, delete all manga, purge / mirror all images, cache clear / refresh / priority and saving settings, and that nothing is deleted. `CLAUDE.md` house rule names Admin Settings' cache purge and delete-all actions explicitly.
- **Why:** the owner asked that only the main admin can reach these destructive actions; the server already enforced it, now a test keeps it that way.
- **Main files:** `backend_fastapi/tests/test_api_management_main_admin_only.py`, `CLAUDE.md`, `AUDIT_LOG.md`.
- **Database / settings:** none.
- **Check:** `pytest backend_fastapi/tests/test_api_management_main_admin_only.py`.
- **Undo:** `git revert` the merge commit. Test and documentation only.

### 2026-10-02 — PR #31: API Management, Admin Settings and Role Management main-admin only; full audit

Merge `8370d34`. Commits `1f69fe9`, `af90062`.

| Change | Why | Main files |
| --- | --- | --- |
| **Sub-admins can no longer read Admin Settings** (`GET /admin/settings`), the OCR provider check (`/admin/validate-ocr-providers`), the unused `/config` snapshot, or trigger `/admin/database/alembic-status`; all are main-admin only. The session policy is readable only by whoever may change it (`set_session_policy`) | Owner's rule; audit finding F-88 showed every sub-admin could read them | `app/api/routers/admin.py`, `app/api/routers/management.py` |
| **API Management toggles are main-admin only**: `view_providers`, `configure_ocr`, `configure_translation`, `configure_ai`, `set_provider_priority` join `MAIN_ADMIN_ONLY` (no Role Management toggle, stored grants ignored, presets skip them; the *Operations* preset no longer lists them) | They guarded nothing (API Management was already main-admin only in code) but showed sub-admins as holding it (F-98) | `app/core/permissions.py` |
| **Role Management is main-admin only**: the permission catalogue and presets are no longer readable by sub-admins; `promote_secondary` / `demote_secondary` join `MAIN_ADMIN_ONLY`; `/admin/promote/{id}`, `/demote/{id}` and their `-by-email` forms require the main admin at the route (the service already refused sub-admins promoting; now a sub-admin can't change any role, not even an ordinary user's). Sub-admins keep `GET /admin/permissions/me` (their own toggles drive their admin tiles) | Owner's rule | `app/api/routers/admin.py`, `app/core/permissions.py`, `tests/test_role_escalation_guard.py` |
| **Full audit report** (F-86 – F-98) with prioritised recommendations, and a step-by-step fix guide for an AI agent | Owner asked for a whole-site review and fix instructions | `audit/full-audit-2026-10-02.md`, `audit/fix-guide-2026-10-02.md` |

- **Database:** none.
- **Settings:** none. API: the endpoints above answer 403 to sub-admins.
- **Destructive Admin Settings actions** (clear site cache, delete all manga, purge / mirror all images, cache clear/refresh/priority, saving settings) were already main-admin only on the server; a regression test now proves a sub-admin holding every grantable toggle gets 403 and nothing is deleted.
- **Check:** `pytest backend_fastapi/tests/test_api_management_main_admin_only.py`; as a sub-admin, Role Management (seen by the main admin) shows no API-management toggles.
- **Undo:** `git revert` the commit. No migration.

### 2026-10-02 — PR #31: Scraper AI is main-admin only

Merge `8370d34` (same PR as the entry above). Commit `ac52a33`.

| Change | Why | Main files |
| --- | --- | --- |
| **Scraper AI API and Custom Parser are hidden from sub-admins** (buttons and panels on Series Management; the key is not even loaded) | Owner's rule: only the main admin enters Scraper AI keys or creates parsers with the AI | `src/pages/Admin/SeriesManagement.jsx` |
| **`trigger_scraper_ai` and `configure_scraper_ai` can never be held by a sub-admin**: `has_permission` ignores stored grants, granting is refused (403 "main-admin only"), presets skip them, Role Management shows no toggle for them (catalogue flag `main_admin_only`) | A toggle or an old override could hand the AI to a sub-admin | `app/core/permissions.py` (`MAIN_ADMIN_ONLY`), `app/services/permissions_service.py`, `src/pages/Admin/RoleManagement.jsx` |
| **Scrapes a sub-admin starts never call the AI**: import preview, import jobs (`ensure_parser` and the in-scrape fallback), staged re-scrapes. They use existing, built-in and detected parsers; otherwise the message says to ask the main admin to add the site with Custom Parser. System jobs with no requester (schedules, health redetect) keep using it and only create candidates | The preview and import used to run the AI for whoever started them | `app/scrapers/source_pipeline.py` (`may_use_scraper_ai`, `allow_ai`), `app/scrapers/ai_fallback.py`, `app/scrapers/base_scraper.py`, `app/services/scraper_workflow_service.py`, `app/services/rescrape_service.py` |
| **A website a sub-admin approves gets no automatic AI parser.** The background job queued on save checks the website's `approved_by`; for a sub-admin it skips the AI and tells the main admin to use Custom Parser. The default `trigger` of `attempt_generation` / `generate_parser_task` is now `"requested"`, so only the website-save call (which passes `"website_saved"`) is checked | Approving a website started AI generation for whoever approved it | `app/services/parser_generation_service.py` (`_saved_by_scraper_ai_user`), `app/tasks/scraper_tasks.py` |

- **Database:** none. Existing `permission_overrides` rows granting these two keys to a sub-admin are ignored (and removed the next time that toggle is touched).
- **Settings:** none. API: `PUT /admin/users/{id}/permissions` granting either key → 403 `main_admin_only`; the catalogue entries carry `main_admin_only`.
- **Check:** sign in as a sub-admin → Series Management shows no *Scraper AI API* / *Custom Parser* buttons; Role Management (as main admin) has no Scraper AI toggles. `pytest backend_fastapi/tests/test_scraper_ai_main_admin_only.py`.
- **Undo:** `git revert` this PR's merge commit. No migration.

### 2026-10-01 — PR #30: scraper engine upgrades, Scraper AI playbook and guard

Merge `93acd4d`. Commits `d1f7415`, `a41aff1`.

| Change | Why | Main files |
| --- | --- | --- |
| **Images hidden in scripts are read.** Decoders for SinMH (`chapterImages`), qTcms (base64 `$qingtiandy$` list), standard packed `eval` scripts and any image array; tried automatically when a reader page has no page `<img>` | Most of the requested Chinese sites build their `<img>` tags with JavaScript, so plain HTML had no pages | `app/scrapers/script_images.py`, `app/scrapers/base_scraper.py`, `app/scrapers/autodetect.py` |
| **AJAX chapter lists** (`chapter_ajax`): WordPress Madara `POST …/ajax/chapters/` with `admin-ajax.php` fallback, or a generic same-site URL. Added to the Madara family, so sites such as mangaraw4u are recognised with no preset | Madara 1.6.5+ pages ship an empty chapter list | `base_scraper.py`, `presets.py`, `http_client.py` (`RequestWrapper.post`, same SSRF pinning as GET) |
| **More page sources:** `image_api` (JSON API keyed by ids in the chapter URL; mkzhan), `hidden_chapter_list` (LZString list in `#__VIEWSTATE`; manhuagui age gate), `data-href`/`data-hreflink` links, `{stem}`/`{ext}` page templates built from the redirected URL (baozimh `0_5_2.html`, senmanga `/2`), and a numbered page that redirects elsewhere ends the chapter | Split chapters and redirector links lost pages or mixed in the next chapter | `base_scraper.py`, `presets.py` |
| **Bot checks and 404s are named.** Cloudflare/CAPTCHA pages stop retries and are reported as such (also for Anime-Planet); 404 stops retrying. `naver.com` gets "use comic.naver.com". A list page pasted into Custom Parser falls back to the first series it links to; series discovery also recognises cover grids | Admins were told "selectors failed" for sites that were really blocking, or for the wrong page | `base_scraper.py` (`is_bot_challenge`), `source_pipeline.py`, `presets.py` (`WRONG_HOSTS`), `parser_generation_service.py`, `services/animeplanet_service.py` |
| **Scraper AI playbook:** the AI gets the full manual (every key, site families, 14 common obstacles and the key for each, hard stops where it must answer `{"unsupported": …}`, examples), measured site signals and script excerpts for the page, and the HTML fenced as untrusted data | Owner asked for instructions that make generation easy and reliable | `app/scrapers/ai_playbook.py`, `services/scraper_ai_service.py` (`build_prompt`, `generate_definition`) |
| **Guard on every AI answer:** only known keys; selectors must compile and avoid `:nth-child`/absolute paths; fetch URLs same-site; headers limited to Accept / Accept-Language / same-site Referer; known decoders only. Removed items are fed back to the next attempt; results are checked (chapter links on-site and distinct, page images not logos) | AI answers are untrusted (malformed, or steered by text on the page) | `app/scrapers/definition_guard.py`, `source_pipeline.py` |
| **Custom Parser shows "What to do next"** and "What the scraper saw on the page" under a failure | Failures only said "not possible" | `src/pages/Admin/SeriesManagement.jsx`, `ai_playbook.NEXT_STEPS` |

- **Database:** none.
- **Settings:** none. New optional parser-definition keys: `chapter_ajax`, `ajax_marker`, `hidden_chapter_list`, `image_api`, `image_source.decoder` values `sinmh` / `qtcms` / `script_array` / `auto_script`, page-template tokens `{stem}` / `{ext}`.
- **Check:** Admin → Series → Custom Parser with a series page of a requested site → green with a chapter count, or red with "What to do next". `pytest backend_fastapi/tests/test_scraper_site_capabilities.py` covers every requested address and capability offline. The live sites could not be fetched from the build sandbox (network policy), so the per-site settings follow each site's publicly known structure and are validated on every scrape.
- **Undo:** `git revert -m 1 <merge sha>`. No migration. Parsers saved with the new keys keep their rows; after a revert those keys are ignored and such parsers fall back to their selectors.

### 2026-10-01 — PR #29: one-time admin page that disappears; admin hash fixes; legacy bootstrap removed; install guides per OS

Merge `161a810`. Commit `843cad4`.

| Change | Why | Main files |
| --- | --- | --- |
| **`/admin-login` disappears after one use.** Once the one-time password has signed the owner in (or when none is set) the page and its API answer **404** like an address that never existed. The "Site owner? Admin sign-in" link is gone from the login page, and the page is a separate code chunk regular visitors never download. A new hash in `.env` re-opens it once (recovery) | Owner asked for a one-time page with no trace on the site afterwards | `app/api/routers/admin_login.py`, `src/pages/AdminLogin.jsx`, `src/app.js`, `src/components/Login.js` |
| **Admin hashes that can't be mangled.** New `scripts/make_admin_hash.py` prints `a2:<base64>` values with no `$`; `--write .env` puts them in `.env`, `--check .env` tests an e-mail/password. The server also accepts the old raw form, strips stray quotes, and ignores spaces around the password. `cli_bootstrap` no longer needs the database to run `admin-hashes` | The hash command crashed without a configured database; raw `$argon2id$…` hashes were silently cut by Compose / `source .env` / PowerShell; the page then greyed out **Continue** | `scripts/make_admin_hash.py`, `app/core/admin_identity.py`, `scripts/cli_bootstrap.py` |
| **`cli_bootstrap admin-status`** says whether the page is open, used or not set up, and whether the server sees both lines | "Password doesn't work" had no way to diagnose; `docker compose restart` doesn't re-read `.env` | `scripts/cli_bootstrap.py` |
| **Authenticator stays required after the hash is deleted.** The main admin needs the authenticator whenever the one-time sign-in is set up **or has been used** (marker in `system_settings`), so removing the used line from `.env` doesn't switch it off. The owner's authenticator can only be (re)set via that sign-in or on the server | Before, deleting `MAIN_ADMIN_PASSWORD_HASH` silently dropped the requirement | `app/core/admin_identity.py` (`admin_sign_in_in_use`), `app/dependencies/auth.py`, `app/api/routers/admin_2fa.py` |
| **Legacy bootstrap removed:** `SECRET_PHRASE`, `SECRET_PHRASE_FILE`, `EXPECTED_PHRASE` (never read), `ADMIN_PROMOTION_SECRET`/`_TTL`/`_MAX_TTL` + `POST /system/admin-token/redeem` + `GET /system/bootstrap` + `cli_bootstrap issue-admin-token`/`promote-user` + `services/admin_bootstrap.py`, `MAIN_ADMIN_AUTO_PROMOTE_ENABLED` (e-mail-only promotion), `ADMIN_2FA_REQUIRED` (replaced by the rule above), `REACT_APP_ADMIN_TOKEN_HINT`, and the `secret_phrase_used` flag in the manga list | Redundant ways to become admin, some weaker than the one-time sign-in; the manga list ran an extra query per request for an unused flag | `app/core/settings.py`, `app/services/auth_service.py`, `app/api/routers/system_state.py`, `app/api/routers/manga.py`, `app/services/catalogue_service.py`, `.env.example` |
| **`/system/health` is OK on a fresh install.** It no longer requires the retired `secret_phrase_used` flag; `admin_configured` now means a main admin account exists | Health stayed "not ok" for ever on sites set up through Admin sign-in | `app/api/routers/system_state.py` |
| **Install guides per OS** in `guide/` (Windows, macOS, Linux), plus `scripts/make_env.py` (creates `.env` with random secrets) and `.gitattributes` (LF for shell scripts, so Windows checkouts don't break the containers) | Owner asked for detailed, separate top-to-bottom guides | `guide/`, `backend_fastapi/scripts/make_env.py`, `.gitattributes`, `GUIDE.md` §1, §3, §6, §10, §11 |

- **Database:** none. The old `admin_bootstrap_state`, `admin_promotion_tokens` tables and the `system_state.secret_phrase_used` column stay (unused, history only; `GET /admin/admin-tokens` still lists old tokens).
- **Settings:** `.env` keys removed from the template and ignored if still present: `SECRET_PHRASE`, `SECRET_PHRASE_FILE`, `EXPECTED_PHRASE`, `ADMIN_PROMOTION_SECRET`, `ADMIN_PROMOTION_TOKEN_TTL_SECONDS`, `ADMIN_PROMOTION_TOKEN_MAX_TTL_SECONDS`, `MAIN_ADMIN_AUTO_PROMOTE_ENABLED`, `ADMIN_2FA_REQUIRED`, `REACT_APP_ADMIN_TOKEN_HINT`. `MAIN_ADMIN_EMAIL_HASH` / `MAIN_ADMIN_PASSWORD_HASH` now also accept the `a2:` form.
- **API:** `GET /auth/admin/status` returns `{"open": true}` or 404 (was `{"enabled", "used"}`); `POST /auth/admin/login` returns 404 when closed (was 403 / 401 "already used"). `GET /system/state` returns only `admin_configured`. Removed: `POST /system/admin-token/redeem`, `GET /system/bootstrap`. The manga list no longer has `secret_phrase_used`.
- **Check:** `cli_bootstrap admin-status` says OPEN → sign in at `/admin-login` (e-mail, password, authenticator) → `admin-status` says CLOSED and `/admin-login` shows "Page Not Found"; `/login` has no admin link; `/api/system/health` → `"ok": true`. Verified in Chromium against the real API (SQLite): wrong password refused, `#$` in a password accepted, page 404 after use, a new hash re-opens it once, a magic-link session gets "Confirm it's you" on `/admin`, and a valid code opens the Administrator Control Hub. The full Docker stack could not be built in the review sandbox (image registry blocked by its proxy).
- **Undo:** `git revert` this PR's merge commit, then `docker compose up -d --build --force-recreate`. No migration to undo. The old raw-hash lines keep working after a revert; `a2:` lines do **not** (make raw ones with the reverted `cli_bootstrap admin-hashes`). Old `.env` files with the removed keys work either way.

### 2026-10-01 — PR #28: Audit log and update/rollback guide

Merge `d831bc0`. Commit `fc0d566`.


- **What:** added this `AUDIT_LOG.md`, `CLAUDE.md` (working rules: every change gets an entry here and a `GUIDE.md` update), a PR template with the same checklist, and `GUIDE.md` §12 "Updating safely and rolling back".
- **Why:** to keep a record of what was changed, why, and how to undo it.
- **Database / settings:** none.
- **Undo:** revert the PR. Documentation only.

### 2026-10-01 — PR #27: domain switch, sign-in switch, admin sign-in, one email per account, chapter times, donations, right-click

Merge `6412a23`. Commits `a8b5d41`, `604b742`, `2c89797`, `66b5a0f`, `e285735`, `8c287f4`, `38a0fc3`.

| Change | Why | Main files |
| --- | --- | --- |
| **Website domain** in the Secret Vault drives the site address, CORS origins and Google/Microsoft/magic-link return addresses, live, no restart. Check → Switch → Go back card. Rescue command `set_site_domain` | Move to a new domain in a few clicks after a takedown | `app/vault_keys.py`, `app/services/secret_vault.py`, `app/bootstrap/middleware.py` (`LiveCORSMiddleware`), `app/api/routers/secret_vault.py`, `scripts/set_site_domain.py`, `src/pages/Admin/SecretVault.jsx` |
| **Sign-in required** switch (Admin Settings, main admin only, starts **off**). When on, guests get `LOGIN_REQUIRED` from reading routes; sign-in and admin routes are never gated | Owner's choice whether the site is members-only | `app/dependencies/site_access.py`, `app/bootstrap/routers.py`, `src/components/AuthGuard.js`, `AdminSettings.jsx` |
| **Admin sign-in** `/admin-login`: e-mail + **one-time** password (hash in `.env`) + authenticator. The password is void after it is used once. With it set, admin routes always need the authenticator, and the authenticator can't be changed from a normal session | Prove ownership without Google/e-mail; a stolen Gmail gets a reader session at most | `app/api/routers/admin_login.py`, `app/core/admin_identity.py`, `app/api/routers/admin_2fa.py`, `scripts/cli_bootstrap.py`, `src/pages/AdminLogin.jsx` |
| **One inbox, one account, for life**: unique canonical-email key (Gmail dots and `googlemail.com` folded, `+tags` dropped). The email can't be changed. Deleted accounts keep their email | Stop one inbox opening many accounts | `app/utils/email_crypto.py`, `app/models/user.py`, `app/services/auth_service.py` |
| **Reader passwords removed** (endpoint, profile field, Login tab, `password_service`) | Magic link / Google / Microsoft only; nothing to forget | `app/api/routers/account.py`, `src/components/Login.js`, `src/pages/CompleteProfile.js` |
| **Chapter times**: update cards show when the newest chapter arrived; each chapter shows "Xh ago"; "latest" sorts by newest chapter; times sent as UTC with `Z`; a missing time shows nothing instead of "Just now" | Cards said "Just now" and the order changed whenever a series was viewed | `app/services/catalogue_service.py`, `app/services/manga_service.py`, `src/utils/gstTime.js`, `Homepage.js`, `MangaDetail.js` |
| **Donation links** (Admin Settings → Donations): allow-listed platforms over https, crypto addresses checked against their network, all-or-nothing saves, audit log + bell notice on change; footer "Support the site" | Accept donations safely | `app/services/donation_service.py`, `app/api/routers/support.py`, `src/components/DonationEditor.jsx`, `SupportLinks.jsx` |
| **Right-click a manga card** opens it in a new tab; Shift(/Win/Cmd)+right-click opens a new window; right-click stays blocked elsewhere | Open series without leaving the page | `src/utils/mangaLinkMenu.js`, `src/components/AntiTamperGuard.jsx` |

- **Database:** `20261009_login_required`, `20261010_email_identity`, `20261011_admin_password_single_use`.
- **Settings:** new `.env` `MAIN_ADMIN_PASSWORD_HASH`. New vault key `SITE_DOMAIN`.
- **Check:**
  - `/admin-login` works once, then shows "already been used".
  - Admin Settings shows the *Sign-in required* card and the *Donations* tab.
  - Update cards show "Xh ago".
  - The Secret Vault shows the *Website domain* card.
- **Undo:** `git revert -m 1 6412a23`, then `alembic downgrade 20261008_chapter_title_translations`. After that, the admin password is reusable, Gmail aliases can open separate accounts again, and reader password login comes back for accounts that had one (the `password_hash` column was kept).

### 2026-10-01 — PR #26: library in the browser, day mode, silent re-login, Anime-Planet, permissions, UTC

Merge `b73171f`. Commits `c26d351`, `34f4273`, `987e112`.

- **Anime-Planet** metadata source (manga, manhwa and manhua only). The same metadata page can't be imported twice. Files: `app/services/animeplanet_service.py`, `metadata_sources.py`, `series_import.py`.
- **Bookmarks and history in the browser.** The server stops recording history. Only chapters actually opened count as read. One history entry per series. New public `GET /manga/batch`. Stock photos replaced with SVG placeholders. Files: `src/utils/library.js`, `src/utils/placeholders.js`, `BookmarkHistoryTab.jsx`.
- **Day mode** palette remap (`src/index.css`). **Silent session refresh** on 401 (`src/services/api.js`), which fixed "Mark resolved logs me out". The **default translator** now uses the LibreTranslate URL.
- **Permissions**: new `broadcast` and `manage_ads` toggles. Branding is main-admin only. Adds `GET /admin/permissions/me`.
- **Times**: server times are read as UTC.
- **Database:** none.
- **Undo:** `git revert -m 1 b73171f`. Readers' browser libraries stay in their browsers.

### 2026-10-01 — PR #25: vault holds every non-foundation setting, chapter titles, OCR language fix

Merge `f1f230a`. Commits `6a62fa2`, `1c8474a`, `8ae9a70`.

- **Tesseract language bug**: `-l <lang>` came after `tsv`, so every page was read as English. Neighbouring CJK glyphs are now joined. File: `app/services/ocr_service.py`.
- **Readable chapter titles**: "522 원준 522화 2024-11-07" becomes "Chapter 522". Real subtitles are translated once and cached. Files: `chapter_title_service.py`, `GET /manga/{id}/chapter-titles`.
- **Vault grows to 79 settings**, applied at start-up by `vault_preload.py`. Removing a value restores `.env`. `VAULT_PRELOAD_DISABLED` exists for recovery.
- **Database:** `20261008_chapter_title_translations`.
- **Undo:** `git revert -m 1 f1f230a`, then `alembic downgrade 20261007_three_roles`.

### 2026-10-01 — PR #24: modals and cards, reader translation overlay, notifications, three roles

Merge `5f2034b`. Commits `e6e98b8`, `64e00cb`, `97b78f1`, `907e387`.

- **Fixes**: modals scroll, cards open, real views and ratings. AI/OCR providers save to the account with Test buttons, and the Gemini request format is fixed. The backend image ships Tesseract with CJK language data.
- **Overlay**: driven by settings; ten open-licence fonts; colours; usage limits; higher-quality page images.
- **Notifications**: readers only get their own (new chapter, finished series, broadcasts, account notices). Operational notices go to the main admin.
- **Three roles** (admin, sub-admin, user): the moderator role is retired, and Role Management rewritten against the real API.
- **Database:** `20261005_local_ocr_default_on`, `20261006_reader_overlay_settings`, `20261007_three_roles` (**lossy**).
- **Undo:** `git revert -m 1 5f2034b`. For the database, restore the pre-update backup (the moderator data is gone), or `alembic downgrade 20261004_vault_secrets` for the columns only.

### 2026-10-01 — PR #23: real admin metrics, Secret Vault

Merge `58ca9af`. Commit `9e90f5a`.

- **Admin hub and Health page** show real counts; placeholder and random numbers removed.
- **Secret Vault** (main admin, authenticator, 10-minute unlock, values encrypted with `INTEGRATIONS_SECRET`, audit log never records values).
- **Database:** `20261004_vault_secrets`.
- **Undo:** `git revert -m 1 58ca9af`, then `alembic downgrade 20261003_merge_totp_custom_tabs` (vault values are lost, and `.env` takes over).

### Before 2026-10-01

PRs #1–#22 predate this log. Their summaries are in the merge commits
(`git log --first-parent main`) and the pull requests on GitHub.

---

## 5. Open items and known limits

- **Not run when `GUIDE.md` was rewritten for Ubuntu:** the Docker image builds and `docker compose up` (no Docker daemon in the sandbox), Docker's installer, NodeSource, the deadsnakes PPA, Caddy's own apt repository (Ubuntu 22.04) and Let's Encrypt (those hosts are blocked there). Their commands are the vendors' documented ones. Check them on the first real install.
- **Repo behaviours the guide works around (code unchanged):** `docker-compose.yml` publishes 8000 and 8080 on all interfaces and hard-codes `APP_ENV: development`; `make_env.py` leaves `.env` world-readable (644); `backup_postgres.sh` / `backup_storage.sh` assume a host-reachable database and `/app/storage`; `setup-server.sh` turns off SSH password and root login and installs `docker-compose-plugin`, which stock Ubuntu does not have. Fixing them in the code would remove the need for the workarounds.
- **Storage & Backups** was tested against an in-memory S3 server (and the signer against AWS's published example), not against a live R2/B2 bucket: press *Test connection* with your own keys once. **Geolock** does not cover picture files nginx serves directly, and VPNs get around any country lock.
- **Scraper AI in scrapes a deputy starts**: a deputy holding *trigger_scraper_ai* gets AI help in previews and re-scrapes without entering a fresh code (the Custom Parser page itself asks for one). It only spends AI quota.
- **Bubble shapes** are found with a light heuristic (Pillow, no AI): tested on synthetic pages with round, square, freeform, dark and open bubbles. A bubble whose outline has a gap, touches the page edge, or holds two separately-read text lines falls back to the plain box. Report pages where the shape looks wrong.
- **Per-site scraper settings** (baozimh page templates, mkzhan image API, senmanga page URLs, Madara AJAX) follow each site's public structure and were tested on synthetic pages only; the build sandbox could not reach the sites. Run Custom Parser on one real series per site.
- **Anime-Planet parser** was tested on synthetic pages only (the build sandbox couldn't reach the site). Check a real link in the import preview.
- **Domain "is this site" check** asks `/healthz`, which any copy of this software answers. It confirms the domain reaches *a* MangaWorld server, not necessarily yours.
- **Win + right-click**: Windows often swallows the Windows key. Shift + right-click is the reliable way to get a new window.
- **Crypto addresses** are checked for format, not ownership. Send yourself a small test amount after every change.
- **Comment and cultivation systems**: postponed by the owner ("fix our issues first").
- **Unused server code** (found 2026-10-03): `suggestion_service` remains. (The `read_history` table is in use again: see the 2026-10-03 history-sync entry.) Many functions in `src/services/api.js` belong to features with no page yet (below) and are kept for them.
- **Built on the server but without a page** (found 2026-10-03): Community (emojis, realms, memes, ranks, pills; it has a Site Functions switch), comment edit / vote / react / report / moderation, and notification preferences.
- **SQLite development database:** several migrations are PostgreSQL-only, so an SQLite database made with `alembic upgrade head` lacks `settings`, `footer_settings`, `login_tokens`, `complaints` and some columns. Production (PostgreSQL) is complete. Use PostgreSQL for local testing too (the install guides do, through Docker).
- **`braces` advisory ignored in CI** (GHSA-vfj7-8cjw-p6xm, build-time only via tailwindcss 3): remove it from `.github/scripts/npm-audit-gate.mjs` when `braces` ships a fix or the site moves to Tailwind 4.
- **`users.password_hash`** column is unused since PR #27. It was kept so that undoing PR #27 restores old password logins. It can be dropped in a later migration.

---

## Entry template

Copy this to the top of [Change entries](#change-entries):

```markdown
### YYYY-MM-DD — PR #NN: short title

Merge `<merge sha>`. Commits `<sha>`, `<sha>`.

| Change | Why | Main files |
| --- | --- | --- |
| What a user/admin will notice | The problem it solves | `path/one`, `path/two` |

- **Database:** new migrations (and add them to §2 with their downgrade effect), or "none".
- **Settings:** new/changed `.env` keys, vault keys, Admin Settings switches, or "none".
- **Check:** how to see it works after deploying.
- **Undo:** the exact `git revert` / `alembic downgrade` / switch, and what is lost.
```
