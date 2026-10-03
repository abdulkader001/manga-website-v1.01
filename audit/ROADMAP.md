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
| 10 | Drop the unused `custom_tabs` table with a migration. | done | 2026-09-30 | Owner approved the drop. Migration `20261002_drop_custom_tabs` (downgrade recreates the empty table); model, relationship and export removed. Run on SQLite only; not run on Postgres. Rows in the table are lost. |

## PR D — Keep it running without attention

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 11 | Daily health check per source site: alert when a parser finds 0 chapters or 0 pictures, then try AI re-detection. Sites change layout over time; this is the main long-term breakage. | done | 2026-09-30 | `source_health_service.py`, daily task `check_source_health`. One sample series per host; zero chapters / zero pictures / unreachable -> admin notification; the first two also try re-detection and save a *candidate* parser only (activation stays with an admin). Latest results: `GET /admin/sources/health`. Tested with mocked sites; never run against a real source site (needs the real sites). |
| 12 | Storage usage report (admin page or metric) and an alert threshold. `chapters.pages_bytes` already stores sizes. | done | 2026-09-30 | `storage_report_service.py`: `GET /admin/storage` (totals from `pages_bytes`, top series, volume usage), Prometheus gauges, daily alert task; limits `STORAGE_ALERT_PERCENT` (80) and `STORAGE_ALERT_BYTES`. No admin screen yet. |
| 13 | Error monitoring (Sentry or similar) and alerts for failed Celery tasks. | blocked | 2026-09-30 | Code done: `sentry-sdk` added to requirements (it was missing, so Sentry never started), Celery integration, and workers now initialise it. Needs the owner's DSN (U4) in `SENTRY_DSN`; until then it stays off. `requirements.lock` edited by hand, regenerate with pip-compile when convenient. |
| 14 | Scheduled backups for Postgres and the pictures volume, plus a written restore test. | done | 2026-09-30 | Added pictures backup, restore and restore-test scripts, `run_backups.sh`, `run_backup_verification.sh`, systemd timers (nightly backup, weekly restore test) and a written restore drill in `backups.md`. Scripts tested on a local directory (plain and encrypted); Postgres and Redis steps and the systemd units were not run here. |

## PR E — Deeper security

Item 17 (contact page and takedown procedure) was dropped by the owner on 2026-09-30.

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 15 | Second factor or re-authentication for the main admin. | done | 2026-09-30 | Authenticator-app codes (TOTP) for admin-tier accounts: enrol at `/admin/security`, then admin routes need a 30-minute step-up cookie (`admin_second_factor.py`, `routers/admin_2fa.py`, guard in `dependencies/auth.py`, migration `20261002_admin_totp`). Since PR #39 the owner **must** enrol before any admin page opens (`ADMIN_2FA_REQUIRED` is gone). Secret encrypted at rest; codes single-use; guesses rate-limited. Tests `test_admin_second_factor.py` (SQLite). Migration applied on PostgreSQL 14 (compose stack) and in the empty-database chain check. Screens clicked through in Chromium, including entering a code at the gate. No backup codes: a lost phone is fixed by clearing the row (see `deployment/key-rotation.md`). |
| 16 | Encryption key rotation: accept an old and a new key together, re-encrypt, document the steps. | done | 2026-09-30 | `EMAIL_ENCRYPTION_KEY=NEW,OLD` and `INTEGRATIONS_SECRET_PREVIOUS`; `scripts/rotate_encryption_key.py` re-encrypts emails, OAuth tokens, admin authenticator secrets and API keys; steps in `deployment/key-rotation.md`. Several email keys need `EMAIL_HASH_SECRET` pinned (startup refuses otherwise). Tests `test_key_rotation.py`. Rehearsed on PostgreSQL 14 in the compose stack: 5 values rotated, 0 unreadable; afterwards login lookup, email, OAuth tokens, authenticator secret and a stored API key all read with the new keys only. |
| 18 | Upgrade `vite` to 6+ and `react-router-dom` to 7 (clears the 4 `npm audit` findings). | done | 2026-09-30 | `vite` 7.3 (not 8: 8 swaps the bundler and needs a config rewrite; 7 clears the advisories), `@vitejs/plugin-react` 5, `react-router` 7 (imports moved from `react-router-dom`). `npm audit`: 0. Build and `tsc` pass. Clicked through 18 routes in Chromium against a seeded local API: no errors, and the admin second-factor gate works. That run found `/admin/roles` crashing because the permission catalogue sends only keys; fixed by deriving the label. Not checked: reader with real page images, admin import with a real source site. |

## PR F — Long-term maintenance

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 19 | Dependabot or Renovate config; keep the weekly dependency audit in CI. | done | 2026-09-30 | Fixed `dependabot.yml` (the npm entry pointed at a folder that does not exist, and ignored `react-scripts`, which is gone); it now covers pip, npm, GitHub Actions, base images and compose, and skips only the Vite 8 major on purpose. CI now also runs every Monday (dependency audit only), and the npm gate is `high` because the audit is clean. Not run on GitHub here: the schedule and Dependabot fire only there. |
| 20 | Frontend tests in CI: login, reader, admin import. | done | 2026-09-30 | Vitest + Testing Library + jsdom (`npm test`, run in CI before the build). 15 tests: login (`Login.test.jsx`), reader (`ChapterViewer.test.jsx`), admin series import (`SeriesManagement.test.jsx`) and the admin second-factor gate. They test the screens with the API mocked, not the API itself; the earlier browser click-through covered the real API. |
| 21 | Pin base images and dependencies; document how and when to update them. | done | 2026-09-30 | Base images pinned by digest (Python, Node, nginx, PostgreSQL, Redis) and npm dependencies pinned to exact versions (`.npmrc` `save-exact`); Python was already exact plus lock. How and when to update: `deployment/updating.md`. Both images built and the full stack ran healthy (see item 28). The digests are identical on ECR Public and Docker Hub. |
| 22 | Runbook: change of source domain, restore from backup, key rotation, adding a new source site. | done | 2026-09-30 | `deployment/runbook.md`: source domain change, restore from backup, key rotation (links `key-rotation.md`), adding a new source site. Restore and key rotation rehearsed on the compose stack: encrypted dump, scratch-database verification (51 tables match), a real restore after deleting data (series back, all services healthy), pictures restore verified. Source-domain change and adding a site need the real sites (items 24-26). |
| 23 | Move pictures to S3 or a CDN when the library outgrows the disk (design first). | done | 2026-09-30 | Design only, as the item says: `audit/storage-design.md` (trigger, options, recommended path, risks). Nothing built; the trigger is the storage report from item 12. |

## PR G — Real-site verification (Together with the owner)

These need the real source sites or accounts, which the build sandbox cannot
reach. The agent guides and fixes what the checks show.

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 24 | Run Test & Live Preview on one series per supported site; fix parsers from what it shows. | todo | | Sites: see `backend_fastapi/app/scrapers/presets.py`. |
| 25 | Import one real MangaUpdates link and check the metadata (the id decoding was never tried on the real site). | todo | | |
| 26 | Import one real two-page (book format) series and one long-strip series; check split, order and compression by eye. | todo | | |
| 27 | Configure an OCR and translation provider (Admin → API management) and translate one real chapter. | todo | | |
| 28 | `docker compose build` and `up`, then click through the site once (Docker images were never built in the sandbox). | done | 2026-09-30 | Built both images and ran the whole stack (API, PostgreSQL 14, Redis, 8 Celery workers, beat, nginx web): all healthy, all 9 queues consumed, 18 pages clicked through on the production build behind nginx with no errors. Found and fixed 3 start-up bugs (found later 30-32). Sandbox limits: `deb.debian.org` is blocked here, so the backend image was built without its `postgresql-client` step (the backup scripts ran from the host instead), and images came from Docker Hub instead of ECR Public (same digests). Build once on the server with `docker compose build` to cover that step. |

## PR H — Decision needed

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 29 | Public browsing: today everything except login pages requires login, so search engines cannot index series and ads reach logged-in users only. Proposed: browsing public, login only for bookmarks, ratings, comments and translation. | done | 2026-10-03, branch `claude/funny-gauss-k12tkr` | Owner decided: an owner-only switch (*Sign-in required*, Admin → Site Functions) that starts **off**; the owner switches it on once the Admins are in place. Bookmarks stay in the browser, so guests have them too. |

## Owner actions (not for the agent)

| # | Action | Status | Notes |
| --- | --- | --- | --- |
| U1 | Rotate the Google OAuth client secret that was committed in the old `Manga-Website` repository. | todo | Google Cloud console. |
| U2 | Make sure `ALLOW_PLAINTEXT_SECRETS` is not set on the production server. | todo | |
| U4 | Provide a Sentry (or similar) DSN (item 13). | todo | |

## Found later

| # | Item | Status | Done (date, PR) | Notes |
| --- | --- | --- | --- | --- |
| 30 | Every Celery worker and beat container ran a second copy of the API instead of Celery: compose's `command` is appended to the image `ENTRYPOINT` (`start_backend.sh`), which ignores it. No background job (scraping, compression, email, schedules) ever ran under compose. | done | 2026-09-30 | `entrypoint: []` on the workers and beat, in `docker-compose.yml` and the scale overlay (the migrate service already did this). Kubernetes was not affected (`command` replaces the entrypoint there). |
| 31 | The web container never started: `pid` was set both in `nginx.conf` and in the start command, and nginx refuses a duplicate. | done | 2026-09-30 | Removed it from the command in `web.Dockerfile` and `docker-compose.yml`. |
| 32 | `WEB_CONCURRENCY=` (blank) in `.env.example` crashed gunicorn at start-up (it parses the value as a number), so a backend configured from the example never served. | done | 2026-09-30 | Set to 4 (same as `GUNICORN_WORKERS`) with a note never to leave it blank. |
| 34 | `main` had two migration heads after PR #12 (`drop_custom_tabs`) and PR #13 (`admin_totp`) both followed `20261001_page_mirroring`: `alembic upgrade head` refused to run and CI on `main` went red. | done | 2026-09-30 | Merge revision `20261003_merge_totp_custom_tabs` joins them without changing either. Chain checked on an empty PostgreSQL 14 database; full backend suite passes on it. |
| 35 | Whole-site bug test (2026-10-03): 8 bugs found live and fixed (comment e-mails exposed, comment names, branding, sign-in link spent twice, reader title, missing icons and service worker, guest bell polling). | done | 2026-10-03, branch `claude/funny-gauss-k12tkr` | `audit/bug-test-2026-10-03.md` |
| 36 | "New chapter" notifications reach nobody: they go to server-side bookmarks, which no page creates. | blocked | | Owner decides: opt-in "follow this series" on the server, or drop it. BT-9 |
| 37 | Remove unused server code (`/bookmarks`, `/history`, `read_history`, `suggestion_service`) and ~60 unused API client functions. | todo | | BT-10 |
| 38 | Community, comment actions and notification preferences have a backend but no page. | todo | | BT-11 |
| 39 | Homepage header text saved only in the admin's browser. | todo | | BT-12 |
| 33 | The pinned `python:3.11-slim` digest is Debian 13 (trixie), not bookworm as before, so the image's `postgresql-client` is version 17. | todo | | Works with the PostgreSQL 14 server (newer `pg_dump` reads older servers). Check backups once on the server after the first real build. |

## Done log

| Date | What | Pull request |
| --- | --- | --- |
| 2026-09-30 | UI connected to the FastAPI backend, scraping, page compression, layouts | #4, #5 |
| 2026-09-30 | Repository tidy: unused files and custom tabs removed, audit and deployment files grouped | #6 |
