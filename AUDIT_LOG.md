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
| **Secret Vault** (Admin → Secret Vault) | Everything else: Google/Microsoft sign-in, SMTP/magic links, OCR/translation, API keys, limits, Sentry, **website domain** | Main admin only, with an authenticator code and a 10-minute unlock | Remove the value and it falls back to `.env`. `VAULT_PRELOAD_DISABLED=true` skips the vault if a bad value stops start-up |
| **Admin Settings** (database) | Site name/logo/footer, sign-in required switch, donations, maintenance, session policy | Main admin (sub-admins get only the toggles granted to them) | Change it back in the page |

### People and roles

- **Main admin**: one owner. Proves it **once** at `/admin-login` with e-mail, a **one-time** password from `.env` and an authenticator code. After that the page is gone (404, no link anywhere), the owner signs in like readers, and every admin page asks for the authenticator code. A new password hash in `.env` (server access) re-opens the page once, for recovery. Signing in with the owner's e-mail alone never grants admin.
- **Sub-admin**: a user with per-person permission toggles (Role Management). Can never get the Secret Vault, Admin Settings (not even read), **API Management** (OCR / translation / AI providers), branding, role management, or the **Scraper AI** (its API key and Custom Parser; `core/permissions.py` `MAIN_ADMIN_ONLY`). Previews, imports and re-scrapes a sub-admin starts use built-in and detected parsers only, never the AI.
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

### 2026-10-02 — API Management and Admin Settings main-admin only; full audit

Branch `claude/great-faraday-nh2dwx`. PR number and merge SHA: fill in when known.

| Change | Why | Main files |
| --- | --- | --- |
| **Sub-admins can no longer read Admin Settings** (`GET /admin/settings`), the OCR provider check (`/admin/validate-ocr-providers`), the unused `/config` snapshot, or trigger `/admin/database/alembic-status`; all are main-admin only. The session policy is readable only by whoever may change it (`set_session_policy`) | Owner's rule; audit finding F-88 showed every sub-admin could read them | `app/api/routers/admin.py`, `app/api/routers/management.py` |
| **API Management toggles are main-admin only**: `view_providers`, `configure_ocr`, `configure_translation`, `configure_ai`, `set_provider_priority` join `MAIN_ADMIN_ONLY` (no Role Management toggle, stored grants ignored, presets skip them; the *Operations* preset no longer lists them) | They guarded nothing (API Management was already main-admin only in code) but showed sub-admins as holding it (F-98) | `app/core/permissions.py` |
| **Full audit report** (F-86 – F-98) with prioritised recommendations | Owner asked for a whole-site review before further fixes | `audit/full-audit-2026-10-02.md` |

- **Database:** none.
- **Settings:** none. API: the endpoints above answer 403 to sub-admins.
- **Check:** `pytest backend_fastapi/tests/test_api_management_main_admin_only.py`; as a sub-admin, Role Management (seen by the main admin) shows no API-management toggles.
- **Undo:** `git revert` the commit. No migration.

### 2026-10-02 — Scraper AI is main-admin only

Branch `claude/great-faraday-nh2dwx` (commit on top of `a41aff1`, which `main` merged as `93acd4d` with no other change). PR number and merge SHA: fill in when known.

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
