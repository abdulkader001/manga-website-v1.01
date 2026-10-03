# MAP.md — how this website is put together

> **For the next agent:** read this file, then [`plan.md`](plan.md). This file says *what exists and how
> it connects*; `plan.md` says *what is wrong and how to fix it*. Nothing in this map is guesswork:
> every route, table, task and file below was read from the code or produced by running it.
>
> | | |
> | --- | --- |
> | Written | 2026-10-03, on `main` at `c66dc92` (merge of PR #45) |
> | Size | backend `app/` ≈ 54,600 lines of Python in 40 routers, 93 services, 53 tables, 97 migrations, 44 Celery tasks; frontend `src/` ≈ 20,600 lines (React 18 + Vite 7 + React Router 7 + TanStack Query 5 + Tailwind 3) |
> | API surface | **306** route/method pairs under `/api/v1` (+ 3 SEO routes at the site root). The UI calls **151** of them; **12** more are reached by browser redirects, image tags or downloads; **143 have no caller at all** (see Appendix A) |
> | Checks on this commit | `ruff` clean · backend **1256 passed, 7 skipped** (PostgreSQL 16) · `tsc` clean · frontend **85 passed** · `vite build` OK · Alembic chain applies on an empty PostgreSQL and ends at one head (`20261017_login_required_default_off`) |
> | Regenerating the tables | Appendix A and B were generated from the running app and a migrated PostgreSQL (recipes are in `plan.md` §"How I tested"). If you change routes, tables or tasks, regenerate or edit them by hand |

---

## 1. The one-minute picture

```
 Reader's browser
      │  HTTPS
      ▼
 Caddy on the host  (TLS, Let's Encrypt)                    ← the documented live setup (GUIDE.md §8, Step 7)
      │  http://127.0.0.1:8080
      ▼
 web container: nginx :8080  (deployment/nginx/site.conf)
      │   • serves the built React app (dist/)  + /config.json (runtime API base)
      │   • /api/*, /sitemap.xml, /rss.xml, /feed.xml  → backend
      │   • /api/v1/manga/pages/*  and  /api/v1/manga/covers/*  → files straight from the storage volume (alias)
      ▼
 backend container: gunicorn + uvicorn workers :8000   (backend_fastapi.app.main:app, FastAPI)
      │                    │                       │
      ▼                    ▼                       ▼
 PostgreSQL 14        Redis 7                 volume app-storage → /app/storage
 (all data)           (cache, rate limits,     (pages/ covers/ branding/ profile_uploads/ backups …)
                       Celery broker/results)
      ▲                    ▲
      │                    │  queues: default, scrape, compress, ocr, translation, email, maintenance, notifications
      └──── Celery workers (8 containers, one queue each) + Celery beat (the schedule)
                 │
                 └──► source sites (scraping) · MangaUpdates · Anime-Planet · OCR/translation/AI providers
                      · SMTP (sign-in e-mails) · Google / Microsoft (sign-in) · S3-compatible storage (backups)
```

Other ways the same code runs:

| Mode | How | Notes |
| --- | --- | --- |
| Developer | `npm run dev` → `server.ts` (Express + Vite middleware on :3000) proxies `/api/*`, `/sitemap.xml`, `/rss.xml`, `/feed.xml` to `BACKEND_URL` (default `127.0.0.1:8000`); `npm run backend` runs uvicorn | No nginx, so no picture alias and no limits. `server.ts` also serves `/config.json` |
| Compose, local test | `docker compose up -d --build` with `.env` from `make_env.py --local` → `http://localhost:8080` | `FORCE_HTTPS_REDIRECTS=false` here |
| Compose, small server | `-f docker-compose.small.yml` | 2 Celery workers (solo pool) instead of 8; Postgres/Redis memory caps |
| Compose, scale | `-f backend_fastapi/deployment/docker-compose.scale.yml` | one worker per queue, scalable |
| Kubernetes | `backend_fastapi/deployment/k8s/*.yaml` | API, worker (+ compress worker), beat, migrate job |
| Host, no Docker | `deployment/manga-site.conf` + `manga-frontend.service`, `backend_fastapi/deployment/manga-*.service` | **Does not work as written** — see `plan.md` P1-9 |

---

## 2. What happens to a request

### 2.1 Front doors

| Hop | File | What it does to the request |
| --- | --- | --- |
| Caddy | (host; GUIDE.md §8) | TLS; sends `X-Forwarded-For`, `X-Forwarded-Proto: https` |
| web nginx | `deployment/nginx/site.conf`, `nginx.conf` | CSP + security headers; `limit_conn conn_per_ip 20`; `limit_req` zones `login_per_ip` (10 r/min, sign-in paths) and `img_per_ip` (30 r/s, burst 200, pictures); hotlink map (`$hotlink_blocked`); `client_max_body_size 10m` (0 for backup/geolock uploads); static assets cached 1 year; takes the visitor's address (`real_ip`, last `X-Forwarded-For` hop) and scheme (`$fwd_proto`) only from loopback/private proxies and passes them on; logs without visitor addresses (fixed P0-1 and P0-2 in `plan.md`) |
| Node gateway | `server.ts` | dev/`npm start` only: appends the peer to `X-Forwarded-For`, sets `x-forwarded-proto` from its own socket, proxies, no limits |
| gunicorn | `backend_fastapi/deployment/gunicorn.conf.py` | `uvicorn.workers.UvicornWorker`, `2×CPU+1` workers (or `GUNICORN_WORKERS`), timeout 180 s, recycles workers every ~2000 requests, access log to stdout |

### 2.2 Backend middleware (outermost first) — `bootstrap/middleware.py`

`CORS (LiveCORSMiddleware)` → `SecurityHeaders` → `Prometheus` → `Geolock` (451 for blocked countries) → `ForwardedHeaders` (scheme/host/port from `X-Forwarded-*` — **from any peer**; client IP only from a trusted peer, last hop) → `HTTPSRedirect` (when `FORCE_HTTPS_REDIRECTS`; `/health`, `/healthz` exempt) → `Timeout` (5 s default; OCR, translation, backups, geolock exempt) → `Backpressure` (500 concurrent) → `LegacyApiAliasDeprecation` → `Logging` (request id) → `GZip` → `MaintenanceMode` → `CSRF` (double-submit cookie) → `RateLimit` (300 requests / 60 s per client IP, Redis-backed with in-memory fallback, repeated violations block for 2×, 4×, … up to 1 h; `/health`, `/healthz`, `/metrics` exempt) → router.

Routers are mounted three times: `/api/v1` (canonical, documented), `/` and `/api` (deprecated aliases, hidden from the schema; the documented Google redirect address `…/api/auth/google/callback` still uses the `/api` alias). `seo_router` (sitemap/rss/feed) is mounted once at the root.

### 2.3 Sign-in and sessions

* Readers: **e-mail magic link, Google, Microsoft** — no passwords. One inbox = one account for life (canonical e-mail identity, `users.email_lookup_hash`). New accounts can be switched off (Site Function `new_registration`).
* Cookies: `access_token_cookie` (1 h), `refresh_token_cookie` (14 days by default, 1–30 set by the owner), `csrf_token` (readable by JS; sent back as `X-CSRF-Token`). `Authorization: Bearer` is also accepted (tests use it). Revoked tokens are listed in `revoked_tokens` (`/auth/logout?all=true` revokes every session).
* Frontend: `src/services/api.js` sends cookies + CSRF header, retries once after `POST /auth/refresh` on a 401 (only if a session existed), dispatches `admin-step-up-required` (403 `REVERIFICATION_REQUIRED`) and `region-blocked` (451) events.
* Admin area: the owner **must** enrol an authenticator (TOTP) before any admin page opens; every admin route then needs a **30-minute step-up cookie** (`services/admin_second_factor.py`, `routers/admin_2fa.py`, wrapper `components/AdminSecondFactor.jsx`). Owner powers additionally need a *fresh* code (`dependencies/powers.py`).

### 2.4 Who may do what (roles, powers, switches)

| Concept | Where it lives | One-line rule |
| --- | --- | --- |
| Four roles | `models/user.py` `UserRole`, `core/permissions.py` | **owner** (`PERMANENT`, legacy `ADMIN` alias; one person; untouchable) · **Admin** (`CO_ADMIN`, ≤ 2) · **sub-admin** (`SECONDARY`, many, within seats) · **user**. `MODERATOR` is retired |
| Permissions | `core/permissions.py` `_CATALOGUE` (57 keys) | effective = role default + the person's override; six capabilities are never grantable |
| Site-owner powers | `OWNER_POWERS` (16 keys: vault, admin settings, cache, purge, API management, scraper AI, role management, branding, donations, backups, geolock, reveal e-mail) | an Admin holds all but `manage_admin_settings`, `manage_cache`, `purge_site_data` by default; only the owner switches them (a code is needed to switch one *on*); sub-admins can never hold them |
| Seats / succession | `services/admin_roles.py`, `admin_succession.py`, `tasks/roles_tasks.py` | 50 sub-admin seats shared between Admins; each Admin has a line of two successors; automatic succession is owner-only and off by default |
| Tab access | `core/admin_tabs.py`, `routers/roles_tabs.py`, `pages/Admin/TabAccessPanel.jsx` | owner decides which admin tabs each Admin/sub-admin sees; a hidden tab also removes its permissions |
| Site Functions | `core/site_functions.py` (18 keys), `services/site_functions.py`, `dependencies/site_functions.py`, `routers/site_functions.py` | owner-only on/off switch per main function; enforced server-side (router dependency or explicit check) and mirrored by `useSiteFunctions` / `FunctionGate` in the UI |
| Sign-in required | `dependencies/site_access.py` (`require_site_access`) | **off by default**; when on, reading routes answer 401 to guests (auth, config, health and admin never do) |
| Visitor IPs | `utils/audit_logger.py`, `services/admin_service.py`, Site Functions `ip_owner_only` / `record_ips` | only the owner sees IPs (unless the owner switches `ip_owner_only` off); never logged by the app |

Guards used on routes (`dependencies/`): `get_current_user`, `get_optional_user`, `require_admin_user`, `require_main_admin_user`, `require_permission(key)` (staff holding a permission), `require_power(key)` (owner power; needs authenticator + fresh code), `require_vault_owner` / `require_vault_unlocked`, `require_processing_user` (OCR/translation), `require_site_access`, `require_function(key)`.

---

## 3. Repository layout

| Path | What is in it |
| --- | --- |
| `src/` | React UI (see §4). `src/test/` = Testing Library setup |
| `public/` | `sw.js` (service worker), `manifest.json`, `favicon.ico`, `logo192.png`, `logo512.png` |
| `index.html`, `vite.config.ts`, `vitest.config.ts`, `tsconfig.json` (`strict:false`, **`checkJs` off**), `tailwind.config.js`, `postcss.config.js` | frontend build |
| `server.ts` | dev/`npm start` gateway (see §2.1) |
| `backend_fastapi/app/` | the API and workers (see §5): `main.py` (app factory), `api/routers/` (40), `services/` (93), `models/` (12 files, 53 tables), `schemas/`, `core/`, `dependencies/`, `bootstrap/`, `utils/`, `tasks/` (13), `scrapers/` (16 + adapters), `repositories/`, `migrations/versions/` (97) |
| `backend_fastapi/tests/` | 161 test files, **1256 tests**, `_support/` helpers (route table, staff factory, an `httpx` stub — the suite does **not** run against the real `httpx`) |
| `backend_fastapi/scripts/` | `make_env.py`, `cli_bootstrap.py` (owner tools), `start_*.sh`, `wait_for_*`, `rotate_encryption_key.py`, `verify_alembic_chain.py`, `seed_bootstrap_state.py`, … |
| `backend_fastapi/deployment/` | gunicorn config, systemd units, k8s manifests, scale overlay, backup/restore/monitoring scripts, `backups.md` |
| `deployment/` | web image (`web.Dockerfile`), `nginx/` (the config the image really uses), `manga-site.conf` + `manga-frontend.service` (host nginx alternative), certbot files, `runbook.md`, `updating.md`, `key-rotation.md` |
| `docker-compose.yml`, `docker-compose.small.yml` | 14 services (below) |
| `alembic.ini` | points at `backend_fastapi/app/migrations` (no URL in the file: `DATABASE_URL` only) |
| `guide/` + `GUIDE.md` + `GOOGLE_LOGIN_SETUP.md` | owner-facing install/operate guides (path A: local test, path B: live server) |
| `AUDIT_LOG.md` | change ledger the project's `CLAUDE.md` requires for every PR |
| `audit/`, `backend_fastapi/audit/` | earlier audit reports, `ROADMAP.md`, fix guides |
| `.github/workflows/ci.yml` | CI (below), `dependabot.yml`, `scripts/npm-audit-gate.mjs` |

Compose services: `db` (postgres:14), `redis` (7), `manga-stack-migrate` (runs `alembic upgrade head` + `seed_bootstrap_state.py`, then exits), `backend` (:8000), `celery_worker` (queues `default,celery`), `celery_worker_scrape` (`scrape`), `…_compress`, `…_ocr`, `…_translation`, `…_email`, `…_maintenance`, `…_notifications`, `celery_beat`, `web` (:8080, storage mounted read-only). Volumes: `db-data`, `app-storage`.

---

## 4. The frontend (`src/`)

### 4.1 How it starts and talks to the API

* `src/index.jsx` sets the theme before first paint, renders `<AuthProvider><App/></AuthProvider>`, and registers `public/sw.js` in production builds.
* `src/app.js` = router + shell. Providers (outer → inner): React Query (`staleTime` 5 min, no refetch on focus) → `BrowserRouter` → `AntiTamperGuard` → `AdblockCheck` → `AdsProvider` → `RegionGate` (Geolock 451 notice) → `AppShell` (Navbar, two global ad sections, two ad placements, Footer, `BookmarkSync`, `HistorySync`, scroll helpers) → `ErrorBoundary` → routes. Admin pages are separate lazy chunks.
* `src/config.js`: API base = `/config.json` (`apiBase`, written by `deployment/nginx/entrypoint.sh` or by `server.ts`) → `VITE_API_BASE` → `/api/v1`. (`REACT_APP_*` names in the file never resolve under Vite.)
* `src/services/api.js`: `request()` (JSON, cookies, CSRF header, one silent refresh on 401, error envelope `{success:false,error:{code,message}}`), `apiFetch()` (raw `Response`, accepts old `/api/v1/…` prefixes), and the `api.*` helper tree (170 helpers; 74 are never called — several screens call `apiFetch("/api/v1/…")` directly instead, so there are two ways to call the API).
* `src/services/apiRegistry.js`: a browser-side catalogue of ~40 OCR/translation/AI provider presets (kept in `localStorage` key `manga_admin_api_registry_v1`) used by **API Management** next to the server's real providers.

### 4.2 Routes (`src/app.js`)

All routes except the auth entry pages sit under `AuthGuard followSiteSetting` (a guest passes only when the server says "Sign-in required" is off; a signed-in user with an incomplete profile is sent to `/complete-profile`).

| Path | Component | Extra guard | Data it loads |
| --- | --- | --- | --- |
| `/login` | `components/Login.js` | — | `GET /config/site-functions`; starts Google (`/auth/google`) or Microsoft (`/api/v1/auth/microsoft`) by full-page redirect, or `POST /auth/request-magic-link` |
| `/magic-link/:token`, `/login/magic/:token` | `pages/MagicLinkConsume.js` | — | `GET /auth/magic-link/{token}` (single use) |
| `/complete-profile` | `pages/CompleteProfile.js` | — | `GET /auth/check-username`, `POST /auth/complete-profile` |
| `/` | `Homepage.js` | follows sign-in switch | `GET /manga/?sort=latest&per_page=50`, `/announcements`, ads, branding, footer, support, site-functions, geo status; staff: `POST /admin/broadcast`, `DELETE /admin/announcements/{id}` |
| `/browse` | `BrowseManga.js` | same | `GET /manga/` (search, status, type, sort, page — nothing else) |
| `/manga/:mangaId` | `MangaDetail.js` | same | `GET /manga/{id}`, `/manga/{id}/chapters`, `/manga/{id}/chapter-titles`, `POST /manga/{id}/rate`, comments |
| `/reader/:mangaId/:chapterId` | `ChapterViewer.js` (+ `ReaderOverlay`, `OverlayBox`) | same | `GET /manga/{m}/chapters/{c}`, chapter list, titles, `GET /processing/chapter/{c}/page/{i}?target=` (signed-in, translation on), `POST /chapters/{c}/report`, staff: `GET /chapters/{c}/reports`, `POST /admin/chapters/{c}/rescrape`, `DELETE /admin/chapters/{c}/pages/{i}`, comments, reader settings |
| `/bookmarks` | `BookmarkHistoryTab.jsx` | same | `GET /manga/batch?ids=` (series cards for the ids held in the browser); library in `localStorage` |
| `/settings` | `pages/UserSettings.js` → `settings/SettingsPage.tsx` (+ `ReadingSettings.tsx`, `ProviderSection.tsx`) | signed in | `POST /auth/profile`, `GET /auth/check-username`, `GET/PUT /user/processing-settings` (via `useReaderSettings`), `GET /integrations/list`, `POST /integrations/{add,test}`, `DELETE /integrations/remove` |
| `/notifications` | `pages/NotificationsPage.js` | signed in | `GET /notifications`, mark read/delete |
| `/admin` | `pages/AdminPanel.js` | staff | `GET /health` (counts) and `GET /admin/permissions/me`; tiles come from `constants/adminFeatures.js` |
| `/admin/security` | `Admin/AdminSecurity.jsx` | staff | `/admin/2fa/*` |
| `/admin/series` | `Admin/SeriesManagement.jsx` | `edit_series` | public `GET /manga/` (the series list), `POST /admin/series` (import), `DELETE /admin/series/{id}`, `POST /admin/series/{id}/{rescrape,layout,schedule,mirror-images}`, `/admin/scraper/{ai-config,preview,parsers,parsers/generate,tasks/{id}}` |
| `/admin/chapter-reports` | `Admin/ChapterReports.jsx` | `handle_reports` | `GET /reports/chapters`, `POST /reports/{id}/resolve`, `DELETE /reports/{id}`, `POST /admin/reports/{id}/rescrape-single` |
| `/admin/users` | `Admin/UserDatabase.jsx` | `view_user_list` | `GET /admin/users/all` (every user, unpaginated), `POST /admin/{promote,demote}-secondary`, `GET/POST /admin/settings` (re-verification interval) |
| `/admin/roles` | `Admin/RoleManagement.jsx` (+ `TabAccessPanel.jsx`) | `manage_roles` | `/admin/roles/*`, `/admin/users/{id}/permissions*`, `/admin/permissions/*` |
| `/admin/ads`, `/admin/ad-slots` | `AdsManager.jsx`, `AdSlotsManager.jsx` | `manage_ads` | `/ad-slots*`, `/ads/global-networks*`, `/ads/placements` |
| `/admin/health`, `/admin/audit-report` | `Health.jsx`, `AuditReport.jsx` | `view_system_health` | `GET /health`, `POST /health/diagnostics`, cache/image purge buttons; `GET /admin/audit-report?range=` |
| `/admin/api-management` | `ApiManagement.jsx` | `view_providers` (owner power) | `/admin/api-registry*` |
| `/admin/settings` | `AdminSettings.jsx` (+ `DonationEditor`, `FooterEditor`) | `manage_admin_settings` (owner power) | `GET/POST /admin/settings`, `POST /branding`, `GET/POST /footer`, `/social-links*`, `/admin/maintenance/{delete-all-manga,purge-all-images}`, `POST /admin/settings/clear-cache` |
| `/admin/vault` | `SecretVault.jsx` | `manage_secret_vault` (owner power) | `/admin/vault*` |
| `/admin/backups` | `StorageBackups.jsx` | `manage_backups` (owner power) | `/admin/backups*` |
| `/admin/geolock` | `Geolock.jsx` | `manage_geolock` (owner power) | `/admin/geolock*` |
| `/admin/functions` | `SiteFunctions.jsx` | **owner only** (no permission opens it) | `/admin/site-functions*` |
| `*` | `NotFound.js` | — | — |

Admin pages that need the authenticator are wrapped in `AdminSecondFactor`. The owner-only tab list is `core/admin_tabs.py` (13 tabs); `tests/test_route_audit.py` fails when the frontend routes, the backend routes and the tab registry disagree.

### 4.3 Browser-side state

| What | Where | Notes |
| --- | --- | --- |
| Session | httpOnly cookies; `AuthContext` (`/auth/me`), `localStorage.mw_had_session` | `isAdmin` = owner tier (`admin`/`permanent_admin`/`is_main_admin`); `isSecondaryAdmin` = sub-admin **or** Admin (`co_admin`) |
| Staff powers | `useStaffPermissions` → `GET /admin/permissions/me` | `can(key)`; the owner always can |
| Site switches | `useSiteFunctions` → `GET /config/site-functions` (`FunctionGate`) | unknown/loading counts as "on" |
| Branding | `useBranding` → `GET /branding` | name, logo, homepage title |
| Reader settings | `useReaderSettings` → `GET/PUT /user/processing-settings` | translation overlay on/off, language, colours, text scale |
| **Library** | `localStorage.mw_library_v1` via `utils/library.js` | bookmarks, read chapters (id → time), last chapter per series, plus queues (`pending`, `readPending`, `clearPending`). The **browser is the main copy**; for a signed-in reader `BookmarkSync` (series ids → `/bookmarks`) and `HistorySync` (chapter ids + times → `/history/sync\|read`) mirror it to the account so a new device sees it. Guests stay local |
| Service worker | `public/sw.js` (registered in production) | cache-first for every image forever (`manga-reader-cache-v1`), network-first for the rest; no size limit or expiry |

### 4.4 File inventory

| Group | Files (lines) |
| --- | --- |
| Entry / shell | `index.jsx`, `app.js` (315), `config.js`, `server.ts` (153), `index.css`, `styles/mgeko.css` (689), `components/{Navbar 519, Footer 351, ScrollToTop*, ThemeToggle, ErrorBoundary, AntiTamperGuard 123, AdblockCheck, RegionGate}` |
| Reading | `Homepage.js` (1015), `BrowseManga.js` (780), `MangaDetail.js` (552), `ChapterViewer.js` (697) + `ChapterViewer.css`, `ReaderOverlay.js`, `OverlayBox.js`, `OverlayScaleControl.js`, `CommentSection.js`, `BookmarkHistoryTab.jsx`, `NotificationBell.js`, `NotificationsPage.js` |
| Account | `Login.js`, `MagicLinkConsume.js`, `CompleteProfile.js`, `AuthGuard.js`, `settings/SettingsPage.tsx` (578), `ReadingSettings.tsx`, `ProviderSection.tsx`, `BookmarkSync.jsx`, `HistorySync.jsx` |
| Ads / support | `GlobalAds.js`, `AdPlacement.js`, `SupportLinks.jsx`, `utils/urlValidator.ts` (client-side URL audit for ad links) |
| Admin | `pages/AdminPanel.js`, `pages/Admin/*.jsx` (16 pages, 1460-line `SeriesManagement` is the largest file), `AdminSecondFactor.jsx`, `FooterEditor.js` (645), `DonationEditor.jsx`, `ColorPicker.js`, `constants/adminFeatures.js` |
| Hooks / utils | `hooks/{useAuth,useBranding,useChapterTitles,useReaderSettings,useSiteFunctions,useStaffPermissions}.js`, `utils/{library 349,gstTime,color,favicon,mangaLinkMenu,maskEmail,notificationTargets,overlayText,placeholders}.js`, `fonts/overlayFonts.js` |
| Tests (21 files, 85 tests) | `components/{AdminSecondFactor,AuthGuard,BookmarkSync,ChapterViewer,CommentSection,HistorySync,Login,Navbar,OverlayBox,SupportLinks}.test.jsx`, `contexts/AuthContext.test.jsx`, `pages/MagicLinkConsume.test.jsx`, `pages/Admin/{RoleManagement,SeriesManagement,SiteFunctions,StorageGeolock,TabAccessPanel}.test.jsx`, `constants/adminFeatures.test.js`, `utils/{gstTime,mangaLinkMenu,overlayText}.test.js` — all with the API mocked; **no test for Homepage, BrowseManga, MangaDetail, Settings, Notifications, Footer, ads, or any admin page not listed** |

---

## 5. The backend (`backend_fastapi/app/`)

### 5.1 Start-up (`main.py` → `create_app()`)

1. `configure_logging()` (structlog, JSON) → `ensure_encrypted_env_loaded()` → `get_settings()` (`core/settings.py`, Pydantic; refuses to start in production with `ALLOW_PLAINTEXT_SECRETS`, without secure cookies, etc.).
2. `initialize_integration_vault(app)` and `secret_vault.refresh_if_stale()` apply the **Secret Vault** values (database table `vault_secrets`, encrypted with `INTEGRATIONS_SECRET`) over `.env` for every allow-listed key (`vault_keys.py`, 89 keys). A background task re-reads the vault every few seconds so a change made in another worker is picked up.
3. `initialize_provider_state()` builds the OCR/translation provider registry and the `features` flags (`ocr`, `translation`).
4. `init_sentry()` (only if `SENTRY_DSN`), `configure_middleware()` (§2.2), `setup_metrics()` (`/metrics`), exception handlers (error envelope `{success:false,error:{code,message,details}}`).
5. Root probes registered **before** the API routers so they win: `/`, `/health` (public, minimal), `/healthz`.
6. `register_api_routes()`: `/api/v1` + the two hidden aliases + the SEO router.
7. Lifespan: checks DB, opens Redis, Celery connection, shared HTTP client; optional Alembic drift check (`ALEMBIC_CHECK_ON_STARTUP`).

### 5.2 Routers (`api/routers/`, 40 modules, 306 route/method pairs)

Full per-route table with guards and UI usage: **Appendix A**. Summary by area:

| Area | Router modules | Main idea |
| --- | --- | --- |
| Reading | `manga` (list, `batch`, detail, chapters, chapter-titles, chapter content), `reader` (rate, like, report, announcements, bookmark import, **cover / page / image-proxy file routes**), `processing` (page OCR + translation), `comments`, `history`, `bookmarks`, `notifications`, `glossary`, `seo` | catalogue, reading, per-reader data |
| Accounts | `auth` (magic link, refresh, logout, Google, `/auth/me`, options), `account` (Microsoft, profile, username check), `user_settings`, `integrations` (a reader's own provider keys) | sign-in and profile |
| Admin core | `admin` (71 routes: series, domains/parsers, users, roles, rights/takedown, audit, scraping jobs), `site_admin` (34: announcements, chapter reports, ad networks, API registry, audit report, health diagnostics, maintenance, storage), `scraper_admin` (preview / parser generation tasks), `admin_2fa`, `roles_admins`, `roles_succession`, `roles_tabs`, `site_functions`, `secret_vault`, `backups_admin`, `geolock_admin` (+ public `/geo/status`), `branding`, `support`, `ad_slots`, `ads`, `cache_admin`, `health`, `system_stats`, `system_state`, `tasks`, `management` | owner/staff tools |
| Processing helpers | `ocr` (6), `translation` (3), `provider_management` (6) | older direct APIs; the reader uses `processing` only |
| Community | `community` (17: emojis, ranks, realms, pills, memes, GIF search, user moderation) | built, **no UI** |
| Legacy | `backup` (`/backup/create\|restore`, replaced by `backups_admin`) | still mounted |

### 5.3 Services (`services/`, 93 files) — by job

| Job | Key files |
| --- | --- |
| Catalogue payloads | `catalogue_service` (list/detail/chapter list, `enrich`, view counting), `manga_service` (filters, sorts, import checks), `chapter_title_service`, `content_rights` (hostable / translatable gates, takedown), `series_alerts` |
| Importing & scraping | `series_import`, `scraper_workflow_service`, `rescrape_service`, `scheduled_checks_service`, `source_health_service`, `scraper_health_service`, `parser_generation_service`, `scraper_ai_service`, `metadata_sources` + `mangaupdates_service` + `animeplanet_service`, `chapter_grouping`, `page_image_service` (download → WebP → `/app/storage/pages/<manga>/<chapter>/NNNN-<sha>.webp`), `cover_service` (`/app/storage/covers/<sha1>.webp`), `image_proxy` (signed `/images/proxy` for hotlink-protected sources), `pinned_fetch` + `url_guard` (SSRF-safe fetching) |
| Reader translation | `chapter_processing_service` (cache → plan → OCR → translate → overlay shape), `ocr_service`, `ocr_workflow`, `ai_vision_assist`, `translation_service`, `translation_cache_service`, `chapter_translation_service`, `bubble_shape`, `processing_plan`, `processing_settings_service`, `platform_ceiling_service`, `provider_resolver`, `provider_management_service`, `provider_registry`, `provider_config` |
| Accounts & roles | `auth_service`, `oauth_service`, `microsoft_oauth`, `email_service`, `disposable_email`, `admin_service`, `admin_roles`, `admin_succession`, `permissions_service`, `admin_second_factor`, `history_service`, `reputation_service`, `ranking_service` |
| Owner tools | `secret_vault`, `site_functions`, `site_content_service`, `donation_service`, `geolock`, `backup_service` (+ `backup_crypto`, `s3_storage`), `storage_report_service`, `cache_admin_service`, `ads_config_service`, `ad_placements`, `audit_service` |
| Community | `comment_service`, `comment_translation_service`, `meme_service`, `emoji_catalogue`, `notification_service` |
| Unused | `suggestion_service` (never called; its query would fail on the JSON column) |

### 5.4 Data (`models/`, 53 tables)

Grouped (Appendix B lists every foreign key and what happens when the parent row is deleted):

| Group | Tables |
| --- | --- |
| Catalogue | `manga` (35 cols), `chapters`, `read_history`, `bookmarks`, `manga_ratings`, `manga_daily_views`, `chapter_likes`, `chapter_reports`, `series_glossary_terms` |
| Accounts | `users` (47 cols), `login_tokens`, `revoked_tokens`, `user_api_keys`, `user_processing_settings`, `permission_overrides`, `permission_presets`, `admin_successors`, `admin_activity_days`, `admin_promotion_tokens`, `admin_bootstrap_state` (unused) |
| Settings & owner | `system_settings`, `system_state`, `site_functions`, `settings` (key/value: branding, footer, site content), `footer_settings`, `vault_secrets`, `admin_audit_logs`, `admin_task_results` (preview/parser jobs), `announcements`, `notifications`, `notification_preferences` |
| Scraping | `sources`, `scraping_jobs`, `approved_source_domains`, `parser_versions` |
| Translation | `ocr_cache`, `translation_cache` (per chapter page), `system_provider_instances` (providers & keys), `provider_credentials` |
| Ads | `ad_slots`, `ad_clicks`, `global_ad_providers` |
| Community (no UI) | `comments`, `comment_votes`, `comment_reactions`, `comment_translations`, `content_reports`, `custom_emojis`, `meme_uploads`, `pills`, `reputation_events`, `cultivation_realms`, `complaints` (unused) |

Notes: genres are a JSON array of strings **as the source gave them** (usually Title Case); chapter numbers are `DECIMAL(10,2)` (serialised as numbers; chapter `0` exists); naive-UTC timestamps (`datetime.utcnow()`), serialised without a `Z` in most payloads (the catalogue serialiser adds one) and parsed as UTC by `src/utils/gstTime.js::parseUtc`; e-mails are stored encrypted (`users.email`) with a hash (`email_hash`) and a fast lookup hash.

### 5.5 Background work (Celery)

* Broker/result backend: Redis. Prefork pool (solo pool in the small profile), `acks_late`, prefetch 1, retries (max 3, exponential backoff), dead-letter list `celery:dead_letter` in Redis, Sentry on workers.
* **Queues** (`task_routes`): `default` (cache refresh, echo), `scrape`, `compress` (picture download + WebP), `ocr`, `translation`, `email`, `maintenance`, `notifications`. Compose runs one worker per queue (`CELERY_QUEUES`); k8s runs one general worker for all but `compress`.
* The 44 tasks, their queue and schedule are in Appendix C. Beat entries: audit flush (5 min, **placeholder**), suggestion scan (hourly, **no-op**), stuck-job cleanup (15 min), scheduled scrape (15 min), scheduled chapter checks (30 min), manga-count metric, source-health, storage-usage, PDF integrity (daily), revoked-token purge (daily), content-report prune (daily), admin succession (daily), backup weekly check (hourly).

### 5.6 Scrapers (`scrapers/`)

`source_pipeline.py` (find parser → list chapters → pages), `presets.py` (built-in sites), `autodetect.py` (structure detection), `ai_fallback.py` + `ai_playbook.py` + `definition_guard.py` (Scraper AI parser generation with safety checks), `base_scraper.py`, `http_client.py` (SSRF-safe, size-capped), `packed_scripts.py` + `script_images.py` (script decoders), `parsing.py`, `config.py` (`ConfigManager`, parsers kept in the `settings` table), `adapters/example_adapter.py`. Domain approval (`approved_source_domains`) and parser versions (`parser_versions`: candidate → approved → active) gate what may be scraped.

### 5.7 Cross-cutting utilities (`utils/`)

`client_ip.py` (trusted-proxy aware client address), `rate_limiter.py` (generic IP limiter), `endpoint_limiter.py` (per-user/per-endpoint), `daily_limiter.py` (translation quotas), `csrf_middleware.py`, `swr_cache.py` (stale-while-revalidate cache: Redis + 10-s in-process cache), `cache_invalidation.py`, `bounded_threadpool.py` (DB and page pools), `audit_logger.py`, `crypto_utils.py` / `email_crypto.py`, `image_safety.py`, `malware_scanner.py`, `circuit_breaker.py`, `sanitizer.py` (bleach), `structured_logging.py`.

---

## 6. The owner's house rules, and where the code enforces them

| Rule (from `CLAUDE.md`) | Enforced / implemented in | Status found |
| --- | --- | --- |
| Only DB/Redis, site address, keys and admin identity stay in `.env`; everything else is in the Secret Vault | `vault_keys.py` (89 keys), `services/secret_vault.py`; ~78 infra-level names (paths, pool sizes, proxy CIDRs, Gunicorn/Celery tuning) are still `.env`-only | by design for infra; decide in `plan.md` Q-7 |
| Four roles; power only over a strictly lower tier | `core/permissions.py`, `permissions_service.assert_may_act_on`, `admin_roles.py` | tested (`test_four_roles`, …) |
| Owner powers need an authenticator + fresh code; sub-admins never hold them | `dependencies/powers.py`, `OWNER_POWERS`, `admin_second_factor.py` | tested |
| Seats, succession, tab access, "switch all powers off" | `admin_roles.py`, `admin_succession.py`, `roles_*` routers, `TabAccessPanel.jsx` | tested |
| Sign-in required off by default; sign-in/sign-up/admin never gated | `site_access.py`, migration `20261017`, `AuthGuard followSiteSetting` | works for the API; **pictures bypass it** (plan P1-2) |
| Site Functions + Tab access owner-only, every function has an enforcement point | `core/site_functions.py`, `tests/test_route_audit.py` | all 18 functions enforced |
| Visitors' IP addresses owner-only; never returned to others; never logged | `audit_logger.py`, `admin_service.py` (`source_ip` only for the owner unless the owner switches `ip_owner_only` off) | app code clean; **nginx and gunicorn access logs print the connecting address** (becomes a real visitor address once P0-2 is fixed) |
| Readers' history and bookmarks live in the browser; signed-in readers also keep series ids and chapter ids + times on the account, nothing else | `utils/library.js`, `BookmarkSync`, `HistorySync`, `history_service.py`, `routers/bookmarks.py` | as designed; see plan P2-9 for failure handling |
| No reader passwords; one inbox = one account | `auth.py`, `account.py`, `email_lookup_hash` | as designed (`users.password_hash` column still exists, unused) |
| Translation on the server through API providers (no in-browser models) | `processing` router, `provider_*` services | server side clean; **UI/CSP/docs still mention in-browser OCR** (plan P3-1) |
| Every PR adds an `AUDIT_LOG.md` entry; migrations get a §2 row; guide updated when install/operate changes | `CLAUDE.md` | the next PRs must follow it (see `plan.md` §"Rules for the fixing session") |

---

## 7. Key flows, step by step

### 7.1 A reader signs in with an e-mail link
1. `Login.js` → `POST /auth/request-magic-link {email}` (needs Site Function `sign_in_magic_link`; unknown address + registration closed = silent no-op; disposable e-mails rejected silently).
2. `auth_service.create_magic_token` stores only a hash; `tasks/email_tasks.send_magic_link` (queue `email`) sends `…/magic-link/{token}` (built from `FRONTEND_URL`; **without a worker on the `email` queue nothing is sent**).
3. Browser opens `/magic-link/:token` → `MagicLinkConsume` → `GET /auth/magic-link/{token}` (atomic single use) → sets the cookies → `/complete-profile` (name, username, birth date; birth date can't be changed later) or `/`.

### 7.2 A reader signs in with Google / Microsoft
`window.location` → `GET /auth/google` (`/auth/microsoft`) → provider → `GET /api/auth/google/callback` (`/api/v1/auth/microsoft/callback`) → account created or found → cookies → 302 to `MAGIC_LINK_REDIRECT_URL` (default: the home page; the old `…/auth/magic-complete` value redirects to `/`) or `FRONTEND_URL`.

### 7.3 Browsing and reading
`/` and `/browse` ask `GET /manga/` (Redis/in-process cached 60 s; cached payload shared between viewers, per-viewer fields added after). A series page asks detail + chapter list (+ titles). The reader asks the chapter (`pages` = our WebP URLs, or signed proxy / raw source URLs for chapters not mirrored yet), `record_chapter_view` counts the view (30-min de-dupe per signed-in reader only), then the browser loads `…/manga/pages/<manga>/<chapter>/<file>.webp` (nginx alias in Docker). `ChapterViewer` writes `recordRead()` to the library; for a signed-in reader `HistorySync` sends `POST /history/read`.

### 7.4 Page translation (signed-in, switch on, series translatable)
`ReaderOverlay` per page → `GET /processing/chapter/{id}/page/{i}?target=xx` → rights gate (`assert_series_translatable`) → provider plan (reader's own keys, then site providers, then env default) → shared `ocr_cache` / `translation_cache` → OCR (tesseract/provider) → translation → boxes + bubble shape + colours → drawn over the picture. No provider = HTTP 400 per page.

### 7.5 Admin imports a series
`SeriesManagement` → `POST /admin/scraper/preview` (task row `admin_task_results`, worker `run_source_task`, UI polls `GET /admin/scraper/tasks/{id}`) → `POST /admin/series {url, …}` creates a `scraping_jobs` row → `scrape_series_by_url` / `process_manga_scrape` (queue `scrape`) → metadata + cover → chapters → `mirror_chapter_pages` (queue `compress`) → `chapters.ingestion_status=complete`. Beat re-checks each series on its own schedule (`next_check_at`), and `series_alerts` notifies readers who bookmarked it.

### 7.6 Taken-down series (as implemented)
`POST /admin/series/{id}/takedown` sets `manga.takedown_status` and clears the caches. API reads then answer 451 to readers (staff still see it). **No screen calls it, nothing deletes the pictures, and picture URLs are not checked** (plan P1-2).

### 7.7 Backups
`Admin → Storage & Backups` → `/admin/backups*`: archives under the storage volume, optional password encryption (`backup_crypto`), optional copy to S3-compatible storage, weekly schedule (beat `backups-weekly-check`). Shell scripts under `backend_fastapi/deployment/` do Postgres/Redis/picture backups and restore drills.

---

## 8. Configuration, deployment files and the web server

### 8.1 Where a setting lives
`.env` (foundation only, `.env.example` is the template; `make_env.py` fills the secrets) → **Secret Vault** (Admin → Secret Vault, encrypted in `vault_secrets`, overrides `.env`, `SITE_DOMAIN` derives `FRONTEND_URL`, CORS origins, OAuth redirect addresses and `MAGIC_LINK_REDIRECT_URL`) → **Admin Settings / Site Functions** (rows in `system_settings`, `site_functions`, `settings`).

### 8.2 web nginx (`deployment/nginx/site.conf`) — location order matters

| Match | Does |
| --- | --- |
| `= /healthz` | proxy to backend `/healthz` |
| `~ ^/(sitemap.xml\|rss.xml\|feed.xml)$` | proxy |
| `^~ /api/v1/manga/pages/`, `^~ /api/v1/manga/covers/` | `alias /app/storage/{pages,covers}/`, hotlink map, `img_per_ip` limits, 1-year immutable cache — **no API, rights or sign-in check** |
| `~ ^/api/(v1/)?admin/(backups/(upload\|files/)\|geolock/database/upload)` | no body limit, no buffering, 1-hour timeouts |
| `~ ^/api/(v1/)?auth/(google\|callback\|request-magic-link\|magic\|magic-link)` | `login_per_ip` 10 r/min (Microsoft is not in the list) |
| `/api/` | proxy, `limit_conn 20` per IP |
| `~* \.(js\|css\|woff2?\|ttf\|eot\|otf\|ico\|png\|jpe?g\|gif\|svg\|webp\|avif\|wasm)$` | static files, 1-year immutable — **matches before `/api/` for any API URL ending in one of these extensions** (uploaded logos, profile pictures, memes → 404) |
| `= /index.html`, `= /config.json`, `~* \.map$`, `/` | no-cache; no-cache; 404; SPA fallback |

### 8.3 Other deployment files

| File | State |
| --- | --- |
| `docker-compose.yml` / `.small.yml` / `backend_fastapi/deployment/docker-compose.scale.yml` | consistent with each other and with `celery_app.task_routes` |
| `deployment/manga-site.conf`, `manga-frontend.service` | host-nginx alternative; **fails `nginx -t` (3 ways)**; also lacks the SEO proxy and caps every `/api/` call at 500/h and 2000/day per IP (pictures included) |
| `backend_fastapi/deployment/manga-*.service` | systemd units; the general worker has no `CELERY_QUEUES`, so only the `default` queue is served |
| `backend_fastapi/deployment/k8s/*.yaml` | consistent (worker lists every queue except `compress`, which has its own deployment) |
| `deployment/manga-certbot.*`, `renew_certificates.*` | certbot for the host-nginx variant |
| `backend_fastapi/deployment/*.sh`, `backups.md` | Postgres/Redis/picture backup, restore, verification, monitoring |

---

## 9. Tests and CI

| What | Where | Notes |
| --- | --- | --- |
| Backend | `backend_fastapi/tests/` (161 files, 1256 tests) | needs PostgreSQL for the full suite (CI uses `postgres:16`; the compose stack runs **14**); `conftest.py` stubs `httpx` and password hashing; most tests use SQLite-friendly paths; every genre fixture is lower-case (the real data is Title Case) |
| Frontend | `src/**/*.test.*` (85 tests, jsdom, API mocked) | see §4.4 for what is not covered |
| CI (`.github/workflows/ci.yml`) | `backend` (ruff, pytest on PG16, Alembic chain on an empty DB), `frontend` (`npm run lint` = `tsc --noEmit`, `npm test`, `npm run build`, no source maps, "no inline script" check), `dependencies` (pip-audit on the lock, npm audit gate) | the inline-script check cannot fail (plan P2-10); `tsc` does not type-check `.js/.jsx` (`checkJs` off); no ESLint; no nginx/compose/Docker validation |
| Browser/e2e | none in the repo | earlier audits clicked through manually (`audit/bug-test-2026-10-03.md`) |

---

## 10. Documentation index

| Document | Audience | Notes |
| --- | --- | --- |
| `GUIDE.md` (1,600+ lines), `guide/*.md` | owner/admin | install (Windows/macOS/Linux), live server, operate, update, troubleshoot |
| `AUDIT_LOG.md` | everyone | change ledger, migration ledger (§2), how to undo (§3), known limits (§5) |
| `README.md`, `backend_fastapi/README.md` | developers | the dev quick-start worker command is wrong (plan P3-6); README says `PAGE_MAX_WIDTH` 1280, code and `.env.example` 1440 |
| `audit/*`, `backend_fastapi/audit/*` | developers | earlier reports; some link to a `docs/` folder that is not in this repository |
| `deployment/runbook.md`, `updating.md`, `key-rotation.md`, `backend_fastapi/deployment/backups.md` | operators | |
| `CLAUDE.md` | agents | the working rules this repository sets |

---

## 11. Feature ledger — what is built, what has a screen, what is dead

| Feature | Server | Screen | State |
| --- | --- | --- | --- |
| Browse, series page, reader | yes | yes | works; several wrong behaviours (plan P1-3 … P1-8) |
| Bookmarks (browser + account), reading history (browser + account) | yes | yes | works; failed bookmark calls are dropped (plan P2-9) |
| Ratings, chapter reports (reader + admin triage), announcements | yes | yes | works; broadcast errors are hidden (plan P2-11) |
| Chapter **likes** | yes | **no button** (handler and state still in `ChapterViewer`) | dead UI code |
| Notifications (bell + page) | yes | yes | works; **preferences** API has no screen |
| Comments: list + post | yes | yes | works; edit, vote, react, report, moderate, moderation queue have no screen |
| **Community** (emojis, ranks, realms, pills, GIFs, memes, user block/timeout) | yes (17 routes) | **none** | switch `community` is **on** by default |
| Translation overlay | yes (`/processing`) | yes | needs a provider; 400 per page without one |
| Direct OCR / translation / glossary APIs (`/ocr/*`, `/translation/*`, `/manga/{id}/glossary`) | yes | **none** | reachable by any signed-in user; the reader does not use them |
| Reader's own provider keys | yes | yes (Settings → AI & OCR engines) | `PUT /user/api-keys` duplicate unused |
| Profile picture upload; account **export** and **delete** | yes | **none** | `DELETE /user/me` deactivates but keeps the encrypted e-mail |
| Takedown, rights records, taken-down notices | yes | **none** | and pictures stay reachable (plan P1-2) |
| Reveal a user's e-mail, revoke a user's sessions, flagged-user review | yes | **none** | |
| Audit log list/search, session policy, access config, cache admin, scheduled-checks dashboard, scraper/source health, storage report, mirror-all-images, bulk delete, batch schedule, approved domains, parser versions | yes | **none** | `AuditReport` shows a summary only |
| Logo **upload** | yes | **none** (URL or emoji only) | uploaded-file URLs would 404 behind the web nginx |
| Series import, schedule, layout, re-scrape, custom parser | yes | yes | works; delete fails on PostgreSQL once readers touched the series (plan P0-3) |
| Ads (slots, networks), support/donation links, footer, branding | yes | yes | duplicate fetches, doubled global ad (plan P2-7); several editors report success after an error |
| Secret Vault, Admin Settings, Site Functions, Roles, Tab access, 2FA | yes | yes | work |
| Storage & Backups | yes | yes | old `/backup/*` duplicate still mounted |
| Geolock | yes | yes | blind behind the current proxy chain; does not cover pictures |
| Sitemap, RSS | yes | n/a | not proxied by the host-nginx alternative |

**Unused code that can be deleted once the owner agrees:** `suggestion_service` + its beat task, `flush_audit` placeholder, `GET /config`, `GET /manga/browse` (sunset 2026-07-01), `/backup/*`, `/admin/ads`, `/ads/*` (legacy), the 74 uncalled helpers in `src/services/api.js`, the in-browser engine presets in `src/services/apiRegistry.js`, tables `admin_bootstrap_state` and `complaints`, 13 `Settings` fields, `users.password_hash`, the `REACT_APP_*`/PP-OCR/`POSTGRES_PASSWORD_FILE`/`SUPABASE_*` lines in `.env.example`.

---

## Appendix A — every API route

Generated by walking `build_api_router()` in the running app (306 route/method pairs; the three SEO routes `GET /sitemap.xml`, `/rss.xml`, `/feed.xml` are mounted at the site root and are public, gated by Site Function `sitemap_feeds` and the sign-in switch).

**Who can call it** — `public`; `login` (any signed-in user); `optional login`; `staff` (admin or sub-admin) plus `perm` (a permission the person holds) or `power` (an owner power: authenticator + fresh code); `owner`; `fn` = the Site Function that must be on; `gate: sign-in-required` = answers 401 to guests while the owner's switch is on; `IP login cap` = per-IP limiter on sign-in.
**Called by** — `UI` = a screen in `src/` really calls it (helpers executed against a stub to map each to its URL); `browser` = reached by a redirect, an `<img>` or a download link; `—` = nothing in this repository calls it (`legacy` = a duplicate of another route).

Totals: **151 UI · 12 browser · 143 nothing** (5 of those are legacy duplicates).

**`account`** (5)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/auth/check-username` | `check_username` | login | UI |
| POST | `/auth/complete-profile` | `complete_profile` | login | UI |
| POST | `/auth/profile` | `update_profile` | login | UI |
| GET | `/auth/microsoft` | `microsoft_login` | public | browser (redirect / image / download) |
| GET | `/auth/microsoft/callback` | `microsoft_callback` | public | browser (redirect / image / download) |

**`admin`** (71)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/settings` | `get_admin_settings` | staff, power `manage_admin_settings` | UI |
| POST | `/admin/database/alembic-status` | `trigger_alembic_status` | staff, power `manage_admin_settings` | — nothing |
| GET | `/admin/validate-ocr-providers` | `validate_ocr_providers` | staff, power `view_providers` | — nothing |
| GET | `/admin/system-providers` | `get_system_providers` | staff, power `view_providers` | — nothing |
| GET | `/admin/system-providers/{service}/secret` | `get_system_provider_secret` | staff, power `manage_providers` | — nothing |
| PUT | `/admin/system-providers` | `update_system_provider` | staff, power `manage_providers` | — nothing |
| GET | `/admin/scraper/ai-config` | `get_scraper_ai_config` | staff, power `configure_scraper_ai` | UI |
| POST | `/admin/scraper/ai-config` | `save_scraper_ai_config` | staff, power `configure_scraper_ai` | UI |
| POST | `/admin/system-providers/scraper-ai/test` | `test_scraper_ai` | staff, power `configure_scraper_ai` | — nothing |
| PATCH | `/admin/system-settings` | `update_system_settings` | staff, power `manage_admin_settings` | — nothing |
| GET | `/admin/ads` | `get_ads_config` | perm `manage_ads`, login | — nothing |
| POST | `/admin/ads` | `update_ads_config` | staff, power `manage_ads` | — nothing |
| GET | `/admin/approved-domains` | `list_approved_domains` | perm `view_websites`, login | — nothing |
| POST | `/admin/approved-domains` | `create_approved_domain` | perm `approve_website`, login | — nothing |
| DELETE | `/admin/approved-domains/{domain_id}` | `delete_approved_domain` | perm `remove_website`, login | — nothing |
| PUT | `/admin/approved-domains/{domain_id}/status` | `set_website_status` | staff, power `approve_website` | — nothing |
| GET | `/admin/parsers/{domain}` | `list_parser_versions` | perm `view_websites`, login | — nothing |
| POST | `/admin/parsers/{domain}/candidates` | `create_parser_candidate` | staff, power `approve_parser` | — nothing |
| POST | `/admin/parsers/versions/{version_id}/approve` | `approve_parser_version` | staff, power `approve_parser` | — nothing |
| POST | `/admin/parsers/versions/{version_id}/reject` | `reject_parser_version` | staff, power `approve_parser` | — nothing |
| POST | `/admin/parsers/{domain}/generate` | `generate_parser` | staff, power `trigger_scraper_ai` | — nothing |
| POST | `/admin/parsers/{domain}/rollback` | `rollback_parser` | staff, power `rollback_parser` | — nothing |
| PUT | `/admin/approved-domains/{domain_id}/check-settings` | `update_website_check_settings` | perm `modify_website`, login | — nothing |
| PUT | `/admin/series/{manga_id}/check-override` | `set_series_check_override` | staff, perm `edit_series` | — nothing |
| GET | `/admin/scrapers/scheduled-checks/dashboard` | `scheduled_checks_dashboard` | perm `view_scraper_health`, login | — nothing |
| GET | `/admin/scrapers/health` | `scrapers_health` | perm `view_scraper_health`, login | — nothing |
| GET | `/admin/users/flagged` | `list_flagged_users` | perm `view_user_list`, login | — nothing |
| POST | `/admin/users/{user_id}/flag-review` | `review_flagged_user` | staff, perm `ban_account` | — nothing |
| POST | `/admin/users/{user_id}/revoke-sessions` | `revoke_user_sessions` | perm `revoke_user_sessions`, login | — nothing |
| GET | `/admin/notifications` | `list_admin_notifications` | staff | — nothing |
| PUT | `/admin/approved-domains/{domain_id}/rights` | `update_domain_rights` | staff, power `modify_website` | — nothing |
| GET | `/admin/series/{manga_id}/rights` | `get_series_rights` | perm `edit_series`, login | — nothing |
| PUT | `/admin/series/{manga_id}/rights` | `update_series_rights` | staff, power `set_rights_records` | — nothing |
| POST | `/admin/series/{manga_id}/takedown` | `set_series_takedown` | staff, power `set_takedown` | — nothing |
| GET | `/admin/config/session` | `get_session_policy` | perm `set_session_policy`, login | — nothing |
| PUT | `/admin/config/session` | `update_session_policy` | perm `set_session_policy`, login | — nothing |
| GET | `/admin/config/access` | `get_site_access` | **owner** | — nothing |
| PUT | `/admin/config/access` | `update_site_access` | **owner** | — nothing |
| GET | `/admin/permissions/me` | `my_permissions` | login | UI |
| GET | `/admin/permissions/catalogue` | `get_permission_catalogue` | staff, power `manage_roles` | UI |
| GET | `/admin/users/{user_id}/permissions` | `get_user_permissions` | staff, power `manage_roles` | UI |
| PUT | `/admin/users/{user_id}/permissions` | `set_user_permissions` | staff, power `manage_roles` | UI |
| POST | `/admin/users/{user_id}/permissions/reset` | `reset_user_permissions` | staff, power `manage_roles` | UI |
| GET | `/admin/permissions/presets` | `get_permission_presets` | staff, power `manage_roles` | UI |
| POST | `/admin/permissions/presets` | `create_permission_preset` | staff, power `manage_roles` | — nothing |
| POST | `/admin/users/{user_id}/permissions/apply-preset` | `apply_permission_preset` | staff, power `manage_roles` | UI |
| GET | `/admin/permissions/managed` | `list_managed_permissions` | staff, power `manage_roles` | UI |
| POST | `/admin/series/scrape` | `preview_series_scrape` | perm `submit_manga_url`, login | — nothing |
| POST | `/admin/series` | `create_series_by_url` | perm `submit_manga_url`, fn `scraper`, login | UI |
| GET | `/admin/series/{manga_id}/ingestion` | `series_ingestion_progress` | perm `submit_manga_url`, login | — nothing |
| GET | `/admin/users/{user_id}/email` | `reveal_user_email` | staff, power `reveal_user_email` | — nothing |
| GET | `/admin/status` | `get_status` | staff | — nothing |
| GET | `/admin/users` | `list_users` | perm `view_user_list`, login | — nothing |
| GET | `/admin/users/all` | `list_users_legacy_alias` | perm `view_user_list`, login | UI |
| POST | `/admin/promote-secondary` | `promote_secondary_admin` | staff, power `promote_secondary` | UI |
| POST | `/admin/demote-secondary` | `demote_secondary_admin` | staff, power `demote_secondary` | UI |
| POST | `/admin/demote-main` | `demote_main_admin` | **owner** | — nothing |
| POST | `/admin/promote/{user_id}` | `promote_user` | staff, power `promote_secondary` | — nothing |
| POST | `/admin/demote/{user_id}` | `demote_user` | staff, power `demote_secondary` | — nothing |
| POST | `/admin/promote-by-email` | `promote_by_email` | staff, power `promote_secondary` | — nothing |
| POST | `/admin/demote-by-email` | `demote_by_email` | staff, power `demote_secondary` | — nothing |
| GET | `/admin/audit/logs` | `list_audit_logs` | staff | — nothing |
| GET | `/admin/audit/logs/search` | `search_audit_logs` | staff | — nothing |
| GET | `/admin/series` | `list_series` | staff, power `edit_series` | — nothing |
| DELETE | `/admin/series/{manga_id}` | `delete_series` | perm `delete_series`, login | UI |
| POST | `/admin/series/bulk-delete` | `bulk_delete_series` | staff, power `delete_series` | — nothing |
| GET | `/admin/scraping-jobs` | `list_scraping_jobs` | perm `view_scraper_health`, login | — nothing |
| GET | `/admin/admin-tokens` | `list_admin_tokens` | **owner** | — nothing |
| POST | `/admin/series/{manga_id}/rescrape` | `rescrape_series` | fn `scraper`, perm `rescrape_series`, login | UI |
| POST | `/admin/series/{manga_id}/rescrape/rollback` | `rollback_series_rescrape` | staff, power `rollback_series` | — nothing |
| POST | `/admin/chapters/{chapter_id}/rescrape` | `rescrape_chapter` | fn `scraper`, perm `rescrape_chapter`, login | UI |

**`admin_2fa`** (5)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/2fa/status` | `two_factor_status` | staff | UI |
| POST | `/admin/2fa/setup` | `two_factor_setup` | staff | UI |
| POST | `/admin/2fa/enable` | `two_factor_enable` | staff | UI |
| POST | `/admin/2fa/verify` | `two_factor_verify` | staff | UI |
| POST | `/admin/2fa/disable` | `two_factor_disable` | staff | UI |

**`site_functions`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/site-functions` | `list_functions` | **owner** | UI |
| PUT | `/admin/site-functions/{key}` | `switch_function` | **owner** | UI |

**`roles_tabs`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/roles/tab-access` | `tab_access_overview` | **owner** | UI |
| PUT | `/admin/roles/tab-access/{user_id}` | `set_tab_access` | **owner** | UI |

**`support`** (3)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/support` | `public_support_links` | fn `support_links`, optional login, gate: sign-in-required | UI |
| GET | `/admin/support` | `admin_support_links` | staff, power `manage_donations` | — nothing |
| PUT | `/admin/support` | `update_support_links` | staff, power `manage_donations` | UI |

**`ad_slots`** (6)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/ad-slots` | `list_ad_slots` | fn `ads`, optional login, gate: sign-in-required | UI |
| GET | `/ad-slots/{slot_id}` | `get_ad_slot` | fn `ads`, optional login, gate: sign-in-required | — nothing |
| POST | `/ad-slots` | `create_ad_slot` | perm `manage_ads`, login | UI |
| PATCH | `/ad-slots/{slot_id}` | `update_ad_slot` | perm `manage_ads`, login | UI |
| PUT | `/ad-slots/{slot_id}` | `update_ad_slot` | perm `manage_ads`, login | — nothing |
| DELETE | `/ad-slots/{slot_id}` | `delete_ad_slot` | perm `manage_ads`, login | UI |

**`ads`** (5)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/ads/` | `list_ads_root` | fn `ads`, gate: sign-in-required | — legacy / duplicate |
| GET | `/ads/slots` | `list_ads_slots` | fn `ads`, gate: sign-in-required | — nothing |
| GET | `/ads/placements` | `list_ad_placements` | fn `ads`, gate: sign-in-required | UI |
| GET | `/ads/config` | `fetch_ads_config` | fn `ads`, gate: sign-in-required | — nothing |
| POST | `/ads/click/{slot_id}` | `track_click` | fn `ads`, optional login, gate: sign-in-required | — nothing |

**`auth`** (12)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/auth/refresh` | `refresh_tokens` | public | — nothing |
| GET | `/auth/me` | `read_me` | login | UI |
| POST | `/auth/request-magic-link` | `request_magic_link` | fn `sign_in_magic_link` | UI |
| POST | `/auth/magic/request` | `request_magic_link_v2` | fn `sign_in_magic_link` | — legacy / duplicate |
| GET | `/auth/magic-link/{token}` | `consume_magic_link` | public | UI |
| GET | `/auth/magic/verify` | `verify_magic_link` | public | — legacy / duplicate |
| POST | `/auth/logout` | `logout` | public | UI |
| GET | `/auth/options` | `auth_options` | public | — nothing |
| GET | `/auth/google` | `google_login` | IP login cap | browser (redirect / image / download) |
| GET | `/auth/google/callback` | `google_callback` | IP login cap | browser (redirect / image / download) |
| GET | `/auth/callback` | `google_callback_legacy` | IP login cap | browser (redirect / image / download) |
| GET | `/auth/{provider}` | `login_provider` | public | UI |

**`backup`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/backup/create` | `create_backup` | staff, power `manage_backups` | — nothing |
| POST | `/backup/restore` | `restore_backup` | staff, power `manage_backups` | — nothing |

**`bookmarks`** (6)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/bookmarks` | `list_bookmarks` | login, gate: sign-in-required | UI |
| GET | `/bookmarks/` | `list_bookmarks` | login, gate: sign-in-required | UI |
| POST | `/bookmarks` | `add_bookmark` | login, gate: sign-in-required | UI |
| POST | `/bookmarks/` | `add_bookmark` | login, gate: sign-in-required | UI |
| DELETE | `/bookmarks/{manga_id}` | `delete_bookmark_for_manga` | login, gate: sign-in-required | UI |
| DELETE | `/bookmarks/by-id/{bookmark_id}` | `delete_bookmark_by_id` | login, gate: sign-in-required | — legacy / duplicate |

**`branding`** (8)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/branding` | `get_branding` | public | UI |
| POST | `/branding` | `update_branding` | staff, power `configure_branding` | UI |
| PUT | `/branding` | `update_branding` | staff, power `configure_branding` | — nothing |
| POST | `/branding/logo` | `upload_branding_logo` | staff, power `configure_branding` | — nothing |
| GET | `/branding/assets/{filename}` | `serve_branding_asset` | public | browser (redirect / image / download) |
| GET | `/footer` | `get_footer` | public | UI |
| POST | `/footer` | `update_footer` | staff, power `configure_branding` | UI |
| PUT | `/footer` | `update_footer` | staff, power `configure_branding` | — nothing |

**`cache_admin`** (4)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/cache` | `get_cache_admin_overview` | staff, power `manage_cache` | — nothing |
| PATCH | `/admin/cache/priority` | `update_cache_priority` | staff, power `manage_cache` | — nothing |
| POST | `/admin/cache/clear` | `clear_cache` | staff, power `manage_cache` | — nothing |
| POST | `/admin/cache/refresh` | `refresh_cache` | staff, power `manage_cache` | — nothing |

**`config`** (3)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/config/providers` | `list_providers` | public | — nothing |
| GET | `/config/site-functions` | `public_site_functions` | public | UI |
| GET | `/config/site-access` | `site_access` | public | UI |

**`integrations`** (4)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/integrations/list` | `list_integrations` | login | UI |
| POST | `/integrations/add` | `add_integration` | login | UI |
| DELETE | `/integrations/remove` | `remove_integration` | login | UI |
| POST | `/integrations/test` | `test_integration` | login | UI |

**`health`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/health` | `get_health` | staff, power `view_system_health` | UI |
| GET | `/health/security` | `get_security_status` | staff, power `view_system_health` | — nothing |

**`history`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/history/read` | `mark_chapter_read` | login, gate: sign-in-required | UI |
| POST | `/history/sync` | `sync_history` | login, gate: sign-in-required | UI |

**`system_stats`** (1)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/system/stats` | `get_system_stats` | staff, power `view_system_health` | — nothing |

**`management`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/version` | `get_version` | public | — nothing |
| GET | `/config` | `get_config` | staff, power `manage_admin_settings` | — nothing |

**`comments`** (11)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/comments/config` | `get_comment_config` | fn `comments`, gate: sign-in-required | — nothing |
| GET | `/comments/moderation/reports` | `list_reports` | fn `comments`, perm `handle_reports`, login, gate: sign-in-required | — nothing |
| GET | `/comments/{target_type}/{target_id}` | `list_comments` | fn `comments`, optional login, gate: sign-in-required | UI |
| POST | `/comments/` | `add_comment` | fn `comments`, login, gate: sign-in-required | UI |
| PATCH | `/comments/{comment_id}` | `edit_comment` | fn `comments`, login, gate: sign-in-required | — nothing |
| DELETE | `/comments/{comment_id}` | `delete_comment` | fn `comments`, login, gate: sign-in-required | — nothing |
| POST | `/comments/{comment_id}/vote` | `vote_comment` | fn `comments`, login, gate: sign-in-required | — nothing |
| POST | `/comments/{comment_id}/react` | `react_to_comment` | fn `comments`, login, gate: sign-in-required | — nothing |
| POST | `/comments/{comment_id}/report` | `report_comment` | fn `comments`, login, gate: sign-in-required | — nothing |
| POST | `/comments/{comment_id}/remove` | `moderator_remove_comment` | fn `comments`, perm `remove_comments`, login, gate: sign-in-required | — nothing |
| POST | `/comments/moderation/reports/{report_id}/resolve` | `resolve_report` | fn `comments`, perm `handle_reports`, login, gate: sign-in-required | — nothing |

**`community`** (17)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/community/emojis` | `list_emojis` | fn `community`, gate: sign-in-required | — nothing |
| POST | `/community/emojis/custom` | `add_custom_emoji` | staff, fn `community`, power `manage_community`, gate: sign-in-required | — nothing |
| DELETE | `/community/emojis/custom/{emoji_id}` | `remove_custom_emoji` | staff, fn `community`, power `manage_community`, gate: sign-in-required | — nothing |
| GET | `/community/rank/me` | `get_my_rank` | fn `community`, login, gate: sign-in-required | — nothing |
| GET | `/community/rank/{user_id}` | `get_user_rank` | fn `community`, gate: sign-in-required | — nothing |
| GET | `/community/realms` | `list_realms` | fn `community`, gate: sign-in-required | — nothing |
| PATCH | `/community/realms/{realm_id}` | `update_realm` | staff, fn `community`, power `manage_community`, gate: sign-in-required | — nothing |
| GET | `/community/pills` | `list_my_pills` | fn `community`, login, gate: sign-in-required | — nothing |
| POST | `/community/pills/{pill_id}/claim` | `claim_pill` | fn `community`, login, gate: sign-in-required | — nothing |
| POST | `/community/users/{user_id}/block` | `block_user` | fn `community`, perm `block_user`, login, gate: sign-in-required | — nothing |
| POST | `/community/users/{user_id}/unblock` | `unblock_user` | fn `community`, perm `block_user`, login, gate: sign-in-required | — nothing |
| POST | `/community/users/{user_id}/timeout` | `timeout_user` | fn `community`, perm `timeout_user`, login, gate: sign-in-required | — nothing |
| GET | `/community/gifs/search` | `search_gifs` | fn `community`, login, gate: sign-in-required | — nothing |
| POST | `/community/memes` | `upload_meme` | fn `community`, login, gate: sign-in-required | — nothing |
| GET | `/community/memes/file/{filename}` | `serve_meme_file` | fn `community`, gate: sign-in-required | browser (redirect / image / download) |
| DELETE | `/community/memes/{meme_id}` | `remove_meme` | fn `community`, perm `moderate_images`, login, gate: sign-in-required | — nothing |
| POST | `/community/memes/{meme_id}/report` | `report_meme` | fn `community`, login, gate: sign-in-required | — nothing |

**`manga`** (7)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/manga/` | `list_manga` | optional login, gate: sign-in-required | UI |
| GET | `/manga/browse` | `browse_manga` | optional login, gate: sign-in-required | — legacy / duplicate |
| GET | `/manga/batch` | `get_manga_batch` | optional login, gate: sign-in-required | UI |
| GET | `/manga/{manga_id}` | `get_manga_detail` | optional login, gate: sign-in-required | UI |
| GET | `/manga/{manga_id}/chapters` | `get_chapter_list` | optional login, gate: sign-in-required | UI |
| GET | `/manga/{manga_id}/chapter-titles` | `get_chapter_titles` | optional login, gate: sign-in-required | UI |
| GET | `/manga/{manga_id}/chapters/{chapter_id}` | `get_chapter_content` | optional login, gate: sign-in-required | UI |

**`glossary`** (3)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/manga/{manga_id}/glossary` | `list_glossary` | perm `correct_translation`, login, gate: sign-in-required | — nothing |
| PUT | `/manga/{manga_id}/glossary` | `upsert_glossary_term` | perm `correct_translation`, login, gate: sign-in-required | — nothing |
| DELETE | `/manga/{manga_id}/glossary` | `delete_glossary_term` | perm `correct_translation`, login, gate: sign-in-required | — nothing |

**`notifications`** (7)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/notifications` | `list_notifications` | fn `notifications`, login | UI |
| GET | `/notifications/unread-count` | `get_unread_count` | fn `notifications`, login | UI |
| POST | `/notifications/{notification_id}/read` | `mark_notification_read` | fn `notifications`, login | UI |
| POST | `/notifications/read-all` | `mark_all_notifications_read` | fn `notifications`, login | UI |
| DELETE | `/notifications/{notification_id}` | `dismiss_notification` | fn `notifications`, login | UI |
| GET | `/users/me/notification-prefs` | `get_notification_prefs` | fn `notifications`, login | — nothing |
| PUT | `/users/me/notification-prefs` | `update_notification_prefs` | fn `notifications`, login | — nothing |

**`ocr`** (6)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/ocr/image` | `extract_text` | fn `ocr`, login (processing), optional login | — nothing |
| GET | `/ocr/overlay` | `overlay_boxes` | fn `ocr`, login (processing), optional login | — nothing |
| POST | `/ocr/translate-overlay` | `translate_overlay` | fn `ocr`, login (processing), optional login | — nothing |
| POST | `/ocr/translate-upload` | `translate_upload` | fn `ocr`, login (processing), optional login | — nothing |
| POST | `/ocr/overlay-jobs` | `submit_overlay_translation_job` | fn `ocr`, login (processing), optional login | — nothing |
| GET | `/ocr/jobs/{job_id}` | `get_ocr_job` | fn `ocr`, login | — nothing |

**`processing`** (1)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/processing/chapter/{chapter_id}/page/{page_index}` | `process_chapter_page` | fn `ocr`, login (processing), optional login | UI |

**`provider_management`** (6)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/providers` | `list_providers` | staff, power `view_providers` | — nothing |
| POST | `/admin/providers` | `create_provider` | staff, power `manage_providers` | — nothing |
| PATCH | `/admin/providers/{provider_pk}` | `update_provider` | staff, power `manage_providers` | — nothing |
| DELETE | `/admin/providers/{provider_pk}` | `delete_provider` | staff, power `manage_providers` | — nothing |
| POST | `/admin/providers/{provider_pk}/test` | `test_provider` | staff, power `manage_providers` | — nothing |
| POST | `/admin/providers/health-check` | `health_check_all` | staff, power `manage_providers` | — nothing |

**`system_state`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/system/state` | `system_state_status` | public | — nothing |
| GET | `/system/health` | `system_health` | public | — nothing |

**`tasks`** (1)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/tasks/test` | `enqueue_test_task` | staff, power `view_system_health` | — nothing |

**`translation`** (3)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/translation/text` | `translate_text` | fn `translation`, login (processing), optional login | — nothing |
| POST | `/translation/jobs` | `submit_translation_job` | fn `translation`, login (processing), optional login | — nothing |
| GET | `/translation/jobs/{job_id}` | `get_translation_job` | fn `translation`, login | — nothing |

**`user_settings`** (12)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/user/settings` | `get_user_settings` | login | — nothing |
| PUT | `/user/settings` | `update_user_settings` | login | — nothing |
| POST | `/user/settings` | `update_user_settings` | login | — nothing |
| GET | `/user/processing-settings` | `get_processing_settings` | login | UI |
| PUT | `/user/processing-settings` | `update_processing_settings` | login | UI |
| PATCH | `/user/processing-settings` | `update_processing_settings` | login | — nothing |
| GET | `/user/overlay-fonts` | `get_overlay_fonts` | public | — nothing |
| PUT | `/user/api-keys` | `update_user_api_keys` | login | — nothing |
| POST | `/user/profile-image` | `upload_profile_image` | login | — nothing |
| GET | `/user/profile-image/{filename}` | `serve_profile_image` | login | browser (redirect / image / download) |
| GET | `/user/me/export` | `export_my_data` | login | — nothing |
| DELETE | `/user/me` | `delete_my_account` | login | — nothing |

**`reader`** (9)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/manga/{manga_id}/rate` | `rate_manga` | login, gate: sign-in-required | UI |
| POST | `/chapters/{chapter_id}/like` | `toggle_chapter_like` | login, gate: sign-in-required | UI |
| POST | `/chapters/{chapter_id}/report` | `report_chapter` | fn `chapter_reports`, login, gate: sign-in-required | UI |
| GET | `/chapters/{chapter_id}/reports` | `chapter_alerts` | optional login, gate: sign-in-required | UI |
| GET | `/announcements` | `list_announcements` | gate: sign-in-required | UI |
| POST | `/bookmarks/import` | `import_bookmarks` | login, gate: sign-in-required | UI |
| GET | `/manga/covers/{filename}` | `serve_cover` | gate: sign-in-required | browser (redirect / image / download) |
| GET | `/manga/pages/{manga_id}/{chapter_id}/{filename}` | `serve_page_image` | gate: sign-in-required | browser (redirect / image / download) |
| GET | `/images/proxy` | `proxy_image` | gate: sign-in-required | browser (redirect / image / download) |

**`site_admin`** (34)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/social-links` | `list_social_links` | public | — nothing |
| POST | `/social-links` | `save_social_links` | staff, power `configure_branding` | UI |
| POST | `/social-links/add` | `add_social_link` | staff, power `configure_branding` | UI |
| PATCH | `/social-links/{link_id}` | `update_social_link` | staff, power `configure_branding` | — nothing |
| PUT | `/social-links/{link_id}` | `update_social_link` | staff, power `configure_branding` | UI |
| DELETE | `/social-links/{link_id}` | `delete_social_link` | staff, power `configure_branding` | UI |
| POST | `/admin/broadcast` | `broadcast_announcement` | perm `broadcast`, login | UI |
| DELETE | `/admin/announcements/{announcement_id}` | `delete_announcement` | perm `broadcast`, login | UI |
| GET | `/reports/chapters` | `list_chapter_reports` | perm `handle_reports`, login | UI |
| POST | `/reports/{report_id}/resolve` | `resolve_chapter_report` | perm `handle_reports`, login | UI |
| DELETE | `/reports/{report_id}` | `delete_chapter_report` | perm `handle_reports`, login | UI |
| POST | `/admin/reports/{report_id}/rescrape-single` | `rescrape_reported_chapter` | fn `scraper`, perm `rescrape_chapter`, login | UI |
| GET | `/ads/global-networks` | `list_ad_networks` | staff, power `manage_ads` | UI |
| POST | `/ads/global-networks` | `create_ad_network` | staff, power `manage_ads` | UI |
| PATCH | `/ads/global-networks/{network_id}` | `update_ad_network` | staff, power `manage_ads` | UI |
| DELETE | `/ads/global-networks/{network_id}` | `delete_ad_network` | staff, power `manage_ads` | UI |
| POST | `/admin/settings` | `update_site_settings` | staff, power `manage_admin_settings` | UI |
| POST | `/admin/settings/clear-cache` | `clear_site_cache` | staff, power `manage_cache` | UI |
| POST | `/admin/maintenance/delete-all-manga` | `delete_all_manga` | staff, power `purge_site_data` | UI |
| POST | `/admin/maintenance/purge-all-images` | `purge_all_images` | staff, power `purge_site_data` | UI |
| GET | `/admin/api-registry` | `get_api_registry` | staff, power `view_providers` | UI |
| POST | `/admin/api-registry/provider` | `save_api_provider` | staff, power `manage_providers` | UI |
| DELETE | `/admin/api-registry/provider/{category}/{provider_id}` | `delete_api_provider` | staff, power `manage_providers` | UI |
| POST | `/admin/api-registry/test-connection` | `test_api_provider` | staff, power `manage_providers` | UI |
| GET | `/admin/audit-report` | `audit_report` | staff, power `view_system_health` | UI |
| POST | `/health/diagnostics` | `run_diagnostics` | staff, power `view_system_health` | UI |
| POST | `/admin/series/{manga_id}/schedule` | `update_series_schedule` | perm `edit_series`, login | UI |
| POST | `/admin/series/batch-schedule` | `batch_series_schedule` | perm `edit_series`, login | — nothing |
| DELETE | `/admin/chapters/{chapter_id}/pages/{page_index}` | `delete_chapter_page` | perm `edit_series`, login | UI |
| POST | `/admin/series/{series_id}/layout` | `update_series_layout` | perm `edit_series`, login | UI |
| POST | `/admin/series/{series_id}/mirror-images` | `mirror_series_images` | perm `edit_series`, login | UI |
| GET | `/admin/sources/health` | `source_health` | perm `edit_series`, login | — nothing |
| GET | `/admin/storage` | `storage_usage` | perm `edit_series`, login | — nothing |
| POST | `/admin/maintenance/mirror-all-images` | `mirror_all_images` | staff, power `manage_admin_settings` | — nothing |

**`scraper_admin`** (4)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| POST | `/admin/scraper/preview` | `start_preview` | fn `scraper`, perm `submit_manga_url`, login | UI |
| POST | `/admin/scraper/parsers/generate` | `start_parser_generation` | staff, fn `scraper`, power `trigger_scraper_ai` | UI |
| GET | `/admin/scraper/tasks/{task_id}` | `get_task` | fn `scraper`, login | UI |
| GET | `/admin/scraper/parsers` | `list_parsers` | fn `scraper`, perm `view_websites`, login | UI |

**`secret_vault`** (8)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/vault` | `list_vault` | owner+vault, staff, power `manage_secret_vault` | UI |
| POST | `/admin/vault/unlock` | `unlock_vault` | owner+vault, staff, power `manage_secret_vault` | UI |
| POST | `/admin/vault/lock` | `lock_vault` | owner+vault, staff, power `manage_secret_vault` | UI |
| PUT | `/admin/vault/{key}` | `set_vault_value` | owner+vault, staff, power `manage_secret_vault`, vault unlocked | UI |
| DELETE | `/admin/vault/{key}` | `remove_vault_value` | owner+vault, staff, power `manage_secret_vault`, vault unlocked | UI |
| POST | `/admin/vault/{key}/reveal` | `reveal_vault_value` | owner+vault, staff, power `manage_secret_vault`, vault unlocked | UI |
| GET | `/admin/vault/domain` | `get_domain` | owner+vault, staff, power `manage_secret_vault` | UI |
| POST | `/admin/vault/domain/check` | `check_domain` | owner+vault, staff, power `manage_secret_vault` | UI |

**`backups_admin`** (15)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/backups` | `get_backups` | staff, power `manage_backups` | UI |
| GET | `/admin/backups/status` | `get_status` | staff, power `manage_backups` | UI |
| PUT | `/admin/backups/settings` | `save_settings` | staff, power `manage_backups` | UI |
| PUT | `/admin/backups/password` | `set_password` | staff, power `manage_backups` | UI |
| DELETE | `/admin/backups/password` | `remove_password` | staff, power `manage_backups` | UI |
| POST | `/admin/backups/storage/test` | `test_storage` | staff, power `manage_backups` | UI |
| PUT | `/admin/backups/storage` | `connect_storage` | staff, power `manage_backups` | UI |
| DELETE | `/admin/backups/storage` | `disconnect_storage` | staff, power `manage_backups` | UI |
| GET | `/admin/backups/remote` | `list_remote` | staff, power `manage_backups` | UI |
| POST | `/admin/backups/remote/fetch` | `fetch_remote` | staff, power `manage_backups` | UI |
| POST | `/admin/backups/run` | `run_backup` | staff, power `manage_backups` | UI |
| GET | `/admin/backups/files/{name}` | `download_backup` | staff, power `manage_backups` | browser (redirect / image / download) |
| DELETE | `/admin/backups/files/{name}` | `delete_backup` | staff, power `manage_backups` | UI |
| POST | `/admin/backups/upload` | `upload_backup` | staff, power `manage_backups` | UI |
| POST | `/admin/backups/files/{name}/restore` | `restore_backup` | staff, power `manage_backups` | UI |

**`geolock_admin`** (5)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/geolock` | `get_geolock` | staff, power `manage_geolock` | UI |
| PUT | `/admin/geolock` | `save_geolock` | staff, power `manage_geolock` | UI |
| POST | `/admin/geolock/database/update` | `update_database` | staff, power `manage_geolock` | UI |
| POST | `/admin/geolock/database/upload` | `upload_database` | staff, power `manage_geolock` | UI |
| GET | `/geo/status` | `geo_status` | public | UI |

**`roles_succession`** (2)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/roles/succession` | `get_succession` | **owner** | UI |
| PUT | `/admin/roles/succession` | `save_succession` | **owner** | UI |

**`roles_admins`** (8)

| Method | Path (under `/api/v1`) | Handler | Who can call it | Called by |
| --- | --- | --- | --- | --- |
| GET | `/admin/roles/admins` | `list_admins` | staff, power `manage_roles` | UI |
| POST | `/admin/roles/admins` | `make_admin` | **owner** | UI |
| POST | `/admin/roles/admins/{user_id}/demote` | `remove_admin` | **owner** | UI |
| PUT | `/admin/roles/admins/{user_id}/quota` | `set_quota` | **owner** | UI |
| PUT | `/admin/roles/admins/{user_id}/successors` | `set_successors` | staff, power `manage_roles` | UI |
| POST | `/admin/roles/admins/{user_id}/hand-over` | `hand_over_seat` | **owner** | UI |
| GET | `/admin/roles/sub-admin-limits` | `get_limits` | **owner** | UI |
| PUT | `/admin/roles/sub-admin-limits` | `save_limits` | **owner** | UI |

## Appendix B — foreign keys and what a delete does (PostgreSQL, after `alembic upgrade head`)

58 foreign keys: 34 `CASCADE`, 15 `SET NULL`, **9 `NO ACTION`** (after migration `20261018_cascade_series_children`; before it 28 / 13 / 17). `NO ACTION` means deleting the parent row fails while a child row exists. The ones that block deleting a series or its chapters are marked ⚠.

| Child table.column | Parent | On parent delete | |
| --- | --- | --- | --- |
| `ad_clicks.slot_id` | `ad_slots` | CASCADE |  |
| `ad_slots.provider_id` | `global_ad_providers` | NO ACTION |  |
| `admin_activity_days.user_id` | `users` | CASCADE |  |
| `admin_audit_logs.user_id` | `users` | SET NULL |  |
| `admin_bootstrap_state.initialized_by_user_id` | `users` | SET NULL |  |
| `admin_promotion_tokens.issued_by_user_id` | `users` | SET NULL |  |
| `admin_promotion_tokens.issued_to_user_id` | `users` | SET NULL |  |
| `admin_promotion_tokens.redeemed_by_user_id` | `users` | SET NULL |  |
| `admin_successors.admin_id` | `users` | CASCADE |  |
| `admin_successors.successor_id` | `users` | CASCADE |  |
| `admin_task_results.requested_by` | `users` | SET NULL |  |
| `announcements.created_by` | `users` | SET NULL |  |
| `bookmarks.chapter_id` | `chapters` | CASCADE | (was NO ACTION; P0-3, migration `20261018`) |
| `bookmarks.manga_id` | `manga` | CASCADE | (was NO ACTION; P0-3, migration `20261018`) |
| `bookmarks.user_id` | `users` | NO ACTION |  |
| `chapter_likes.chapter_id` | `chapters` | CASCADE |  |
| `chapter_likes.user_id` | `users` | CASCADE |  |
| `chapter_reports.chapter_id` | `chapters` | CASCADE |  |
| `chapter_reports.manga_id` | `manga` | CASCADE |  |
| `chapter_reports.resolved_by` | `users` | SET NULL |  |
| `chapter_reports.user_id` | `users` | SET NULL |  |
| `chapters.manga_id` | `manga` | NO ACTION | (chapters are deleted first by the code) |
| `comment_reactions.comment_id` | `comments` | CASCADE |  |
| `comment_reactions.user_id` | `users` | CASCADE |  |
| `comment_translations.comment_id` | `comments` | CASCADE |  |
| `comment_votes.comment_id` | `comments` | CASCADE |  |
| `comment_votes.user_id` | `users` | CASCADE |  |
| `comments.parent_id` | `comments` | SET NULL |  |
| `comments.user_id` | `users` | CASCADE |  |
| `complaints.user_id` | `users` | NO ACTION |  |
| `content_reports.reporter_id` | `users` | CASCADE |  |
| `content_reports.resolved_by_id` | `users` | NO ACTION |  |
| `custom_emojis.created_by_id` | `users` | NO ACTION |  |
| `login_tokens.user_id` | `users` | CASCADE |  |
| `manga_daily_views.manga_id` | `manga` | CASCADE |  |
| `manga_ratings.manga_id` | `manga` | CASCADE |  |
| `manga_ratings.user_id` | `users` | CASCADE |  |
| `meme_uploads.uploader_id` | `users` | CASCADE |  |
| `notification_preferences.user_id` | `users` | NO ACTION |  |
| `ocr_cache.chapter_id` | `chapters` | CASCADE | (was NO ACTION; P0-3, migration `20261018`) |
| `permission_overrides.user_id` | `users` | CASCADE |  |
| `pills.chapter_id` | `chapters` | CASCADE |  |
| `pills.user_id` | `users` | CASCADE |  |
| `read_history.chapter_id` | `chapters` | CASCADE | (was NO ACTION; P0-3, migration `20261018`) |
| `read_history.manga_id` | `manga` | CASCADE | (was NO ACTION; P0-3, migration `20261018`) |
| `read_history.user_id` | `users` | NO ACTION |  |
| `reputation_events.user_id` | `users` | CASCADE |  |
| `revoked_tokens.user_id` | `users` | CASCADE |  |
| `scraping_jobs.manga_id` | `manga` | SET NULL | (was NO ACTION; P0-3, migration `20261018`) |
| `scraping_jobs.source_id` | `sources` | NO ACTION |  |
| `series_glossary_terms.manga_id` | `manga` | CASCADE |  |
| `system_provider_instances.created_by_user_id` | `users` | SET NULL |  |
| `translation_cache.chapter_id` | `chapters` | CASCADE | (was NO ACTION; P0-3, migration `20261018`) |
| `translation_cache.ocr_cache_id` | `ocr_cache` | SET NULL | (was NO ACTION; P0-3, migration `20261018`) |
| `user_api_keys.user_id` | `users` | CASCADE |  |
| `user_processing_settings.user_id` | `users` | CASCADE |  |
| `users.appointed_by` | `users` | SET NULL |  |
| `vault_secrets.updated_by_id` | `users` | SET NULL |  |

## Appendix C — Celery tasks (44)

| Task | Queue | Beat schedule | Purpose |
| --- | --- | --- | --- |
| `audit_tasks.flush_audit` | maintenance | audit-flush-every-5m — every 5 min | Placeholder task for periodic audit maintenance. |
| `audit_tasks.log_admin_audit` | maintenance |  | Persist an admin audit entry. |
| `audit_tasks.purge_expired_revoked_tokens` | maintenance | revoked-tokens-purge-daily — every 1 d | Drop revocation rows for tokens that have since expired on their own. |
| `backup_tasks.fetch_remote` | maintenance |  |  |
| `backup_tasks.restore_backup` | maintenance |  |  |
| `backup_tasks.run_backup` | maintenance |  |  |
| `backup_tasks.weekly_check` | maintenance | backups-weekly-check — every 1 h | Runs hourly from beat; makes the weekly backup at the chosen day and hour. |
| `community_tasks.prune_resolved_reports` | maintenance | content-reports-prune-daily — every 1 d | F-28: resolved content reports never expired -- delete ones past |
| `echo.echo` | default |  | Echo the provided message with a timestamp. |
| `echo.ping` | default |  |  |
| `email_tasks.send_magic_link` | email |  | Send a magic-link email via the email service. |
| `email_tasks.send_notification_email` | email |  | Send a bell-notification email via the email service (SRS 1I.5.1). |
| `manga_tasks.refresh_manga_chapters_cache` | default |  |  |
| `manga_tasks.refresh_manga_detail_cache` | default |  |  |
| `manga_tasks.refresh_manga_list_cache` | default |  |  |
| `notification_tasks.create_notification` | notifications |  |  |
| `notification_tasks.fan_out_announcement` | notifications |  | Put an admin broadcast/popup into every active account's bell. |
| `ocr_tasks.translate_overlay_job` | ocr |  |  |
| `pdf_tasks.daily_integrity_scan` | maintenance | pdf-integrity — every 1 d | Run the PDF integrity checker. |
| `roles_tasks.succession_check` | maintenance | roles-succession-daily — every 1 d |  |
| `scraper_tasks.bulk_delete_series_task` | scrape |  |  |
| `scraper_tasks.check_source_health` | scrape | source-health-daily — every 1 d | Daily: run each source site's parser against a sample series, alert on |
| `scraper_tasks.check_storage_usage` | scrape | storage-usage-daily — every 1 d | Daily: alert the admins when the pictures volume passes its threshold. |
| `scraper_tasks.cleanup_stuck_jobs` | scrape | scraper-cleanup-stuck-jobs — every 15 min | Reset jobs that have been stuck in 'in_progress' state for too long. |
| `scraper_tasks.delete_chapter_pages_only` | scrape |  |  |
| `scraper_tasks.generate_parser_task` | scrape |  | Invoke the scraper-creation AI for a website (SRS 1G.6.0A / 1G.8.4). |
| `scraper_tasks.mirror_chapter_pages` | compress |  | Download a chapter's pictures, compress them to WebP and self-host them. |
| `scraper_tasks.mirror_series_pages` | scrape |  | Queue page mirroring for every chapter of a series that still points at |
| `scraper_tasks.process_chapter_scrape` | scrape |  | Async task to scrape chapter pages and handle image processing. |
| `scraper_tasks.process_manga_scrape` | scrape |  | Async task to perform heavy manga scraping. |
| `scraper_tasks.report_manga_count_metric` | scrape | nightly-manga-count-metric — every 1 d |  |
| `scraper_tasks.rescrape_chapter` | scrape |  |  |
| `scraper_tasks.rescrape_series` | scrape |  |  |
| `scraper_tasks.run_fast_scrape` | scrape |  |  |
| `scraper_tasks.run_scheduled_chapter_checks` | scrape | scheduled-chapter-checks — every 30 min | Celery beat entry point for 1G.12A: check due series for new chapters. |
| `scraper_tasks.run_scheduled_scrape` | scrape | scheduled-scrape — every 15 min |  |
| `scraper_tasks.run_source_task` | scrape |  | Run an admin preview / custom-parser request off the API process. The |
| `scraper_tasks.scrape_chapter_by_url` | scrape |  |  |
| `scraper_tasks.scrape_series_by_url` | scrape |  |  |
| `scraper_tasks.staged_series_rescrape` | scrape |  | Full-series rescrape with staged validation (SRS 1G.12.3 / 1G.12.4). |
| `scraper_tasks.sync` | scrape |  |  |
| `suggestion_tasks.generate_user_suggestions` | maintenance |  | Generate user-specific manga suggestions. |
| `suggestion_tasks.scan` | maintenance | suggestion-scan-hourly — every 1 h | Placeholder hourly scan for suggestion housekeeping. |
| `translation_tasks.translate_text_job` | translation |  |  |

## Appendix D — one line per backend module (from each file's own docstring)

`-` = the file has no docstring.

### `app/api/routers/`

| File | What it does |
| --- | --- |
| `account.py` | Reader account endpoints: Microsoft sign-in, username availability and the one-time profile completion step. There are no passwords: readers sign in with a magic link, Go |
| `ad_slots.py` | Routes for managing advertisement slots. |
| `admin.py` | Administrative routes for managing manga content, users, and tasks. |
| `admin_2fa.py` | Admin second factor endpoints (roadmap item 15). |
| `ads.py` | Public advertisement endpoints for slot listings and click tracking. |
| `auth.py` | Authentication routes implemented purely in FastAPI. |
| `backup.py` | Administrative database backup and restore endpoints. |
| `backups_admin.py` | Admin -> Storage & Backups (main admin only). |
| `bookmarks.py` | Authenticated bookmark management routes. |
| `branding.py` | Branding and footer configuration endpoints. |
| `cache_admin.py` | Cache administration endpoints (SRS 2C.4.3). |
| `comments.py` | Native comment system endpoints (SRS Part 3 / 3A). |
| `community.py` | Community endpoints (SRS Part 3): emojis, reputation, cultivation rank, Pills, GIFs/memes, and user-level community moderation (block/timeout). |
| `config.py` | Configuration discovery endpoints. |
| `geolock_admin.py` | Geolock: the public status check and Admin -> Geolock (main admin only). |
| `glossary.py` | Per-series character-name glossary endpoints (SRS 2C.1). |
| `health.py` | System health probes for parity with the legacy backend. |
| `history.py` | A signed-in reader's read chapters (so they follow the reader to a new device). |
| `integrations.py` | Routes for managing third-party integration API keys. |
| `management.py` | Lightweight management endpoints (version info, etc.). |
| `manga.py` | Public manga and chapter routes. |
| `notifications.py` | The bell: notification list/read/delete + per-account preferences (1I.6). |
| `ocr.py` | OCR API endpoints backed by the shared OCR and translation services. |
| `processing.py` | Chapter/page processing endpoint (SRS 2F.1): the reader-facing path tying together cache short-circuiting, provider priority (2A), the normalized OCR shape (2B), whole-ch |
| `provider_management.py` | Admin provider management: multi-provider priority/fallback (SRS 2D). |
| `reader.py` | Reader engagement endpoints: ratings, chapter likes, broken-chapter reports, site announcements, bookmark import and the signed image proxy. |
| `roles_admins.py` | Admins, their seats and succession lines, and the sub-admin ceiling. |
| `roles_succession.py` | Automatic succession settings (the owner only -- never delegable). |
| `roles_tabs.py` | Role Management -> Tab access: which admin tabs each person sees. |
| `scraper_admin.py` | Series-management scraper tools: previews and custom parser generation. |
| `secret_vault.py` | Secret vault endpoints: the main admin's GUI for integration settings. |
| `seo.py` | Search-engine feeds served at the site root: sitemap.xml and rss.xml. |
| `site_admin.py` | Admin console endpoints for the v1.01 panel: social links, announcements, chapter-report triage, auto-ad networks, site settings + maintenance, API provider registry, aud |
| `site_functions.py` | Admin -> Site Functions: the owner's on/off switches for the website. |
| `support.py` | Donation / support links: public list, main-admin-only editing. |
| `system_state.py` | Public system-state routes (no personal data). |
| `system_stats.py` | Expose lightweight per-process resource stats without external deps. |
| `tasks.py` | Endpoints for interacting with Celery tasks. |
| `translation.py` | Translation endpoints backed by the FastAPI services. |
| `user_settings.py` | User settings endpoints for profile data and integration API keys. |

### `app/services/`

| File | What it does |
| --- | --- |
| `ad_placements.py` | Canonical catalogue of ad slot placements. |
| `admin_roles.py` | Admin seats, the sub-admin pool and succession lines (owner's rules, 2026-10-02). |
| `admin_second_factor.py` | Second factor for administrators (roadmap item 15). |
| `admin_service.py` | Business logic and utility functions for administrative tasks. |
| `admin_succession.py` | Admins' activity and automatic succession (owner's rules, 2026-10-02). |
| `ads_config_service.py` | Advertisement configuration helpers for the FastAPI backend. |
| `ai_assist.py` | AI/OCR conflict handling (SRS 2A.3). |
| `ai_vision_assist.py` | AI-assisted OCR correction (SRS 2A.3): re-read flagged regions of the page image via a vision-capable AI provider when OCR failed or fell below the confidence threshold t |
| `animeplanet_service.py` | Series metadata from Anime-Planet's manga section. |
| `audit_service.py` | Admin audit logging helpers. |
| `auth_service.py` | - |
| `backup_crypto.py` | Password encryption for backup archives, streamed so size doesn't matter. |
| `backup_service.py` | Storage & Backups: whole-site archives made, kept, shipped and restored. |
| `bubble_shape.py` | Find the speech bubble around a text box, so the reader can draw the translation inside the bubble's own shape instead of a plain rectangle. |
| `cache_admin_service.py` | Cache administration (SRS 2C.4): Mechanism A (platform default caching) and the admin actions that manage the shared cache's contents. |
| `catalogue_service.py` | Reader-facing catalogue payloads (list, detail, chapter list). |
| `chapter_grouping.py` | How a source lays its content out, and how we turn it into vertical chapters. |
| `chapter_processing_service.py` | Chapter/page processing orchestration (SRS 2F.1). |
| `chapter_title_service.py` | Readable chapter titles. |
| `chapter_translation_service.py` | Whole-chapter translation context (SRS 2C.1), in two stages. |
| `comment_service.py` | Native comment system core (SRS 3A): threading, editing, moderation, voting, reactions, reporting, sorting, and pagination. |
| `comment_translation_service.py` | Automatic comment translation (SRS 3A.5). |
| `config_manager.py` | Lightweight JSON configuration management for the FastAPI backend. |
| `content_rights.py` | Content-rights resolution and gates (SRS Part 1J). |
| `cover_service.py` | Series cover images: download once, verify, re-encode to WebP, self-host. |
| `disposable_email.py` | Disposable / temporary email detection (SRS 1D.2). |
| `donation_service.py` | Donation / support links (Ko-fi, Buy Me a Coffee, PayPal, crypto ...). |
| `email_service.py` | Email sending utilities adapted for the FastAPI backend. |
| `emoji_catalogue.py` | Base Unicode emoji catalogue (SRS 3A.4.1/3A.4.2). |
| `geolock.py` | Geolock: refuse the site to visitors from chosen countries. |
| `gif_service.py` | GIF Tier 1 (SRS 3B.2): search an external catalogue, store URL/metadata only. |
| `glossary_service.py` | CRUD for the per-series character-name glossary (SRS 2C.1). |
| `history_service.py` | A signed-in reader's read chapters, kept on their account. |
| `image_proxy.py` | Signed image proxy for source CDNs that refuse hotlinked images. |
| `integration_key_vault.py` | Utilities for encrypting and decrypting user supplied integration secrets. |
| `maintenance.py` | Maintenance mode: while enabled, API calls from anyone below Secondary Administrator get a 503, except the endpoints needed to sign in and to render the site chrome. |
| `manga_service.py` | - |
| `mangaupdates_service.py` | Series metadata from MangaUpdates (title, description, genres, authors, cover, type, status). |
| `meme_service.py` | User-uploaded memes -- Tier 2 (SRS 3B.2). |
| `metadata_sources.py` | Series metadata links: MangaUpdates or Anime-Planet. |
| `microsoft_oauth.py` | Sign in with Microsoft (personal, work and school accounts) via OpenID Connect authorization-code flow with PKCE. |
| `moderation_service.py` | Moderator actions against a user's community participation (SRS 1F.4.1). |
| `notification_service.py` | Notification creation, delivery, and reader APIs (SRS 1I). |
| `oauth_service.py` | OAuth and SSO integration services. |
| `ocr_normalize.py` | Normalized OCR output (SRS 2B.6). |
| `ocr_service.py` | OCR service implementation decoupled from Flask. |
| `ocr_workflow.py` | OCR helper routines reused across routers and services. |
| `overlay_fonts.py` | Curated overlay font set (SRS 2F.2A). |
| `page_image_service.py` | Chapter page images: download once, compress, store in ONE lightweight format. |
| `page_mirror_service.py` | Database side of page mirroring: compress a chapter's pictures and swap the stored page list over to our own WebP copies. |
| `parser_generation_service.py` | AI-assisted parser generation and repair (SRS 1G.8.2 / 1G.8.4 / 1G.9). |
| `parser_versions_service.py` | Parser versioning and approval lifecycle (SRS 1G.8.3, 1G.8.4, 1G.8.5). |
| `pdf_service.py` | PDF inspection helpers used by periodic tasks. |
| `permissions_service.py` | Effective-permission resolution and override management (SRS 1F.6–1F.10). |
| `pill_service.py` | Pills -- the cache-sharing reward (SRS 3C.3). |
| `pinned_fetch.py` | Fetch remote URLs over a connection pinned to a pre-validated IP address. |
| `platform_ceiling_service.py` | Global platform-default usage ceiling (SRS 2E.3). |
| `processing_plan.py` | Processing methods and provider priority (SRS 2A). |
| `processing_settings_service.py` | CRUD for per-user processing preferences (Part 2: 2A.3, 2C.4.4, 2E.1, 2F.2). |
| `provider_config.py` | Provider configuration helpers without Flask dependencies. |
| `provider_management_service.py` | Multi-provider admin management (SRS 2D). |
| `provider_registry.py` | Runtime registry for OCR/translation/AI provider configuration. |
| `provider_resolver.py` | Helpers for resolving provider configurations and runtime services. |
| `ranking_service.py` | Cultivation ranking system (SRS 3D). |
| `reading_order.py` | Script-dependent reading order (SRS 2B.4). |
| `region_classifier.py` | Heuristic text-region classification (SRS 2B.3). |
| `reputation_service.py` | Reputation system (SRS 3C): earn, revoke, anti-abuse. |
| `rescrape_service.py` | Rescrape flows: the chapter Fix button and staged full-series rescrape (SRS 1G.12). |
| `s3_storage.py` | Minimal S3-compatible storage client for backups (AWS Signature V4). |
| `scheduled_checks_service.py` | Scheduled new-chapter detection (SRS 1G.12A). |
| `scraper_ai_service.py` | The scraper-creation AI (SRS 1G.8.7 / 1G.8.8). |
| `scraper_health_service.py` | Per-website scraper health + structure-change detection (SRS 1G.7.5/1G.7.8). |
| `scraper_service.py` | Simplified scraping service used by FastAPI admin routes. |
| `scraper_workflow_service.py` | - |
| `script_registry.py` | Script support model (SRS 2B.1) and script/language detection. |
| `secret_vault.py` | Secret vault: main-admin-managed overrides for allow-listed env variables. |
| `series_alerts.py` | New-chapter alerts for readers who bookmarked a series. |
| `series_import.py` | Queueing a series import from the admin "Import & Scrape" form. |
| `site_content_service.py` | Admin-editable site content: footer text, social links and site-wide settings (maintenance mode, registration, reader defaults). |
| `site_functions.py` | Reading and changing the owner's website-function switches. |
| `source_health_service.py` | Daily health check per source website (roadmap item 11). |
| `spam_filter.py` | Automated spam/abuse pre-filter for comments (SRS 3A.3). |
| `storage_report_service.py` | Storage usage report and alert threshold (roadmap item 12). |
| `submission_quality_gate.py` | Content-based write authority for the shared OCR/translation cache. |
| `suggestion_service.py` | Generate simple manga suggestions based on bookmarks and history. |
| `system_settings_service.py` | Shared accessor for the singleton system_settings row (id=1). |
| `system_state.py` | System state helpers for the FastAPI backend. |
| `token_revocation.py` | Server-side revocation for the stateless JWTs (Tier 2.9). |
| `translation_cache_service.py` | Policy layer for the shared OCR/translation cache (SRS 1H.14). |
| `translation_service.py` | Translation service abstraction for FastAPI. |
| `universal_scraper.py` | Compatibility wrappers for scraping helpers used by admin tooling. |
| `url_guard.py` | Network safety helpers ported from the legacy Flask backend. |
| `usage_limit_service.py` | Server-side page/word usage-limit enforcement (SRS 2E). |

### `app/models/`

| File | What it does |
| --- | --- |
| `base.py` | - |
| `community.py` | Native community system: reactions, moderation, reputation, cultivation ranking (SRS Part 3). ``Comment`` and ``User`` themselves stay in ``models/user.py``; this module  |
| `engagement.py` | Reader engagement: ratings, chapter likes, broken-chapter reports, site announcements and per-day view counters. |
| `glossary.py` | Per-series character-name glossary (SRS 2C.1: "maintain consistent character-name handling across chapters of one series"). |
| `manga.py` | - |
| `notifications.py` | Bell notifications (SRS 1I). |
| `processing_settings.py` | Per-user processing preferences (SRS Part 2: 2A.3, 2C.4.4, 2E.1, 2F.2). |
| `provider_management.py` | Multi-provider admin management (SRS Part 2: 2D). |
| `scraping.py` | - |
| `settings.py` | - |
| `translation_cache.py` | Shared OCR/translation cache (SRS 1H.14). |
| `user.py` | - |

### `app/core/`

| File | What it does |
| --- | --- |
| `admin_identity.py` | The site owner's identity: one e-mail hash in ``.env``, claimed by Google. |
| `admin_tabs.py` | The admin-panel tabs, and which permissions belong to which tab. |
| `api_errors.py` | Standard API error registry and response envelope (SRS 1B.4). |
| `celery_app.py` | - |
| `database.py` | Expose the SQLAlchemy base classes and session helpers for Alembic. |
| `db.py` | Database configuration for the FastAPI service. |
| `pagination.py` | Standard pagination contract (SRS 1B.4.5). |
| `permissions.py` | Permission catalogue, role defaults, and never-grantable set (SRS 1F.6–1F.8). |
| `scaling.py` | Scaling metadata: high-volume table registry (SRS 1C.3.5 / 1C.3.6). |
| `security.py` | Authentication helpers for JWT handling. |
| `settings.py` | Application settings loaded from environment variables. |
| `site_functions.py` | The website's main functions the owner can switch on and off. |
| `test_mode.py` | Central guard for test-only conveniences. |
| `workload_priority.py` | Workload priority policy (SRS 1C.5.3). |

### `app/dependencies/`

| File | What it does |
| --- | --- |
| `auth.py` | Authentication dependencies for FastAPI routes. |
| `powers.py` | ``require_power(key)``: a route the owner can delegate. |
| `site_access.py` | Members-only switch (Admin -> Site Functions -> "Sign-in required"). |
| `site_functions.py` | ``require_function(key)``: a route that only answers while the owner has the function switched on (Admin -> Site Functions). Off answers ``FUNCTION_DISABLED``. |

### `app/bootstrap/`

| File | What it does |
| --- | --- |
| `backpressure.py` | - |
| `exception_handlers.py` | Global exception handlers rendering the standard error envelope (SRS 1B.4). |
| `geolock_middleware.py` | Geolock: answer 451 to visitors from countries the main admin blocked. |
| `lifecycle.py` | Startup and shutdown helpers for infrastructure components. |
| `metrics.py` | Prometheus metrics (item 42). |
| `middleware.py` | HTTP middleware classes and registration helpers. |
| `observability.py` | Observability initialization helpers. |
| `providers.py` | Provider and integration bootstrap helpers. |
| `routers.py` | Router composition for the FastAPI application. |
| `timeout.py` | Per-request timeout middleware with exemptions for long-running routes (C3). |

### `app/utils/`

| File | What it does |
| --- | --- |
| `alembic_check.py` | Utilities for inspecting Alembic migration state without applying migrations. |
| `audit_logger.py` | - |
| `bounded_threadpool.py` | - |
| `cache_invalidation.py` | Explicit cache invalidation helpers (item 34). |
| `cdn.py` | CDN URL helpers for media assets. |
| `circuit_breaker.py` | - |
| `client_ip.py` | Single source of truth for resolving a request's real client IP. |
| `crypto_utils.py` | Utilities for decrypting environment configuration secrets. |
| `csrf_middleware.py` | Double-submit-cookie CSRF protection (C6). |
| `daily_limiter.py` | - |
| `email_crypto.py` | Helpers for encrypting and decrypting email addresses at rest. |
| `endpoint_limiter.py` | - |
| `file_validation.py` | - |
| `image_safety.py` | Shared image-decode safety helper (SRS 4G.3.1 -- decompression bomb protection). |
| `job_store.py` | Lightweight async-job store for OCR/translation (item 39). |
| `malware_scanner.py` | Malware scanning for user-uploaded files (H5). |
| `python_multipart.py` | Compatibility layer exposing the upstream ``python_multipart`` package. |
| `rate_limiter.py` | Lightweight request rate limiting middleware with Redis fallback. |
| `sanitizer.py` | - |
| `structured_logging.py` | Shared structured logging configuration and context helpers. |
| `swr_cache.py` | - |

### `app/repositories/`

| File | What it does |
| --- | --- |
| `chapter_repository.py` | - |
| `manga_repository.py` | - |
| `scraping_job_repository.py` | - |

### `app/schemas/`

| File | What it does |
| --- | --- |
| `ad_slots.py` | Pydantic schemas for the advertisement slot admin endpoints. |
| `admin.py` | - |
| `auth.py` | Pydantic schemas for authentication endpoints. |
| `bookmarks.py` | - |
| `branding.py` | Pydantic schemas for the branding and footer configuration endpoints. |
| `comments.py` | - |
| `community.py` | - |
| `history.py` | Request and response shapes for a signed-in reader's read-chapter list. |
| `integrations.py` | Pydantic schemas for the integration API-key endpoints. |
| `manga.py` | - |
| `ocr.py` | - |
| `processing_settings.py` | - |
| `translation.py` | - |
| `user.py` | Pydantic schemas for user data transfer. |
| `user_settings.py` | - |

### `app/scrapers/`

| File | What it does |
| --- | --- |
| `ai_fallback.py` | Selector extraction via the PA-configured scraper-creation AI (SRS 1G.8.7). |
| `ai_playbook.py` | The Scraper AI's instruction book, and the page analysis it is given. |
| `autodetect.py` | Work out extraction rules from a page's structure alone (no AI, no per-site knowledge). |
| `base_scraper.py` | Synchronous HTML scraper. |
| `concurrency.py` | - |
| `config.py` | - |
| `definition_guard.py` | Guardrails for parser definitions written by the Scraper AI. |
| `errors.py` | Typed scraper errors (SRS 1G.5.4 / 1G.7.4). |
| `http_client.py` | - |
| `metrics.py` | - |
| `packed_scripts.py` | Decoders for chapter pages that hide their image list inside a script. |
| `parsing.py` | Extraction helpers shared by the scraper, parser tests and presets. |
| `presets.py` | Built-in parsers. |
| `schemas.py` | - |
| `script_images.py` | Page images that a reader page keeps inside a ``<script>`` instead of ``<img>`` tags. |
| `source_pipeline.py` | Find (or create) a parser that can read a website. |

### `app/tasks/`

| File | What it does |
| --- | --- |
| `audit_tasks.py` | Audit logging Celery tasks. |
| `backup_tasks.py` | Storage & Backups background jobs (maintenance queue). |
| `community_tasks.py` | Community moderation maintenance Celery tasks (SRS Part 3 / 1F.4.1). |
| `echo.py` | Simple echo task for diagnostics. |
| `email_tasks.py` | Email related Celery tasks. |
| `manga_tasks.py` | - |
| `notification_tasks.py` | Notification creation Celery task (SRS 1I.5.1: never inline in a request). |
| `ocr_tasks.py` | Async OCR-overlay translation Celery tasks (item 39). |
| `pdf_tasks.py` | PDF maintenance Celery tasks. |
| `roles_tasks.py` | Daily automatic succession check (runs only when the owner switched it on). |
| `scraper_tasks.py` | Scraper related Celery tasks. |
| `suggestion_tasks.py` | Suggestion generation Celery tasks. |
| `translation_tasks.py` | Async translation Celery tasks (item 39). |

### `backend_fastapi/scripts/`

| File | What it does |
| --- | --- |
| `backfill_email_lookup_hash.py` | Backfill ``users.email_lookup_hash`` for pre-existing rows (C2 / item 11). |
| `backfill_oauth_token_encryption.py` | Encrypt any pre-existing plaintext OAuth tokens at rest (Blind Spot #16). |
| `celery_healthcheck.py` | Container healthcheck for the Celery worker and beat services. |
| `cli_bootstrap.py` | Server-side admin commands. |
| `encrypt_env.py` | Utility for encrypting .env files using Fernet symmetric encryption. |
| `make_admin_hash.py` | Make (or check) the .env line that says who the site owner is. |
| `make_env.py` | Create a new .env from .env.example with fresh random secrets. |
| `rotate_encryption_key.py` | Re-encrypt stored secrets under the newest encryption keys (roadmap item 16). |
| `seed_bootstrap_state.py` | Create the singleton system_state row after migrations (run by the migrate job). |
| `set_site_domain.py` | Set (or clear) the website domain from the server, without logging in. |
| `verify_alembic_chain.py` | Automatically verify and repair Alembic migration state. |
| `verify_query_plans.py` | Query-plan verification for the manga search fixes (Phase 4 / item 27, extended for Gap A's pg_trgm title index). |
| `wait_for_services.py` | Block until core infrastructure services accept connections. |
