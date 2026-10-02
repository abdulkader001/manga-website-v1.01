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
| `.env` on the server | Foundation only: database/Redis, signing and encryption keys, `INTEGRATIONS_SECRET`, admin identity (`MAIN_ADMIN_EMAIL_HASH`, `MAIN_ADMIN_PASSWORD_HASH`), starting site address | Whoever has the server | Edit the file and recreate the containers |
| **Secret Vault** (Admin → Secret Vault) | Everything else: Google/Microsoft sign-in, SMTP/magic links, OCR/translation, API keys, limits, Sentry, **website domain**, the **backup** schedule, password and storage keys (`BACKUP_*`, set from Storage & Backups) and **Geolock** (`GEOLOCK_*`, set from Geolock) | Main admin only, with an authenticator code and a 10-minute unlock | Remove the value and it falls back to `.env`. `VAULT_PRELOAD_DISABLED=true` skips the vault if a bad value stops start-up |
| **Admin Settings** (database) | Site name/logo/footer, sign-in required switch, donations, maintenance, session policy | Main admin (sub-admins get only the toggles granted to them) | Change it back in the page |

### People and roles

- **Main admin**: one owner. Proves it **once** at `/admin-login` with e-mail, a **one-time** password from `.env` and an authenticator code. After that the page is gone (404, no link anywhere), the owner signs in like readers, and every admin page asks for the authenticator code. A new password hash in `.env` (server access) re-opens the page once, for recovery. Signing in with the owner's e-mail alone never grants admin.
- **Sub-admin**: a user with per-person permission toggles (Role Management). Sees only **their own** rows in the admin audit log unless granted *See the full audit log* (`view_full_audit`). Previews, imports and re-scrapes use the Scraper AI only for a sub-admin who holds it.
- **Admin** (`UserRole.CO_ADMIN`; at most **two**, `MAX_ADMINS`): the owner's right hand. Holds every power except Admin Settings, the cache and "delete all manga" (`ADMIN_OFF_BY_DEFAULT`) until the owner switches them on; only the owner changes an Admin's toggles (switching a site-owner power on needs the owner's authenticator code). Has power over sub-admins and users only (`permissions_service.assert_may_act_on`, `authorize_change`): never over another Admin, themselves or the owner. Sees sub-admins' and users' e-mail, never an Admin's or the owner's. Needs an authenticator and a fresh code to use site-owner powers (`dependencies/powers.py`). Appoints sub-admins from a shared pool of **50** seats (`SUB_ADMIN_POOL`; an equal share unless the owner sets it). Keeps a **succession line** of up to two sub-admins (`admin_successors`); only the owner makes, removes or hands over an Admin seat (`services/admin_roles.py`, `api/routers/roles_admins.py`). `UserRole.ADMIN` is only the old name of the owner tier.
- **Sub-admin**: per-person toggles set by an Admin or the owner, never above the owner's **ceiling** (`system_settings.sub_admin_blocked_permissions`) and never a site-owner power. Power over users only. Custom roles (presets) are created by the owner only.
- **Automatic succession** (owner only, off by default, owner's code to change): an Admin idle longer than the chosen days (default 60) becomes a user and the first eligible sub-admin in their line (still a sub-admin, active, with an authenticator) takes the seat as it is: the owner's restrictions, the seats and the appointees (`services/admin_succession.py`, daily job). The owner can hand a seat over at once. Ownership never passes to anyone; `/admin/demote-main` stays owner-only.
- **User (reader)**: signs in with a magic link, Google or Microsoft. **No passwords.** One inbox gives one account for life.

### Data that is deliberately *not* on the server

- Bookmarks, reading history and "where I stopped" live in the reader's browser (`localStorage` key `mw_library_v1`, `src/utils/library.js`). Readers move them between devices with export/import.

### Server-side tools (run with `docker compose exec backend python -m backend_fastapi.scripts.<name>`)

| Command | Does |
| --- | --- |
| `make_admin_hash.py [--write .env \| --check .env]` | Makes the two `.env` lines for the one-time Admin sign-in (`$`-free `a2:` form), writes them into `.env`, or checks an e-mail/password against `.env`. Needs only Python + `cryptography`; runs without the site (`guide/` shows the `docker run` form) |
| `make_env.py [--local]` | Creates a new `.env` with random secrets and matching DB/Redis passwords. Never overwrites an existing `.env`. Standard-library Python only |
| `cli_bootstrap admin-status` | Is `/admin-login` open, used up or not set up, and can the server see both lines |
| `cli_bootstrap admin-hashes` | Same as `make_admin_hash.py` (prints the lines) |
| `cli_bootstrap reset-2fa --email …` | Removes a lost authenticator |
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
| `20261011_admin_password_single_use` | #27 | `system_settings.admin_setup_password_used` | Drops it, so the **current admin password works again** |
| `20261012_overlay_text_scale` | #33 | `user_processing_settings.overlay_font_size` becomes the 1-100 slider (pixels converted: 20 px → 28.5); new `overlay_outline_color`, `overlay_match_bubble` | **Lossy**: sizes go back to pixels rounded and capped at 10-40 px (a reader on 100 = 70 px gets 40 px); outline colour and bubble switch are dropped |
| `20261013_admin_succession` | #34 | `admin_activity_days` table (one row per admin per active day) and `system_settings.succession_enabled` / `succession_inactive_days` / `succession_enabled_at` | Drops them. **Lossy**: the activity history and the succession switch are gone (succession is off again) |
| `20261014_four_roles` | this PR | Adds role `CO_ADMIN` (Postgres enum value if native), `users.appointed_by` / `sub_admin_quota` / `admin_since`, `admin_successors`, `system_settings.sub_admin_blocked_permissions`; deletes site-owner overrides held by sub-admins (they can no longer hold them) | **Lossy**: Admins go back to sub-admins, and the new columns, succession lines and ceiling are dropped. The deleted overrides do not come back (re-promote in Role Management) |

Check where a server is: `docker compose exec backend alembic current`.

---

## 3. How to undo a change

Always **back up first** (`GUIDE.md` §12.1 has copy-paste commands). Then pick the smallest undo that works.

**A. Switch a feature off (no code change)**. Many features have a switch:
sign-in required (Admin Settings), donations (untick "Shown" or remove),
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

### 2026-10-02 — Four roles: owner, Admin, sub-admin, user

Branch `claude/eager-noether-0jg9xq`. Merge SHA: fill in when known.

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

Branch `claude/great-faraday-nh2dwx`. Commits `c96b98e`, `2da5e86`, `c608f69` and the follow-ups. Merge SHA: fill in when known.

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

- **Storage & Backups** was tested against an in-memory S3 server (and the signer against AWS's published example), not against a live R2/B2 bucket: press *Test connection* with your own keys once. **Geolock** does not cover picture files nginx serves directly, and VPNs get around any country lock.
- **Scraper AI in scrapes a deputy starts**: a deputy holding *trigger_scraper_ai* gets AI help in previews and re-scrapes without entering a fresh code (the Custom Parser page itself asks for one). It only spends AI quota.
- **Bubble shapes** are found with a light heuristic (Pillow, no AI): tested on synthetic pages with round, square, freeform, dark and open bubbles. A bubble whose outline has a gap, touches the page edge, or holds two separately-read text lines falls back to the plain box. Report pages where the shape looks wrong.
- **Per-site scraper settings** (baozimh page templates, mkzhan image API, senmanga page URLs, Madara AJAX) follow each site's public structure and were tested on synthetic pages only; the build sandbox could not reach the sites. Run Custom Parser on one real series per site.
- **Anime-Planet parser** was tested on synthetic pages only (the build sandbox couldn't reach the site). Check a real link in the import preview.
- **Domain "is this site" check** asks `/healthz`, which any copy of this software answers. It confirms the domain reaches *a* MangaWorld server, not necessarily yours.
- **Win + right-click**: Windows often swallows the Windows key. Shift + right-click is the reliable way to get a new window.
- **Crypto addresses** are checked for format, not ownership. Send yourself a small test amount after every change.
- **Comment and cultivation systems**: postponed by the owner ("fix our issues first").
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
