# Audit — manga-website-v1.01 — 2026-10-02

## Summary

Full nine-pass audit of the repository at branch
`claude/great-faraday-nh2dwx` (`ac52a33` = `main` + "Scraper AI is
main-admin only"); new IDs continue from F-85. All passes ran. Security was
checked by starting the app and calling every admin-tier route as a
sub-admin and as a reader, so findings are reproduced, not guessed. Counts:
**1 critical, 2 high, 6 medium, 4 low** (13). F-88 and F-98 were fixed on
this branch at the owner's request (API Management and Admin Settings are
main-admin only); everything else is open. Lint, 1069 backend tests, type
check, 30 frontend tests and the build are green.

## Findings ledger

| ID | Sev | Location | Defect | Pass |
| --- | --- | --- | --- | --- |
| F-89 | CRITICAL | `backend_fastapi/app/services/provider_registry.py:109` (served by `routers/config.py:25`) | Anonymous `GET /api/v1/config/providers` returns every platform provider's custom header **values** (e.g. an `api-key`), its endpoint URL and the last 4 key characters | 3 |
| F-91 | HIGH | `GET /api/v1/admin/audit/logs`, `/admin/audit/logs/search` (`admin.py`) | A sub-admin on defaults (`view_full_audit` = off) reads the main admin's full audit trail, with IPs and metadata | 3 |
| F-93 | HIGH | `backend_fastapi/app/api/routers/processing.py:295` | `async def process_chapter_page` runs the whole OCR + translation pipeline (`cps.process_page`) synchronously on the event loop, freezing that API worker for every other request until it finishes | 6 |
| F-92 | MEDIUM | `backend_fastapi/app/api/routers/manga.py` (`get_manga_batch` → `_enforce_series_hostable`) | Library batch endpoint checks rights one series at a time (own session + thread hop each): 12 queries for 3 series, 66 for 30, up to ~400 for the 200-id cap | 5 |
| F-94 | MEDIUM | 49 `async def` handlers, e.g. `manga.py get_chapter_content`, `get_chapter_list`, `reader.py`, `comments.py`, `auth.py` | Blocking SQLAlchemy calls made directly inside `async` handlers, so each query stalls the worker's event loop | 6 |
| F-88 | MEDIUM | **fixed on this branch** · `GET /api/v1/admin/settings`, `/admin/config/session`, `/admin/validate-ocr-providers`, `/config` (`admin.py`, `management.py`) | Guarded by `require_admin_user`, which admits sub-admins: Admin Settings and provider status are readable by every sub-admin, against the main-admin-only rule | 3 |
| F-95 | MEDIUM | `src/app.js` (12 eager `import`s of `pages/Admin/*`) | The whole admin console ships in the reader bundle: one 680 kB JS file (178 kB gzip) for every visitor; only `AdminLogin` is lazy | 7 |
| F-96 | MEDIUM | `docker-compose.yml:279-345`, `backend_fastapi/deployment/gunicorn.conf.py:27`, `backend_fastapi/app/core/celery_app.py` | Default stack runs ~20 Python processes (~120 MB each measured) and sets no `worker_max_memory_per_child`/`max_tasks_per_child`: ~2.5 GB RAM before Postgres, with no recycling of leaking image/OCR workers | 8 |
| F-97 | MEDIUM | `src/constants/adminFeatures.js` vs `src/app.js:146-230` | Admin hub shows sub-admins the Users, Health, Ads and Chapter-reports tiles (by permission), but those routes are main-admin only in the router, so the tiles bounce them back | 7 |
| F-98 | LOW | **fixed on this branch** · `backend_fastapi/app/core/permissions.py:54-59` | `view_providers`, `configure_ocr`, `configure_translation`, `configure_ai`, `set_provider_priority` are toggles on Role Management (4 on by default for sub-admins) that no route checks; API Management is main-admin only in code, so the toggles promise access that does not exist | 7 |
| F-90 | LOW | `backend_fastapi/app/api/routers/system_stats.py` | `GET /api/v1/system/stats` serves the Prometheus metrics to anyone (nginx proxies all of `/api/`) | 3 |
| F-86 | LOW | `backend_fastapi/app/utils/swr_cache.py:112` | Stale-cache refreshes are started with `asyncio.create_task(...)` and no reference is kept, so the event loop may garbage-collect them before they finish | 1 |
| F-87 | LOW | `backend_fastapi/app/core/settings.py:260` | `ALGORITHM` is taken from the environment with no allowlist; the `ecdsa` CVE waiver in `requirements.txt` assumes HS256 only | 2 |

## Findings

### Pass 1 — static analysis

ruff (project rules) clean; extended families B/ASYNC/S/PERF/PLW run once.
Hits reviewed: `S105/S106` are token-type constants (false positives),
`S324` sha1 is used for cache file names (not security), `S311` random is
used for jitter/sampling (not security), `PLE0605` is a runtime `sorted()`
list (valid). No orphan frontend modules; `vulture --min-confidence 80`
finds one unused parameter (`processing.py:92 primary`, harmless: the primary
translator is passed per call at `processing.py:306`).

#### F-86 — Background refresh tasks can be garbage-collected
**Severity:** LOW · **Pass:** 1 · **Location:** `backend_fastapi/app/utils/swr_cache.py:112`, `:119`

**Evidence**
```python
if await redis_client.set(lock_key, "1", nx=True, ex=30):
    if celery_task_name and celery_task_kwargs is not None:
        asyncio.create_task(
            _dispatch_celery_refresh(
```

**Why it matters**
The event loop keeps only a weak reference to tasks; a task with no other
reference can be collected mid-run (Python docs, `asyncio.create_task`). The
refresh then silently never happens and the stale value is served until the
30 s lock expires and another request retries. Bounded, but under load it
means more stale reads and repeated refresh attempts.

**Confidence:** likely — pattern confirmed in code; collection is
nondeterministic.

### Pass 2 — dependencies and secrets

`pip-audit` on `requirements.lock`: one advisory, `ecdsa 0.19.2`
PYSEC-2026-1325 (no fix released), already documented and waived in
`requirements.txt` because JWTs use HS256. `npm audit --omit=dev`: 0
vulnerabilities. No committed keys/tokens (pattern sweep for AWS, Google,
OpenAI/Anthropic, GitHub, Slack, Groq keys and private keys); only
`.env.example` files are tracked and they hold placeholders. E-mail
addresses in source are documentation examples only.

#### F-87 — JWT algorithm not restricted to HMAC
**Severity:** LOW · **Pass:** 2 · **Location:** `backend_fastapi/app/core/settings.py:260`

**Evidence**
```python
algorithm = (self.algorithm or "").strip() or "HS256"
self.algorithm = algorithm
```

**Why it matters**
The `ecdsa` waiver ("the app only ever signs/verifies JWTs with HS256")
holds only while nobody sets `ALGORITHM` to an EC algorithm; nothing
enforces it. Configuration-only, so LOW.

**Confidence:** confirmed.

### Pass 3 — security and authorization

Method: the app was started as in the test suite and every route was listed
with the dependencies FastAPI actually runs (844 registrations: 279 under
`/api/v1`, the rest the deprecated `/` and `/api` aliases of the same
handlers). Admin-tier GET routes were then called as a default sub-admin and
as a reader. Two source ranges could not be read in this session
(`dependencies/auth.py` ~150-320, `routers/admin.py` ~290-520, permission
check refused); their behaviour was established by these calls instead.

Checked and sound: main-admin-only gates on providers, Secret Vault, branding,
footer, backups, site access and the Scraper AI; meme/profile/logo uploads
(size cap, pixel cap, re-encode, filename allowlist); rate limits on
magic-link, Google and admin sign-in; the reader catalogue sits behind the
site-access switch.

#### F-89 — Provider secrets readable without signing in
**Severity:** CRITICAL · **Pass:** 3 · **Location:** `backend_fastapi/app/services/provider_registry.py:109`, served by `backend_fastapi/app/api/routers/config.py:25`

**Evidence**
```python
def _masked_payload(raw: Dict[str, Any], api_key: Optional[str]) -> Dict[str, Any]:
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else None
    return {
        "provider": raw.get("provider_id") or raw.get("provider") or "custom",
        "apiKey": mask_api_key(api_key),
        "apiUrl": raw.get("api_url"),
        "model": raw.get("model"),
        "headers": headers,
    }
```
```python
@router.get("/providers")
async def list_providers(request: Request) -> Dict[str, Any]:
    state = _provider_state(request)
    payload = state.to_public_payload()
```
Reproduced: the main admin saved a translation provider with header
`api-key: AZURE-SECRET-VALUE-123` through `PUT /api/v1/admin/system-providers`;
an anonymous `GET /api/v1/config/providers` then returned
`"headers":{"api-key":"AZURE-SECRET-VALUE-123"}`, the endpoint URL and
`"apiKey":"********************7890"`.

**Why it matters**
Custom endpoints (Azure OpenAI, self-hosted gateways, most "custom" providers)
authenticate with a header, so the key itself is public. No sign-in, no
site-access gate, and the same payload is on the `/config/providers` and
`/api/config/providers` aliases.

**Confidence:** confirmed (reproduced end to end).

#### F-91 — Sub-admins read the full audit log
**Severity:** HIGH · **Pass:** 3 · **Location:** `GET /api/v1/admin/audit/logs`, `GET /api/v1/admin/audit/logs/search` (`routers/admin.py`)

**Evidence**
Reproduced: a main-admin audit row (`action="VAULT_SET_SECRET_MARKER"`,
`source_ip="203.0.113.9"`) was returned to a default sub-admin by both
endpoints (HTTP 200, row and IP present). The permission catalogue says
otherwise:
```python
"view_scope_audit": (Group.OBSERVABILITY, True, True),
"view_full_audit": (Group.OBSERVABILITY, True, False),
```
(`core/permissions.py:91-92`; sub-admin default for the full log is off.)

**Why it matters**
Sub-admins see every main-admin action, Secret Vault activity, IP addresses
and action metadata.

**Confidence:** confirmed (behaviour); the handler source is in the
unreadable range, so the exact line is not quoted.

#### F-88 — Admin Settings readable by sub-admins
**Severity:** MEDIUM · **Pass:** 3 · **Location:** `GET /api/v1/admin/settings`, `/admin/config/session`, `/admin/validate-ocr-providers` (`routers/admin.py`), `GET /api/v1/config` (`routers/management.py`)

**Evidence**
Route listing: all four depend on `require_admin_user` (not
`require_main_admin_user`). A default sub-admin gets 200 from each;
`/admin/settings` returns `maintenance_mode`, `allow_registration`,
`session_timeout_days`, `ALLOW_USER_OCR_API`, branding; the OCR check returns
provider configuration/reachability. Writes are main-admin only
(`POST /admin/settings`, `PATCH /admin/system-settings` use
`require_main_admin_user`).

**Why it matters**
House rule: Admin Settings and API management are main-admin only. No
secret is in these responses (that would raise it to HIGH).

**Confidence:** confirmed.

#### F-90 — Prometheus metrics public through the API
**Severity:** LOW · **Pass:** 3 · **Location:** `backend_fastapi/app/api/routers/system_stats.py` (`GET /api/v1/system/stats`)

**Evidence**
Anonymous request returned `200` with `# HELP app_uptime_seconds ...`
(Prometheus text). `deployment/nginx/site.conf:190` proxies all of
`location /api/`. Root `/metrics` is not proxied.

**Why it matters**
Request volumes, paths and process data help an attacker profile the server.

**Confidence:** confirmed.

### Pass 4 — API contract

All 199 literal API calls in `src/` (`api.get/post/put/patch/del`,
`apiFetch`) were matched against the live route table: every path exists
with the method used. (One template-string call, `/auth/logout${...}`, is a
parsing artefact; `POST /auth/logout` exists.) Calls whose path is built at
runtime were not checked.

### Pass 5 — data layer

50 tables, 63 foreign-key columns: every one leads an index or a
unique/composite constraint. Alembic chain and drift are covered by
`tests/test_alembic_drift_check.py` (green). Query counts were measured on
the reader list endpoints with 3 and 30 series: `/manga/` and `/manga/browse`
are served from the SWR cache (1 query when warm); `/manga/{id}/chapters`
uses 9.

#### F-92 — N+1 on the library batch endpoint
**Severity:** MEDIUM · **Pass:** 5 · **Location:** `backend_fastapi/app/api/routers/manga.py` (`get_manga_batch`, `_enforce_series_hostable`)

**Evidence**
```python
    visible = []
    for item in items:
        try:
            await _enforce_series_hostable(item["id"], user)
```
```python
    def _check() -> None:
        with SessionLocal() as db_session:
            manga = db_session.get(Manga, manga_id)
            if manga is not None:
                assert_series_hostable(db_session, manga)

    await run_in_db_threadpool(_check)
```
Measured: 12 SQL statements for 3 ids, 66 for 30 ids (≈2 per series). The
endpoint accepts up to 200 ids and backs the Bookmarks/History tab
(`src/components/BookmarkHistoryTab.jsx:122`).

**Why it matters**
Every library view costs O(n) queries, sessions and thread-pool hand-offs;
on a small database pool this is what saturates first under load.

**Confidence:** confirmed (measured).

### Pass 6 — async and background jobs

#### F-93 — Page translation blocks the API worker
**Severity:** HIGH · **Pass:** 6 · **Location:** `backend_fastapi/app/api/routers/processing.py:154`, `:295`

**Evidence**
```python
async def process_chapter_page(
```
```python
    try:
        result = cps.process_page(
            db,
            chapter=chapter,
```
`chapter_processing_service.process_page` (`chapter_processing_service.py:178`)
is a plain `def` that downloads the page, runs OCR and calls the translation
provider over HTTP. Gunicorn runs `2 × CPU + 1` Uvicorn workers
(`deployment/gunicorn.conf.py:27`), i.e. 3 on a 1-CPU server.

**Why it matters**
While one reader's page is OCR'd and translated (seconds), that worker
answers nobody: catalogue, reader pages and logins queue behind it. Three
concurrent translations on a 1-CPU host stall the whole API.

**Confidence:** confirmed (call path read; no `await`/thread-pool hop
around `process_page`).

#### F-94 — Blocking database calls inside async handlers
**Severity:** MEDIUM · **Pass:** 6 · **Location:** 49 handlers; hottest: `manga.py get_chapter_content`, `manga.py get_chapter_list`, `reader.py rate_manga/toggle_chapter_like`, `comments.py add_comment`, `auth.py request_magic_link`

**Evidence**
```python
manga.py get_chapter_content: db.query(Chapter).filter(Chapter.id == chapter_id, Chapter.manga_id == manga_id).first
manga.py get_chapter_list:    db.query(ReadHistory.chapter_id).filter(ReadHistory.user_id == user.id, ...).all
```
(AST scan of `app/api/routers/*.py`: `async def` functions taking a
`Session` and calling it, or passing it to a sync service, without a
thread-pool hop. Per file: site_admin 12, comments 5, auth 4, manga 4, ocr 4,
reader 4, account 3, admin_2fa 3, community 2, scraper_admin 2, others 1.)

**Why it matters**
Each query blocks the event loop for its round trip; under load the reader
path (`get_chapter_content` runs on every chapter open) serialises behind
the slowest query. A plain `def` handler would run in FastAPI's thread pool
instead.

**Confidence:** confirmed for the listed handlers; impact depends on DB
latency.

### Pass 7 — frontend

Build: `vite build` → `index-*.js` 680 kB (gzip 178 kB), `index-*.css` 163 kB
(gzip 38 kB), 96 font files (3.8 MB, fetched only when a face is used).
An `ErrorBoundary` wraps the app. `dangerouslySetInnerHTML` appears only for
admin ad code (`AdPlacement.js:92`, `GlobalAds.js:79`), sanitised server
side (`tests/test_ad_slots_xss.py`). No orphan modules.

#### F-95 — Admin console bundled for every reader
**Severity:** MEDIUM · **Pass:** 7 · **Location:** `src/app.js`

**Evidence**
```js
const AdminLogin = React.lazy(() => import("./pages/AdminLogin"));
```
is the only lazy route; the 12 `pages/Admin/*` screens (SeriesManagement
alone ~900 lines) are static imports, so they are in `index-*.js`.

**Why it matters**
Readers on slow phones download, parse and compile admin code they can never
open; first load and memory use on low-end devices suffer.

**Confidence:** confirmed (build output).

#### F-97 — Sub-admin tiles lead to pages they cannot open
**Severity:** MEDIUM · **Pass:** 7 · **Location:** `src/constants/adminFeatures.js`, `src/app.js`

**Evidence**
```js
    key: "chapter-reports",
    to: "/admin/chapter-reports",
    permission: "handle_reports",
```
```jsx
          path="/admin/chapter-reports"
          element={
            <AuthGuard requireAdmin>
```
`AuthGuard` admits sub-admins only with `allowSecondaryAdmins`
(`AuthGuard.js:62-69`). Same for `users` (`view_user_list`, route
`requireMainAdmin`), `health` (`view_dashboard`), `ads` (`manage_ads`).

**Why it matters**
Sub-admins with the permission (reports and dashboard are on by default) see
the tile, click it and are sent back to `/`; the backend would have allowed
them (`/admin/users`, `/reports/chapters` return 200 for them).

**Confidence:** confirmed.

#### F-98 — Provider permission toggles that guard nothing
**Severity:** LOW · **Pass:** 7 · **Location:** `backend_fastapi/app/core/permissions.py:54-59`

**Evidence**
```python
    "view_providers": (Group.PROVIDERS, True, True),
    "configure_ocr": (Group.PROVIDERS, True, True),
    "configure_translation": (Group.PROVIDERS, True, True),
    "configure_ai": (Group.PROVIDERS, True, True),
```
The live route table has no `require_permission` on any of these keys; the
provider endpoints use `require_main_admin_user`.

**Why it matters**
Role Management shows API-management powers as granted to sub-admins when
they are not; misleading, and a trap if a future route starts honouring them.

**Confidence:** confirmed.

### Translation overlay — verification

Path traced: `ReaderOverlay.js` → `GET /processing/chapter/{id}/page/{n}` →
`chapter_processing_service.process_page` (OCR → `ocr_normalize` →
`region_classifier.sample_background` → translation → coherence pass) →
regions with `coordinates`, `text`, `source_text`, `background`,
`text_color`, `background_clean` → `OverlayBox.js` (shrink-to-fit text over
a filled box). Field names agree end to end; untranslated regions are
skipped and reported. Covered by the OCR/translation/processing suites
(`test_ocr_workflow`, `test_processing_endpoint`,
`test_chapter_processing_service`, `test_translation_service*`), all green.
Not verified live: Tesseract is not installed in the audit container and no
translation provider key is available.

Bubble shape: today every translation is a rounded rectangle the size of
the OCR text box (`OverlayBox.js:98`, `borderRadius: "0.4em"`); nothing
measures the bubble's outline, so round and oval bubbles get a rectangular
patch. (Design note, not a defect; see Recommendations.)

### Pass 8 — config and ops

CORS comes from `resolve_cors_configuration(settings)`; API docs off in
production (`EXPOSE_API_DOCS`); nginx denies `.map`. Measured one fully
loaded app process at ~120-148 MB RSS.

#### F-96 — Default deployment needs ~2.5 GB RAM and never recycles workers
**Severity:** MEDIUM · **Pass:** 8 · **Location:** `docker-compose.yml:279-345`, `backend_fastapi/deployment/gunicorn.conf.py:27`, `backend_fastapi/app/core/celery_app.py`

**Evidence**
```python
_default_workers = 2 * multiprocessing.cpu_count() + 1
```
```yaml
  celery_worker_scrape:  ...  CELERY_CONCURRENCY: 1
```
Eight Celery worker services (prefork: parent + child each), beat, and
`2×CPU+1` Gunicorn workers; `celery_app.py` sets `worker_prefetch_multiplier = 1`
but no `worker_max_memory_per_child` / `worker_max_tasks_per_child`. DB pool
default 20 + 10 overflow **per process**.

**Why it matters**
A 1-2 GB server swaps or gets OOM-killed; Pillow/OCR workers that grow are
never restarted.

**Confidence:** confirmed (config read, RSS measured).

## Recommendations (in order)

1. **F-89 now.** Stop returning header values (names only) from
   `to_public_payload`, and put `/config/providers` behind sign-in. Then
   rotate any key that was ever stored in a custom provider header.
2. **F-91.** Scope `/admin/audit/logs` and `/search` to the caller's own
   rows unless they hold `view_full_audit`.
3. **F-93 (biggest speed win under load).** Run page OCR + translation off
   the event loop: `await run_in_threadpool(cps.process_page, ...)` as a
   minimum, or queue it to the existing `celery_worker_ocr` and let the
   reader poll (cached pages stay instant).
4. **Small-server profile (F-96).** Add a documented "small server" setup:
   one Celery worker consuming every queue (`--concurrency 1`,
   `--max-memory-per-child 300000`, `worker_max_tasks_per_child 200`),
   `GUNICORN_WORKERS=2`, DB pool 5+5, Redis `maxmemory 128mb` +
   `allkeys-lru`. Target: the whole site in ~1 GB RAM / 1 vCPU.
5. **F-92 / F-94.** Check rights for the whole batch in one query; turn the
   reader-path `async def` handlers that only do DB work into plain `def` (or
   wrap the DB part), starting with `get_chapter_content` and
   `get_chapter_list`.
6. **F-95.** `React.lazy` every `pages/Admin/*` route: readers stop
   downloading the admin console (expected main bundle well under half).
7. **F-97.** Make the admin tiles and the router agree (either let sub-admins
   with the permission open Users/Health/Ads/Chapter reports, or hide the
   tiles).
8. **Low items:** keep task references in `swr_cache` (F-86), allowlist
   `ALGORITHM` to `HS256/384/512` (F-87), put `/system/stats` behind the
   main admin or block it in nginx (F-90).

### Translation bubbles that follow the bubble's shape (design)

Today the overlay is a rounded rectangle the size of the OCR text box. To
make round, oval/egg and square bubbles get a matching patch:

- **Server (`region_classifier.py`, Pillow only, no new dependency):** from
  each text box's centre, cast ~48 rays outward over pixels close to the
  bubble fill colour (already sampled by `sample_background`) until the dark
  outline is hit. The hit points are the bubble's outline. From it derive:
  the bubble's bounding box, a simplified polygon (≤ 32 points, normalised
  to that box), and a shape class: *rectangle* (polygon fills ≥ 93 % of its
  box), *ellipse* (≈ 78 %, any aspect: circles and eggs), else *free-form*.
  When the art is busy (`background_clean` false) or no closed outline is
  found, fall back to today's box. Cost: a few thousand pixel reads per
  bubble.
- **API:** add `bubble: {shape, box, polygon}` to each region (old clients
  ignore it).
- **Reader (`OverlayBox.js`):** draw the fill over the bubble box with
  `clip-path: polygon(...)` (or `ellipse()` / square corners), inset 2-3 px
  so the original outline stays visible, and fit the translated text inside
  the shape's inscribed area (≈ 71 % of an ellipse's width/height), keeping
  the existing shrink-to-fit.
- **Setting:** "Bubble shape: match page / box" in Reading & Translation, so
  readers can switch back.

## Skipped or blocked

- **Live site, real OCR and real translation:** no deployed URL, Tesseract
  is not installed in the audit container, no provider key. Lighthouse and
  live latency numbers were therefore not produced.
- **Sentry (production errors):** the Sentry connector needs authorising.
- **Two source ranges** (`dependencies/auth.py` ~150-320, `routers/admin.py`
  ~290-520) could not be opened in this session; their routes were tested by
  calling them instead (F-88, F-91 come from that).

## Coverage notes

Read in full or by targeted ranges: routers for config, processing, manga
(batch/reader paths), community uploads, management, admin (settings,
session, audit handlers), permissions, provider registry, overlay
components, deployment (gunicorn, compose, nginx). Covered by measurement
rather than reading: every route's guards (route table), admin GETs as
sub-admin/reader, N+1 on reader lists, process memory, bundle size. Not read
line by line: most of `services/` (19.7k lines), migrations (checked by the
drift test), the OCR engine internals, community/comments services beyond
their entry points.
