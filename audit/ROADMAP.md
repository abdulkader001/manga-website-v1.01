# Roadmap: fixes and hardening

This is the living to-do list for the project. It is written so a fresh chat
with an AI coding agent can pick it up cold: read this file, do what the owner
asks, then update this file.

## How to use (owner)

Say one of:

- `do 3` — do item 3 only.
- `do 1, 2, 3` or `do PR A` — do those items (a `PR` group is one pull request).
- `status` — show what is done and what is next.

The agent does only what you name, updates the tables below in the same pull
request, and stops.

## Rules for the agent

1. Read this file, then the referenced audit reports, before touching code.
2. Do only the named items. Do not start other items, and do not open a pull
   request unless the owner asks for one.
3. Verify by running things. Say plainly what was verified and what was only
   read. Items marked **Together** need the owner's real sites or accounts.
4. When an item is finished, change its status to `done`, fill in the
   date and pull request link, and move any new finding to the "Found later"
   table with the next free number.
5. Never point the backend tests at a database that holds real data: the test
   fixtures drop all tables. Use a separate throw-away database.
6. Keep the UI looking and behaving the same unless the item says otherwise.
7. Keep repository files free of model names and session links.
8. Run the same checks CI runs before pushing: `ruff check backend_fastapi`,
   the backend tests (Postgres), `npm run build` and `tsc --noEmit`.

Status values: `todo`, `doing`, `done`, `blocked` (say why in Notes).

## Context (short)

React UI (Vite) + FastAPI + Postgres + Redis + Celery, behind nginx. Scraping
turns source sites into chapters; page pictures are downloaded, compressed to
WebP and served from this site; series can be grouped or split into vertical
pages. Details: [project-verdict-2026-09-30.md](project-verdict-2026-09-30.md),
[frontend.md](frontend.md),
[../backend_fastapi/audit/security-review-2026-09-30.md](../backend_fastapi/audit/security-review-2026-09-30.md),
[../backend_fastapi/README.md](../backend_fastapi/README.md),
[../deployment/README.md](../deployment/README.md).

## PR A — Visible and easy

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 1 | Bundle Font Awesome and Material Icons into the build (npm packages, imported in `src/index.jsx`) and delete the two CDN `<link>` tags in `index.html`. Production CSP blocks the CDNs, so icons vanish otherwise. | done | 2026-09-30 | Font Awesome pinned to 6.5+ (same look as the CDN). Build checked; icons not viewed in a browser. |
| 2 | Fix the "Western Comic / Webcomic" type: the import form offers `comic`, the backend only knows manga/manhwa/manhua and stores manga (right-to-left). Support it properly (left-to-right default) or remove it from the form. | done | 2026-09-30 | Removed the option from the import form. Browse filter still lists `comic` and `webtoon` (matches nothing): not touched. |
| 3 | Return `source_url`, `mangaupdates_url` and `scrape_layout` to admins only (list, detail and search responses). | done | 2026-09-30 | Stripped per viewer in `catalogue_service.apply_viewer_fields`; test `test_manga_admin_only_fields.py`. Routers now copy the cached payload first (it was shared between viewers). |

## PR B — Hardening

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 4 | nginx hotlink protection (`valid_referers`) and `limit_req` / `limit_conn` on `/api/v1/manga/pages/` and `/covers/`. | done | 2026-09-30 | `deployment/nginx/site.conf`. Allow empty referer and the site's own domain(s). Done with a `map` on Referer vs Host (nginx.conf) instead of `valid_referers`, because `server_name` is `_`; partner domains go in that map. Tried against a real nginx: own and empty referer 200, foreign 403, burst beyond 200 gets 429. Not tried in the Docker image. |
| 5 | Refuse to start in production when `ALLOW_PLAINTEXT_SECRETS` is set. | done | 2026-09-30 | `settings.py`; test `test_plaintext_secrets_production_guard.py`. The secure-cookie guard tests now clear the variable. |
| 6 | Per-IP login rate limit in nginx and in the API (beyond the per-account lockout). | done | 2026-09-30 | Login is Google or magic link (no passwords). nginx: 10 requests/min, burst 10 on those paths. API: 30 per 10 min per IP on Google login and callbacks (magic-link endpoints already had limits). Test `test_login_ip_rate_limit.py`. |
| 7 | Run picture compression on its own Celery queue and worker service so a big import cannot delay new-chapter checks. | done | 2026-09-30 | Queue `compress` for `mirror_chapter_pages` only; new worker in both compose files, a Kubernetes deployment and `manga-worker-compress.service`. Routing checked; containers, Kubernetes and systemd not run. The systemd general worker still has no `CELERY_QUEUES` (pre-existing). |

## PR C — Admin screens and clean-up

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 8 | Buttons on the admin series page: re-compress pictures, and change layout (group size, spread mode, reading direction). The API endpoints exist already. | done | 2026-09-30 | Two row buttons and a layout dialog in `SeriesManagement.jsx`. Group size is not offered: the layout endpoint ignores it (grouping is fixed at import). The compress button only handles chapters still pointing at the source site. Build and `tsc` pass; not clicked through in a browser. |
| 9 | Log which legacy API aliases are still called, then remove the two old mounts (each route is registered three times today). | doing | 2026-09-30 | Logging done: `legacy_api_alias_used` log line plus a `legacy_api_alias_requests_total{alias,route}` metric on `/metrics`; test in `test_legacy_api_aliases.py`. Removal of the two mounts still waits until production shows no use. The UI itself calls `/api/v1`. |
| 10 | Drop the unused `custom_tabs` table with a migration. | todo | | Ask the owner first: it is data loss. |

## PR D — Keep it running without attention

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 11 | Daily health check per source site: alert when a parser finds 0 chapters or 0 pictures, then try AI re-detection. Sites change layout over time; this is the main long-term breakage. | done | 2026-09-30 | `source_health_service.py`, daily task `check_source_health`. One sample series per host; zero chapters / zero pictures / unreachable -> admin notification; the first two also try re-detection and save a *candidate* parser only (activation stays with an admin). Latest results: `GET /admin/sources/health`. Tested with mocked sites; never run against a real source site (needs the real sites). |
| 12 | Storage usage report (admin page or metric) and an alert threshold. `chapters.pages_bytes` already stores sizes. | done | 2026-09-30 | `storage_report_service.py`: `GET /admin/storage` (totals from `pages_bytes`, top series, volume usage), Prometheus gauges, daily alert task; limits `STORAGE_ALERT_PERCENT` (80) and `STORAGE_ALERT_BYTES`. No admin screen yet. |
| 13 | Error monitoring (Sentry or similar) and alerts for failed Celery tasks. | blocked | 2026-09-30 | Code done: `sentry-sdk` added to requirements (it was missing, so Sentry never started), Celery integration, and workers now initialise it. Needs the owner's DSN (U4) in `SENTRY_DSN`; until then it stays off. `requirements.lock` edited by hand, regenerate with pip-compile when convenient. |
| 14 | Scheduled backups for Postgres and the pictures volume, plus a written restore test. | done | 2026-09-30 | Added pictures backup, restore and restore-test scripts, `run_backups.sh`, `run_backup_verification.sh`, systemd timers (nightly backup, weekly restore test) and a written restore drill in `backups.md`. Scripts tested on a local directory (plain and encrypted); Postgres and Redis steps and the systemd units were not run here. |

## PR E — Deeper security

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 15 | Second factor or re-authentication for the main admin. | done | 2026-09-30 | Authenticator-app codes (TOTP) for admin-tier accounts: enrol at `/admin/security`, then admin routes need a 30-minute step-up cookie (`admin_second_factor.py`, `routers/admin_2fa.py`, guard in `dependencies/auth.py`, migration `20261002_admin_totp`). `ADMIN_2FA_REQUIRED=true` makes it mandatory for main admins; off by default so nobody is locked out. Secret encrypted at rest; codes single-use; guesses rate-limited. Tests `test_admin_second_factor.py` (SQLite). Screens build and type-check but were not clicked through; migration not run on Postgres. No backup codes: a lost phone is fixed by clearing the row (see `deployment/key-rotation.md`). |
| 16 | Encryption key rotation: accept an old and a new key together, re-encrypt, document the steps. | done | 2026-09-30 | `EMAIL_ENCRYPTION_KEY=NEW,OLD` and `INTEGRATIONS_SECRET_PREVIOUS`; `scripts/rotate_encryption_key.py` re-encrypts emails, OAuth tokens, admin authenticator secrets and API keys; steps in `deployment/key-rotation.md`. Several email keys need `EMAIL_HASH_SECRET` pinned (startup refuses otherwise). Tests `test_key_rotation.py` (SQLite); the script was not run against Postgres. |
| 17 | Public contact page and takedown procedure for hosted pictures. | blocked | | Needs the owner's contact details and wording (U3). Not started. |
| 18 | Upgrade `vite` to 6+ and `react-router-dom` to 7 (clears the 4 `npm audit` findings). | todo | | Own PR; click through every page after. Left out of PR E on purpose. |

## PR F — Long-term maintenance

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 19 | Dependabot or Renovate config; keep the weekly dependency audit in CI. | todo | | |
| 20 | Frontend tests in CI: login, reader, admin import. | todo | | No test runner is installed yet. |
| 21 | Pin base images and dependencies; document how and when to update them. | todo | | |
| 22 | Runbook: change of source domain, restore from backup, key rotation, adding a new source site. | todo | | |
| 23 | Move pictures to S3 or a CDN when the library outgrows the disk (design first). | todo | | Only when item 12 shows the need. |

## PR G — Real-site verification (Together with the owner)

These need the real source sites or accounts, which the build sandbox cannot
reach. The agent guides and fixes what the checks show.

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 24 | Run Test & Live Preview on one series per supported site; fix parsers from what it shows. | todo | | Sites: see `backend_fastapi/app/scrapers/presets.py`. |
| 25 | Import one real MangaUpdates link and check the metadata (the id decoding was never tried on the real site). | todo | | |
| 26 | Import one real two-page (book format) series and one long-strip series; check split, order and compression by eye. | todo | | |
| 27 | Configure an OCR and translation provider (Admin → API management) and translate one real chapter. | todo | | |
| 28 | `docker compose build` and `up`, then click through the site once (Docker images were never built in the sandbox). | todo | | |

## PR H — Decision needed

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 29 | Public browsing: today everything except login pages requires login, so search engines cannot index series and ads reach logged-in users only. Proposed: browsing public, login only for bookmarks, ratings, comments and translation. | blocked | | Owner decides first. `src/app.js`, `seo.py` |

## Owner actions (not for the agent)

| # | Action | Status | Notes |
| --- | --- | --- | --- |
| U1 | Rotate the Google OAuth client secret that was committed in the old `Manga-Website` repository. | todo | Google Cloud console. |
| U2 | Make sure `ALLOW_PLAINTEXT_SECRETS` is not set on the production server. | todo | |
| U3 | Provide contact details for the takedown page (item 17). | todo | |
| U4 | Provide a Sentry (or similar) DSN (item 13). | todo | |

## Found later

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| | | | | |

## Done log

| Date | What | Pull request |
| --- | --- | --- |
| 2026-09-30 | UI connected to the FastAPI backend, scraping, page compression, layouts | #4, #5 |
| 2026-09-30 | Repository tidy: unused files and custom tabs removed, audit and deployment files grouped | #6 |
