# plan.md — what is wrong with the website and the plan to fix it

> **Nothing in this file has been fixed yet.** It is the result of a full read-through, the project's own checks,
> and live tests (real PostgreSQL 16, real nginx 1.24, the real backend, Chromium). It replaces any earlier plan:
> there was **no earlier `plan.md`** in this repository (I looked at every branch and the whole history), so this is the first.
>
> **When the owner says "fix the bugs":** read [`map.md`](map.md) first (how everything connects), then this file,
> ask the owner the questions in §2 that are still open, then work through §4 in order — one pull request per group,
> following §5. Do not start anything the owner has not named.

| | |
| --- | --- |
| Written | 2026-10-03, on `main` at `c66dc92` (merge of PR #45) |
| Baseline | `ruff` clean · backend 1256 passed / 7 skipped (PostgreSQL 16) · `tsc` clean · frontend 85 passed · `vite build` OK · Alembic chain applies on an empty database, one head. **Every automated check is green — the problems below are the ones the tests do not cover.** |
| Evidence tags | **[L]** reproduced live against the real services · **[S]** reproduced in the test client / simulation · **[R]** confirmed by reading the code only |

## 1. Summary

| Priority | Count | Meaning |
| --- | --- | --- |
| **P0** | 4 | The live site (Docker + Caddy, as `GUIDE.md` tells the owner to set it up) does not work, or the admin loses core functions. Fix before go-live |
| **P1** | 10 | Visitors or the owner see wrong results, or something private is exposed |
| **P2** | 15 | Medium: reliability, performance, correctness in corners, tooling that cannot fail |
| **P3** | 12 | Clean-up: dead code, stale docs/settings, features with no screen, small mismatches |

The four P0s in one breath:

1. **P0-1** Behind Caddy, every API call is answered with a redirect to `https://…` and loops (the web nginx tells the backend the request was plain HTTP). [L]
2. **P0-2** Behind Caddy, the backend sees **one visitor** (the Docker gateway): the 300-requests-a-minute limit becomes site-wide (about 20 page loads a minute locks everyone out, for up to an hour), nginx's per-visitor limits become site-wide, Geolock never blocks anyone. [L]
3. **P0-3** On PostgreSQL, **deleting a series, "delete all manga", bulk delete and "purge all images" fail with HTTP 500** as soon as a signed-in reader has opened a chapter or a page has been translated. [L]
4. **P0-4** After a Google or Microsoft sign-in the browser lands on the **404 page** (`…/auth/magic-complete` is what `.env.example`, `GUIDE.md` and the Secret Vault's domain switch all set, and the app has no such page). [L]

What is **not** broken (checked, so nobody re-checks): every one of the 232 API calls in the UI that names its URL matches a real route and method, and every request body I could read statically (all literal object bodies) uses only keys the backend's model accepts and sends all it requires; all 90 in-app links match a route; the migration chain applies on an empty PostgreSQL and ends at one head; `.env.example`/GUIDE variable names exist in the code; every compose service name in the guides exists; all 18 Site Functions have an enforcement point; all 119 `GET` routes called as guest, reader, sub-admin, Admin and owner (595 requests) gave no 5xx; visitor IPs are stored only when allowed and returned only to the owner; the CSP produced no violation in a real browser pass; e-mail sign-in, profile completion, bookmarks, ratings, history sync and the reader work end to end.

---

## 2. Questions for the owner (answer before the matching fix; "recommended" = what I will do if you say "go with your recommendations")

| # | Question | Needed by | Recommended |
| --- | --- | --- | --- |
| Q-1 | Keep the documented live shape **Caddy → web nginx → backend**? | PR-1 | **Yes.** Teach the web nginx to trust the proxy in front of it (real client address + `https`). Tell me if anything else (Cloudflare, a load balancer) sits before Caddy so its address range is trusted too |
| Q-2 | A taken-down series: what must happen to its **pictures**? **A)** delete the page and cover files and block the picture routes. **B)** A, plus short-lived signed picture URLs so "Sign-in required" and Geolock also cover pictures | PR-4 | **A** now (simple, certain, frees disk); **B** later only if you need pictures private while a series is live. Today nginx serves every picture to anyone who has the URL |
| Q-3 | Should visitors **never** see where chapters come from (source site, chapter links, raw image links)? | PR-4 | **Yes** — your roadmap item 3 says so. Staff keep seeing sources |
| Q-4 | Deleting a series: remove everything that points at it (reading history, chapter bookmarks, translation caches) automatically? | PR-2 | **Yes** — at the database level (cascade), so no code path can forget one |
| Q-5 | Genres: today a series stored with `["Action"]` can't be found by an "action" filter on PostgreSQL. OK to make matching case-insensitive (one new index, no data change)? | PR-5 | **Yes** |
| Q-6 | Features that exist on the server but have **no screen** (full list in §P3-4): build, hide, or remove? | PR-8 | Build the **takedown/rights** screen (needed for P1-2). Keep the rest API-only and documented. Switch the **Community** function **off by default** until it has pages. Remove the direct `/ocr/*`, `/translation/*` APIs (the reader uses `/processing`) |
| Q-7 | `.env` vs Secret Vault: ~78 infrastructure names (folders, pool sizes, proxy ranges, Gunicorn/Celery tuning) are still `.env`-only. Your rule says "every other setting belongs in the vault" | PR-8 | Keep them in `.env` and write this down as the one exception (they can't be changed safely at runtime) |
| Q-8 | `AntiTamperGuard`: prints "…will terminate the active session" (false), and blocks F12, Ctrl+S, Ctrl+U and right-click for everybody. It protects nothing and hurts accessibility | PR-8 | Remove the false claim and the blocking; keep only the right-click-on-a-series-card menu. Your call |
| Q-9 | The host-nginx / systemd way of running the site (`deployment/manga-site.conf`, `manga-frontend.service`, `manga-*.service`) can't start as written | PR-9 | **Delete it** (and say "Docker + Caddy only" in the docs). Fixing and maintaining a second path costs more than it saves |
| Q-10 | Account deletion/export exist on the server only. Add buttons in Settings? What may be kept after deletion (the encrypted e-mail identity keeps "one inbox, one account, for life")? | PR-8 | Add both buttons; keep only the e-mail identity hash |
| Q-11 | PostgreSQL: the running stack is **14**, CI tests **16**. | PR-7 | Run CI on both 14 and 16 (no data move). Upgrading the stack needs a dump/restore — do it later, separately |

---

## 3. Findings

Each finding says: **where**, **what happens** (with the evidence), **fix**, and **proof** (how to show it is fixed — these become tests where possible). Line numbers are for `c66dc92`.

### P0 — fix before the site goes live

#### P0-1 Every API call loops on redirects behind Caddy [L]
* **Where:** `deployment/nginx/site.conf` lines 103, 141, 185, 204, 226 (`proxy_set_header X-Forwarded-Proto $scheme;`); `server.ts:53`; `backend_fastapi/app/bootstrap/middleware.py` (`ForwardedHeadersMiddleware`, `HealthExemptHTTPSRedirectMiddleware`).
* **What happens:** the web container listens on plain HTTP (8080), so `$scheme` is `http`. nginx **replaces** the `X-Forwarded-Proto: https` that Caddy sent. The backend copies it into the request scheme and — because production needs `FORCE_HTTPS_REDIRECTS=true` (GUIDE §3.3: "leave it") — answers every API call except `/health`/`/healthz` with `307 → https://<host>/api/…`. The browser follows it back through Caddy and gets the same answer. The page itself loads (static files), nothing behind it works.
* **Evidence:** repo's `site.conf` + real nginx 1.24 + real backend (`FORCE_HTTPS_REDIRECTS=true`): `curl -H 'X-Forwarded-Proto: https' http://127.0.0.1:8080/api/v1/config/site-access` → `307 Location: https://127.0.0.1/api/v1/config/site-access`; the same request straight to the backend → `200`. An echo backend behind the same nginx received `X-Forwarded-Proto: http`.
* **Fix:** in `deployment/nginx/nginx.conf` (http level) add `map $http_x_forwarded_proto $fwd_proto { default $scheme; "https" "https"; }` and use `$fwd_proto` in all five places; **only accept the incoming value from the trusted proxy** (see P0-2: use the `real_ip` trusted list — e.g. `geo $realip_remote_addr $trusted_proxy { default 0; 127.0.0.1 1; 172.16.0.0/12 1; … }` and `map "$trusted_proxy:$http_x_forwarded_proto" $fwd_proto { "1:https" https; default $scheme; }` — the plain `map` was tested; this trusted-peer variant must be re-tested with R4). `server.ts`: take the incoming `x-forwarded-proto` only when the peer is private. Add the backend part (P2-2). Add a GUIDE §10 troubleshooting row: "Every request redirects / `ERR_TOO_MANY_REDIRECTS`".
* **Proof:** recipe R4 (§6): through nginx the backend must receive `https` when the proxy sent it and `http` when nothing was sent; `curl -sI https://<domain>/api/v1/config/site-access` on a real server returns 200. Add the harness as a CI job (P2-10).

#### P0-2 The backend sees one visitor behind Caddy [L]
* **Where:** `site.conf` lines 101–102, 139–140, 183–184, 202–203, 220–225 (`X-Real-IP` and `X-Forwarded-For` set to `$remote_addr`, which is the Docker gateway when Caddy connects through the published port); no `set_real_ip_from`/`real_ip_header` anywhere; `utils/client_ip.py`, `utils/rate_limiter.py`, `services/geolock.py`.
* **What happens (all follow from the code):**
  * generic limiter (`RateLimitMiddleware`, 300 requests / 60 s per address, repeat offenders blocked 60 s, 120 s, … up to 1 h) has **one bucket for the whole site**. A page load is about 15 API calls, so ~20 page loads a minute (by anyone, in total) block everybody; I hit this myself while smoke-testing from one address (59 of 119 calls came back 429);
  * nginx `limit_conn conn_per_ip 20`, `login_per_ip` (10 requests/min), `img_per_ip` (30 r/s) and `conn_img_per_ip` (30) become **site-wide** caps;
  * the per-IP Google-login cap (30 per 10 min) is shared; Geolock (`geoip` mode) receives a private address, `country_for_ip` returns `None`, and **nobody is ever blocked**; the owner-only IP in audit rows and ad clicks is the gateway.
* **Evidence:** echo backend behind the repo's nginx received `X-Forwarded-For: 127.0.0.1` for two different visitors (`203.0.113.9`, `198.51.100.77`) that the "Caddy" side had forwarded.
* **Fix:** http-level `set_real_ip_from` for loopback and the Docker/private ranges (and any extra proxy from Q-1), `real_ip_header X-Forwarded-For;`, `real_ip_recursive off;` — then `$remote_addr` is the real visitor and the existing `proxy_set_header … $remote_addr` lines become correct. Prototype tested: the backend then receives `203.0.113.9` / `198.51.100.77` and `https`; a spoofed `X-Forwarded-For: 1.2.3.4, 203.0.113.9` resolves to `203.0.113.9` (last hop). Document `TRUSTED_PROXY_CIDRS` next to it in GUIDE §8.
* **Owner rule that now bites:** "never write a visitor's IP address to a log line". Once real addresses reach nginx and gunicorn, their **default access logs print them**. In the same PR set `access_log off;` for `/api/` and static locations (or a `log_format` without `$remote_addr`) and give `GUNICORN_ACCESS_LOG` a default that omits the address (and turn the uvicorn access log off). Add a test or CI grep so it cannot regress.
* **Proof:** R4 shows distinct addresses at the backend; a test sends 400 requests from two forwarded addresses and only the noisy one gets 429; a Geolock test with a public address from a blocked country gets 451.

#### P0-3 Deleting series (and "purge all images") fails with HTTP 500 on PostgreSQL [L, PG 16; same FK rules on 14]
* **Where:** `routers/admin.py` `delete_series` (~2635), `tasks/scraper_tasks.py` `bulk_delete_series_task` (474), `routers/site_admin.py` `delete_all_manga` (493) and `purge_all_images` (525); foreign keys listed in map Appendix B.
* **What happens:** these paths delete chapters in bulk (`db.query(Chapter)…delete()`, which skips the ORM's cascades) and then the series. Seven foreign keys point at `chapters`/`manga` with `NO ACTION`: `read_history` (chapter, manga), `bookmarks` (chapter, manga), `ocr_cache.chapter_id`, `translation_cache.chapter_id`, `scraping_jobs.manga_id`; and `translation_cache.ocr_cache_id → ocr_cache` has the same rule.

  | Test on PostgreSQL | Result |
  | --- | --- |
  | `DELETE /admin/series/{id}`, series nobody read | 200 |
  | …series with one `read_history` row (every signed-in reader writes these since PR #45) | **500** |
  | …series with one `ocr_cache` row (any translated page) | **500** |
  | `POST /admin/maintenance/delete-all-manga` with one history row present | **500**, nothing deleted (6 series left) |
  | `POST /admin/maintenance/purge-all-images` with one translated page | **500** (it deletes `ocr_cache` before `translation_cache`) |

  Why the tests did not notice: they delete series nobody has touched, and SQLite does not enforce foreign keys.
* **Fix (Q-4 = yes):**
  1. Migration `20261018_cascade_series_children` (PostgreSQL branch): re-create `fk_bookmarks_chapter_id_chapters`, `fk_bookmarks_manga_id_manga`, `fk_read_history_chapter_id_chapters`, `fk_read_history_manga_id_manga`, `fk_ocr_cache_chapter_id_chapters`, `fk_translation_cache_chapter_id_chapters` with `ON DELETE CASCADE`, and `fk_translation_cache_ocr_cache_id_ocr_cache`, `fk_scraping_jobs_manga_id_manga` with `ON DELETE SET NULL` (both columns are nullable). Mirror `ondelete=` in `models/manga.py`, `models/translation_cache.py`, `models/scraping.py`. Downgrade restores `NO ACTION` (no data is lost: add the §2 row in `AUDIT_LOG.md` saying so).
  2. One `delete_series(db, manga_id)` service used by the route, the bulk task and delete-all: delete children explicitly (so it also works if a database missed the migration), delete the series, then the files (`page_image_service.delete_series_files`, the cover), commit per series.
  3. Delete-all and bulk delete run as a `maintenance`-queue task and answer `202` with progress (also fixes P2-1); "purge all images" deletes `TranslationCache` before `OcrCache` — and either really purges picture files or is renamed to what it does (it only drops the OCR/translation caches).
  4. Tests: PostgreSQL-backed (CI already has it) that create history, a chapter-level bookmark, OCR + translation rows and a scraping job, then call each endpoint; a SQLite fixture with `PRAGMA foreign_keys=ON` so ordinary unit tests catch this class of bug.
* **Proof:** recipe R3 prints 200 for every case; `python backend_fastapi/scripts/verify_alembic_chain.py`; Appendix B shows no `NO ACTION` pointing at `manga`/`chapters` except `chapters.manga_id`.

#### P0-4 Google / Microsoft sign-in ends on the 404 page [L browser + R]
* **Where:** `routers/auth.py:588` and `routers/account.py:334` redirect to `settings.magic_link_redirect_url or settings.frontend_url or "/"`; the value `…/auth/magic-complete` comes from `.env.example:128`, `GUIDE.md:397`, and `vault_keys.derived_from_domain` (`vault_keys.py:264`, used whenever the owner sets or changes the site domain), and `tests/test_secret_vault.py:334` asserts it. `src/app.js` has no `/auth/magic-complete` route.
* **What happens:** the cookies are set (a reload shows the visitor signed in) but the page after the provider says **"404 Page Not Found"**. First owner sign-in (GUIDE Part 4) and every reader sign-in. Real Google/Microsoft sign-in was never exercised in earlier bug tests.
* **Evidence:** Chromium on the production build: `/auth/magic-complete` → heading "Page Not Found".
* **Fix:** (a) add a route `/auth/magic-complete` that redirects to `/` (so values already stored in `.env` or the vault keep working); (b) change the generated/default value to `{base}/` in `vault_keys.derived_from_domain`, `.env.example`, the GUIDE §3.3 table and `test_secret_vault.py`.
* **Proof:** frontend test for the route; backend test that the callback's redirect target exists in the route table (`tests/_support/route_table.py` can read the SPA routes); browser check.

---

### P1 — wrong results or exposure

#### P1-1 Visitors can see where the content comes from [L, guest]
* **Where:** `routers/manga.py:208` (`/manga/batch`), `schemas/manga.py` (`ChapterBase.url`, `ChapterDetailResponse.chapter_url`), `services/catalogue_service.py` (`build_chapter_list_payload`), `services/image_proxy.py:36-58`.
* **What happens (guest, no sign-in):** `/manga/batch?ids=1` returns `source_url`, `last_error` (e.g. `403 from https://src…/x`), `added_by` (an admin's user id), `check_interval_hours`, `scrape_layout`; every chapter in `/manga/{id}/chapters` carries its source link in `url`, `/manga/{m}/chapters/{c}` returns `chapter_url`; pictures not yet mirrored are raw source URLs, or `/images/proxy?u=<base64>&r=<base64>` (signed, but **plain base64** — the source address is readable). Your roadmap item 3 ("source URL … admins only") was done for the list and detail routes only.
* **Fix (Q-3):** (a) pass `/manga/batch` through the same public model as the list (reuse `_hide_admin_fields` and a response model); (b) remove `url` / `chapter_url` from the public chapter schemas (the UI never reads them — verify with `grep`); staff get them from admin endpoints; (c) readers only receive mirrored pictures or an **opaque** proxy token (authenticated encryption, not base64), never a raw source URL; (d) contract test: seed a series whose `source_url`, chapter URLs and page URLs contain `source.invalid`, call every public GET as guest and reader, and assert that string appears nowhere in any response.
* **Proof:** the contract test; recipe R2 against the guest endpoints.

#### P1-2 Pictures ignore takedown, "Sign-in required" and Geolock; takedown has no screen [L]
* **Where:** `deployment/nginx/site.conf:151-170` (`alias`), `routers/reader.py:427-461` (`serve_cover`, `serve_page_image` — no rights or sign-in check either), `routers/admin.py` (`set_series_takedown` ~1527, rights routes), `SeriesManagement.jsx` (no call).
* **What happens:** takedown only sets `manga.takedown_status` and clears the caches. API reads then answer 451, but `GET /api/v1/manga/pages/1/1/0001-….webp` through nginx still returns `200 image/webp` for a guest; with "Sign-in required" switched on the API answers 401 and the same picture still 200; covers likewise; browsers and CDNs may keep them for a year (`immutable`). The nginx hotlink map does work (foreign `Referer` → 403) but allows an empty one. And **no screen calls takedown or the rights records**, so the owner cannot take a series down from the site at all.
* **Fix (Q-2):** **A)** a takedown service that, besides the status, deletes the series' page and cover files and the cached translations, and makes `serve_page_image`/`serve_cover` check `assert_series_hostable` (and `require_site_access`) for the backend path; **B)** (optional, later) signed short-lived picture URLs verified by nginx so "Sign-in required"/Geolock cover pictures. Add a **Takedown / rights** panel to `SeriesManagement.jsx` (status, reason, confirmation, audit entry shows in the audit report).
* **Proof:** recipe R4 + R2: after takedown the picture returns 404/410 through nginx; test that the file is gone; UI test for the panel.

#### P1-3 Browse filters only look at the 50 series on the current page [L browser]
* **Where:** `src/components/BrowseManga.js` lines 64-92 (request), 100-175 (client-side filtering), 92 (`totalResults`), 217 (`setPage(1)` only in "reset"), 669-672 ("Trending"), 762-772 (pager).
* **What happens (120 series, 24 of them Horror):** `/browse?genre=Horror` shows **10** cards (the Horror ones among the first 50) and the header still says "121 Comics"; genre include/exclude, tags, chapter range, minimum rating, "completed only", "translated" (≥ 50 chapters, an invented rule), "hide hiatus" and safe mode are all filtered in the browser over the one page of 50 that the request returned; the request sends only `search`, `status`, `type`, `sort`, `page`. The total falls back to the fixed number **7004** when the server total is 0 or missing; every card carries a fixed **"Trending"** badge; "Next" is never disabled; changing a filter keeps the old page number.
* **Fix:** send everything the server already supports (`q`/`search`, `genre`, `include`, `exclude`, `status`, `type`, `sort`, `page`, `per_page`); drop or re-think the filters the server cannot do (chapter range, rating, "translated", tags — either add real server parameters or remove the controls); show the server's `total`; compute pages from `total/per_page`; reset to page 1 on any change; remove the fixed badge and the 7004; do safe mode through `exclude=` so counts and pages stay right. Needs P1-6.
* **Proof:** frontend tests with a mocked API asserting the parameters sent; backend test that `include/exclude/genre` work with Title-Case data; browser check with the 120-series seed.

#### P1-4 Search and sort links go nowhere [L browser]
* **Where:** `Navbar.js:95` (`/browse?search=…`), `Homepage.js:778` (`/browse?sort=recently_added`), `MangaDetail.js:202` (`/browse?genre=…`); `BrowseManga.js:66-73` reads only `genre` (and only into a client-side list).
* **What happens:** typing "Series 077" in the navbar search opens Browse with 50 unrelated series and no 077; `sort=recently_added` is ignored (and is not a sort the server knows).
* **Fix:** make Browse's state come from the URL (`useSearchParams`): `search`, `sort`, `genre`, `status`, `type`, `page`; change the Homepage link to `sort=new` (valid sorts: `latest`, `new`, `popular`/`views`, `views_today`, `views_week`, `views_month`, `rating`, `az`/`title`, `chapters`, `random`).
* **Proof:** test that `/browse?search=x` calls the API with `search=x`.

#### P1-5 "Read now" and "latest chapter" links lose their chapter id [L]
* **Where:** `schemas/manga.py` `MangaBase` has no `first_chapter_id` / `latest_chapter_id`, so FastAPI drops them from `GET /manga/` and `GET /manga/{id}` (the response model is an allow-list); `catalogue_service.enrich` computes them; used by `Homepage.js:944`, `BrowseManga.js:31`; `/manga/batch` (a plain dict) keeps them, which is why the Bookmarks page works.
* **What happens:** every "▶ Read Now" opens the series page instead of chapter 1; the homepage update cards never show the latest-chapter link. No test asserts the fields.
* **Fix:** add both fields to `MangaBase` (`Optional[int]`). **Proof:** contract test that `GET /manga/` items contain both; Browse "Read Now" href in the browser pass.

#### P1-6 The genre filter finds nothing for real data on PostgreSQL [L, PG 16]
* **Where:** `services/manga_service.py` `apply_genre_filters` (lowercases the query, then `cast(genres, JSONB).has_key('action')` — case-sensitive); genres are stored as the sources give them (Title Case, e.g. MangaUpdates); every test fixture uses lower-case genres.
* **What happens:** `GET /manga/?genre=Action` and `?include=action` both return `total=0` for a series stored as `["Action","Comedy"]`. Browse hides it by filtering in the browser (P1-3); fixing P1-3 alone would expose it.
* **Fix (Q-5):** migration `…_genres_ci_index`: `CREATE INDEX ix_manga_genres_ci_gin ON manga USING gin ((lower(genres::text)::jsonb))`; query with `lower(genres::text)::jsonb ? :genre` (include) and its negation (exclude). No data change. **Proof:** PostgreSQL test with `["Action"]` returning for `genre=action` and `genre=Action`; the old lower-case tests still pass.

#### P1-7 Homepage "Most viewed" and "New" are computed from the 50 latest series [R + L]
* **Where:** `Homepage.js:175` (`sort: "latest"`, 50 items), `193-215` (client sorts).
* **What happens:** with more than 50 series the two sliders rank only the 50 most recently updated; a popular older series never appears. The server already has `sort=views_today|views_week|views_month|new`.
* **Fix:** request each slider with its own `sort` (small `per_page`), cached by React Query. **Proof:** frontend test of the requests.

#### P1-8 A series with chapter 0 opens the wrong chapters [L browser]
* **Where:** `MangaDetail.js:128-131, 308` (`Number(ch.chapter_number || ch.id)` — `0` is falsy so the **id** is used as the sort key), button label `Ch. {chapter_number || id}`.
* **What happens:** for a series with chapters 0, 1, 2: "Read Latest (Ch. 3)" opens **chapter 0**; "First Chapter" opens chapter 1.
* **Fix:** use the server's `latest_chapter_id`/`first_chapter_id` (P1-5) or compare `chapter_number ?? Infinity`; label with `chapterLabel(ch)`. **Proof:** frontend test with chapters 0, 1, 2.

#### P1-9 The non-Docker way of running the site cannot start; the developer quick-start leaves queues unserved [L nginx -t]
* **Where:** `deployment/manga-site.conf`, `deployment/manga-frontend.service`, `backend_fastapi/deployment/manga-worker.service`, `README.md` and `backend_fastapi/README.md`.
* **What happens:** `nginx -t` on `manga-site.conf`: `"env" directive is not allowed here` (line 34); used as the main config as `manga-frontend.service` does (`nginx -c`): `"server" directive is not allowed here`; and `limit_req_zone … rate=$api_rate_hourly` is not a valid rate. Even if loaded it lacks the SEO proxy and limits **every** `/api/` call (pictures included) to 500/hour and 2000/day per address. `manga-worker.service` has no `CELERY_QUEUES`, so only the `default` queue is consumed (sign-in e-mails, notifications, scraping never run). The README tells developers to run `celery … worker -Q scrape,celery` — the default queue is called `default`, not `celery`, and `email`, `notifications`, `ocr`, `translation`, `maintenance`, `compress` are not listed, so **no sign-in e-mail is sent in the developer setup**.
* **Fix (Q-9):** delete the host-nginx/systemd files and say "Docker + Caddy only" in `deployment/README.md`, GUIDE §8 and `AUDIT_LOG.md` §5; correct the README command to the full queue list (`-Q default,scrape,compress,ocr,translation,email,maintenance,notifications`). If the owner wants the host path, instead rewrite it as a full `nginx.conf` and give the systemd worker the queue list.
* **Proof:** `nginx -t` on every remaining nginx file in CI (P2-10).

#### P1-10 Admin screens say "saved" when the server refused [R]
* **Where:** `ApiManagement.jsx:134-205` (save → on **any** error shows "✅ … saved locally", delete → "✅ Deleted"), `FooterEditor.js:158, 175, 180, 193, 202, 212` (update, toggle, delete, move social links: error → success message and the change stays only in the editor), `pages/Admin/ApiManagement.jsx` + `services/apiRegistry.js` (a browser-side copy of ~40 provider presets).
* **What happens:** an owner who enters a translation provider and key while a step-up code is missing, or the https-only check fails, or the network blips, sees a green "saved" while **nothing** is stored on the server — translation then silently does not work. Deleting a provider that the server refused to delete shows "Deleted" until the page reloads. The footer editor changes what the owner sees, not what visitors see.
* **Fix:** show the server's error message; never fall back to a local-only save; do not keep a browser copy of the registry (the server is the only list); same for the footer editor (reload from the server response). Remove the in-browser presets (P3-1).
* **Proof:** frontend tests that mock a failing API and expect an error notice and no success.

---
### P2 — medium

| ID | Finding (evidence) | Where | Fix | Proof |
| --- | --- | --- | --- | --- |
| **P2-1** | **A 5-second limit applies to every admin action** except OCR, translation, backups and geolock (`REQUEST_TIMEOUT_SECONDS`, default 5). `delete-all-manga`, `mirror-all-images` and a large `DELETE /admin/series/{id}` (with its picture folder) can exceed it: the admin gets a 504 while the thread keeps working. `delete-all-manga` also loads every series into memory with one ORM loop and leaves the cover files behind. [R] | `bootstrap/timeout.py`, `routers/site_admin.py:493`, `routers/admin.py` | long jobs become `202` + a Celery task with progress (done together with P0-3); exempt only what must stay synchronous; delete covers in delete-all | test that delete-all returns 202 and finishes in the worker |
| **P2-2** | `ForwardedHeadersMiddleware` believes `X-Forwarded-Proto/Host/Port` from **any** peer (the client address is checked, these are not). A client that can reach the backend port can claim `https` or another host. [R] | `bootstrap/middleware.py:183-222` | apply the same trusted-peer check (`utils/client_ip._is_trusted_peer`) to proto, host and port | unit test: untrusted peer + `X-Forwarded-Proto: https` stays `http` |
| **P2-3** | Microsoft sign-in has **no per-address limit**: its two routes lack `_limit_login_attempts` (Google's have it) and the nginx rule lists `google\|callback\|request-magic-link\|magic\|magic-link` but not `microsoft`. [R] | `routers/account.py:269,303`, `site.conf:195` | add the dependency and add `microsoft` to the nginx regex | test like `test_login_ip_rate_limit` for Microsoft |
| **P2-4** | A chapter view by a **guest** (or a bot) is never de-duplicated: every `GET /manga/{m}/chapters/{c}` runs three `UPDATE`s (`chapters.views`, `manga.views`, `manga_daily_views`) on hot rows; the numbers drive the "most viewed" lists. Signed-in readers are de-duplicated for 30 minutes. [L: a guest request moved `views` 0 → 1] | `services/catalogue_service.py:record_chapter_view` | count guests through a short-lived Redis key per anonymous visitor token (a cookie value, **not** the IP), or batch counts in Redis and flush from beat | test: two guest requests with the same token count once |
| **P2-5** | **Uploaded-file URLs 404 through the web nginx**: `/api/user/profile-image/x.webp`, `/api/community/memes/file/x.webp`, `/api/v1/branding/assets/x.png` match the static-extension regex before `location /api/`, and `/branding/assets/…` (the URL branding stores) is not proxied at all. [L: real nginx → 404 `text/html`] No screen produces these URLs today (no logo/avatar upload UI), so it is latent. | `site.conf:239`, `routers/branding.py:58` (`/branding/assets/`), `user_settings.py:59`, `meme_service.py:41` | make `location ^~ /api/` win (or add the extensions only outside `/api/`); make branding URLs `/api/v1/branding/assets/…` | R4 shows 200 from the backend for these paths |
| **P2-6** | The **service worker caches every image forever** (`cache-first`, `manga-reader-cache-v1`, no size limit, no expiry): a reader's device fills with pages; a taken-down series stays viewable on devices that opened it; offline navigations return `undefined`. [R] | `public/sw.js` | cache covers only (with a size cap), network-first for pages, version/expire the cache, return a real offline response | manual + unit test of the fetch handler |
| **P2-7** | **Ads cost 6 requests per page and half of them can never show:** `AdSection`/`AdPlacement` each call `GET /ad-slots` on mount (6 on the homepage); the `AdSection` keys `global`, `browse_header`, `header_row_2`, `footer_row_1/2` are **not in the placement catalogue** (`services/ad_placements.py`), so a slot assigned in the admin panel never matches them. HTML/iframe ads are blocked by the CSP (`frame-src 'self'`) although the sanitiser allows cross-origin `<iframe>`. [L: 15 API calls on first load, `/ad-slots` ×6] | `components/GlobalAds.js`, `AdPlacement.js`, `app.js:71,81`, `site.conf` CSP | one shared `useQuery(["adSlots"])`; remove or catalogue the `AdSection` mounts; decide iframe ads (allow named ad origins in `frame-src`, or strip iframes in the sanitiser) | frontend test: one request per page; browser pass |
| **P2-8** | `mutation.isLoading` does not exist in TanStack Query 5 (`isPending`): the buttons never disable, so a double click sends two requests (rating, **re-scrape**, **resolve**, **delete** report). [R, type-check with `checkJs`] | `MangaDetail.js:240`, `ChapterReports.jsx:259,271,283` | use `isPending` | test that a second click is ignored |
| **P2-9** | A signed-in reader's **bookmark add/remove that fails is dropped** (`.catch(() => {})`, unlike history, which is re-queued); at the next sign-in the local list is replaced by the server's, so the bookmark silently disappears. [R] | `components/BookmarkSync.jsx:41-44`, `utils/library.js` (`withChange`) | on failure put the change back in `pending` | extend `BookmarkSync.test.jsx` |
| **P2-10** | **CI cannot fail where it claims to check:** the "index.html carries no inline script" step uses `grep -qE` with a lookahead (`(?!…)`), which ERE does not support — on a file that does contain an inline script it exits 1 (no match) and the step passes. [L] Other gaps: `npm run lint` is `tsc` with `checkJs` off (almost all code is `.js/.jsx`, unchecked), no ESLint, no `nginx -t`, no `docker compose config`, no Docker build, no end-to-end test. | `.github/workflows/ci.yml:156`, `tsconfig.json` | `grep -P` (or a tiny node script); add jobs: `nginx -t` on every nginx file in a container, `docker compose config` for all three compose files, the R4 harness; enable `checkJs` per folder or add ESLint | break the check on purpose in a throw-away PR and see it fail |
| **P2-11** | **Homepage announcements:** the new entry gets `id: Date.now()` (the server's id differs, so "delete" 404s until reload) and a failed request is swallowed ("Local fallback active") — the admin believes it is live. [R] | `Homepage.js:230-285` (`handlePublishBroadcast`, `handleDeleteNotice`) | use the response's `announcement.id`; show the error | frontend test with a failing API |
| **P2-12** | The series list's **"next check in …"** parses a naive-UTC time with `new Date(iso)`, i.e. as local time: off by the admin's UTC offset. [R] | `SeriesManagement.jsx:20-25` (use `parseUtc`) | use `parseUtc` | test with a non-UTC `TZ` |
| **P2-13** | **User Database and Role Management download every account** (`GET /admin/users/all`, unpaginated) and filter in the browser; the paginated, searchable `GET /admin/users` is unused. At tens of thousands of accounts this is slow and hits the 5 s limit. [R] | `UserDatabase.jsx:58`, `RoleManagement.jsx:412`, `routers/admin.py:2189` | use `/admin/users?page&search`; drop the alias | test for pagination |
| **P2-14** | CI tests **PostgreSQL 16**; the compose stack runs **14** (and the backend image carries the 17 client). Behaviour can differ. | `.github/workflows/ci.yml`, `docker-compose.yml:111` | CI matrix 14 + 16 (Q-11) | CI green on both |
| **P2-15** | Guests get a **red 401 `GET /auth/me` in the console on every page**; the **Report** button is shown to guests and sending it redirects to `/login`, losing the typed text. [L] | `AuthContext.js` (`loadMe`), `ChapterViewer.js` | hide Report for guests (or ask to sign in first, keep the text); let `/auth/me` answer `200 {user:null}` for guests (needs a contract + test change) or skip the call when no sign-in could exist | browser pass: no red errors for a guest |

### P3 — clean-up

| ID | Finding | Where | Fix |
| --- | --- | --- | --- |
| **P3-1** | **In-browser OCR is gone but still advertised** (your rule: translation runs on the server): the API Management presets list "Tesseract.js (On-device OCR) … runs entirely in the browser" and "Argos Translate (local)"; the CSP and nginx comments describe `wasm-unsafe-eval`, `worker-src blob:` and `connect-src https:` for OCR engines; `.env.example` has `REACT_APP_PPOCR_*`; `src/config.js` and `api.js` mention `REACT_APP_*` (never read by Vite). | `src/services/apiRegistry.js`, `site.conf:20-62`, `manga-site.conf`, `.env.example:432-441`, `src/config.js`, `api.js:~190` | delete the presets and comments; tighten the CSP to `script-src 'self'`, `worker-src 'self'`, `connect-src 'self'` once the browser pass is clean; remove the dead env lines |
| **P3-2** | `AntiTamperGuard` (Q-8). | `src/components/AntiTamperGuard.jsx` | per the answer |
| **P3-3** | **Dead code and endpoints.** Server: `GET /manga/browse` (sunset 2026-07-01 passed), `GET /config` (always `{}`), `/backup/*` (replaced by `backups_admin`), `/admin/ads`, the legacy `/ads/`, `/ads/slots`, `/ads/config`, `/admin/providers*` + `/admin/system-providers*` (duplicates of `/admin/api-registry`), `POST /tasks/test` (a test endpoint left mounted), `suggestion_service` (broken: `.overlap` on a JSON column) and the two **no-op beat tasks** (`flush_audit` every 5 min, `suggestion-scan` hourly), tables `admin_bootstrap_state` and `complaints`, 13 `Settings` fields (`supabase_*`, `rate_limit_per_*`, `api_base_url`, `celery_worker_concurrency`, `monitor_*`, `app_host/port`), `users.password_hash`. UI: 74 of 170 `api.js` helpers are never called (some are bypassed by raw `apiFetch("/api/v1/…")` calls — two styles for the same thing), and the chapter-like handler/state without a button. | see map §11 | delete after Q-6; one migration drops the two tables and the unused column; unify on the `api.*` helpers |
| **P3-4** | **Features with no screen** (143 of 306 route/method pairs have no caller): takedown/rights (→ P1-2), reveal a user's e-mail, revoke a user's sessions, flagged-user review, audit log list/search, session policy, access config, cache admin, scheduled-checks dashboard, scraper/source health, storage report, mirror-all-images, bulk delete, batch schedule, approved domains and parser versions, account **export** and **delete**, profile-picture and logo **upload**, comment edit/vote/react/report/moderation, notification preferences, the 17 **Community** routes, glossary, `/ocr/*`, `/translation/*`. | map Appendix A | per Q-6, Q-10 |
| **P3-5** | **Schema drift** (models vs a migrated PostgreSQL): `users.role` and `provider_credentials.created_at` are nullable in the database but `NOT NULL` in the model; `sources.name` is `varchar(100)` vs 255; `scraping_jobs.error` is `varchar` vs `Text`; extra nullable columns `ad_slots.config`, `read_history.created_at`, `sources.parser_type`; two identical unique indexes on `scraping_jobs.source_url`; `bookmarks` and `read_history` have no unique `(user_id, chapter_id[, manga_id])` (the code works around races); several index/constraint names differ. | `models/*`, migrations | one tidy migration (after P0-3) + unique constraints with a de-duplicating step |
| **P3-6** | **Docs that disagree with the code:** README dev command (P1-9); `backend_fastapi/README.md` says `PAGE_MAX_WIDTH` 1280 (code, `.env.example`, GUIDE: 1440); `backend_fastapi/audit/*.md` link to a `docs/` folder that is not in this repository; GUIDE §8 Step 7 says Caddy "sends `X-Forwarded-Proto`, which the backend uses to avoid redirect loops" (true only after P0-1/P0-2); `AUDIT_LOG.md` §5 says Geolock does not cover pictures (still true, and so does "Sign-in required"). | README files, GUIDE, `backend_fastapi/audit` | fix together with the code PRs |
| **P3-7** | The site has **three built-in names** — `Manga Reader` (`index.html`, manifest), `Manga World` (login page), `MangaWorld` (`config.js` default, library export file name) — besides whatever the owner saves as branding. | `index.html`, `public/manifest.json`, `Login.js:53`, `config.js`, `Navbar.js` | read the saved name everywhere; neutral defaults |
| **P3-8** | **Small UI ↔ API mismatches:** Settings expects `user.age_locked` (never sent; the server refuses a changed birth date on save instead); the reader's alert banner reads `details` but the API sends `message`; `<Router future={{v7_…}}>` is not a prop of React Router 7; `ChapterViewer` falls back to `chapter.all_chapters` / `image_urls` that no response has; "completed" status filter missing in `/admin/series` (`400`) and its list returns `chapters_count` 0 (unused route). | `SettingsPage.tsx:158`, `ChapterViewer.js:326`, `app.js:298`, `routers/admin.py:2601` | tidy |
| **P3-9** | **nginx hygiene:** two `Cache-Control` headers on static files (`expires` plus `add_header`); `sw.js` and `favicon.ico` served `immutable` for a year; the host config's `proxy_cookie_flags ~*jwt` matches no cookie name (`access_token_cookie`); CSP comments out of date (P3-1). | `site.conf:239-247`, `manga-site.conf` | tidy |
| **P3-10** | **Privacy/security notes:** with the owner's `ip_owner_only` switch **off**, staff can read visitor IPs in the audit log (your rule says never — the switch is the owner's explicit choice; document it); sitemap/RSS fall back to the `Host` header when `FRONTEND_URL` is unset (`routers/seo.py`); `GET /manga/` accepts an unbounded `q` that becomes part of a Redis key (`search` is capped at 200); `DELETE /user/me` keeps the encrypted e-mail, birth date and the person's comments/ratings (decision Q-10); the direct `/ocr/*` and `/translation/*` APIs are open to any signed-in user with their own limits. | `routers/manga.py:134`, `seo.py:20` | cap `q`; require `FRONTEND_URL` for feeds; per Q-6/Q-10 |
| **P3-11** | **Tooling gaps:** `tsc` sees almost no `.js/.jsx` (P2-10); frontend tests cover 21 files only (not Homepage, Browse, MangaDetail, Settings, Notifications, ads, most admin pages); the backend suite stubs `httpx`, runs most tests on SQLite without foreign keys, and uses lower-case genres only. | `tsconfig.json`, `tests/conftest.py` | add tests with each fix; `PRAGMA foreign_keys=ON` for SQLite fixtures |
| **P3-12** | **Performance notes:** `get_chapter_content` loads every chapter id of the series to find previous/next; `report_to_dict` does three `get` calls per report (N+1 on the report list); `_genres()` scans every series' genres on each list-cache rebuild; chapter lists are unpaginated; `GET /chapters/{id}/reports` is called for staff every 10 s; `/admin/series` returns every series without `enrich`. | `routers/manga.py`, `routers/reader.py`, `catalogue_service.py` | batch queries; paginate when lists grow |

---

## 4. Order of work — one pull request per group

Do P0 first (PR-1, PR-2 and PR-3 do not depend on each other and can be done in parallel). Each PR follows §5.

| PR | Contents | Needs answers | Migration | Main files | Done when |
| --- | --- | --- | --- | --- | --- |
| **PR-1 Make the live stack work** | P0-1, P0-2, P2-2, P2-3, P3-9 (nginx part) | Q-1 | none | `deployment/nginx/{nginx,site}.conf`, `server.ts`, `bootstrap/middleware.py`, `routers/account.py`, `gunicorn.conf.py`, GUIDE §8/§10 | R4 passes (distinct addresses, `https` preserved, no visitor IP in any access log); new backend tests green; GUIDE has the "redirect loop" row |
| **PR-2 Deleting works** | P0-3, P2-1 | Q-4 | `20261018_cascade_series_children` (lossless downgrade) | `models/{manga,translation_cache,scraping}.py`, `routers/{admin,site_admin}.py`, `tasks/scraper_tasks.py`, new `services/series_delete.py`, tests | R3 prints 200/202 for every case on PostgreSQL; chain check passes; AUDIT_LOG §2 row added |
| **PR-3 Sign-in landing** | P0-4 | none | none | `src/app.js`, `vault_keys.py`, `.env.example`, GUIDE §3.3, `tests/test_secret_vault.py` | browser: OAuth landing shows the home page; route test |
| **PR-4 Privacy and rights** | P1-1, P1-2 | Q-2, Q-3 | none (or one if takedown needs a column) | `routers/manga.py`, `schemas/manga.py`, `catalogue_service.py`, `image_proxy.py`, `routers/reader.py`, new takedown service, `SeriesManagement.jsx` | the contract test finds no source host in any public response; after takedown the picture is gone through nginx and the backend; takedown screen works |
| **PR-5 Reading pages show the right things** | P1-3, P1-4, P1-5, P1-6, P1-7, P1-8, P3-8 (reader bits) | Q-5 | `…_genres_ci_index` (index only) | `schemas/manga.py`, `manga_service.py`, `BrowseManga.js`, `Homepage.js`, `MangaDetail.js`, `Navbar.js` | the 120-series browser pass shows 24 Horror titles over their own pages, the true total, working search/sort links, "Read Now" opening chapter 1, chapter 0 handled |
| **PR-6 Admin screens tell the truth** | P1-10, P2-8, P2-11, P2-12, P2-13, P3-1 (presets) | — | none | `ApiManagement.jsx`, `FooterEditor.js`, `Homepage.js`, `ChapterReports.jsx`, `MangaDetail.js`, `UserDatabase.jsx`, `RoleManagement.jsx`, `apiRegistry.js` | failing-API tests show errors; no browser registry copy |
| **PR-7 Hardening and speed** | P2-4, P2-5, P2-6, P2-7, P2-9, P2-10, P2-14, P2-15, P3-11, P3-12 | Q-11 | none | `catalogue_service.py`, `site.conf`, `public/sw.js`, ads components, `BookmarkSync.jsx`, `ci.yml` | CI has the new jobs and a deliberately broken input fails them |
| **PR-8 Clean-up** | P3-1 (rest), P3-2, P3-3, P3-4, P3-5, P3-6, P3-7, P3-10 | Q-6, Q-7, Q-8, Q-10 | one tidy migration (drop `admin_bootstrap_state`, `complaints`, `users.password_hash`; constraints) | many | `AUDIT_LOG.md` lists every removal; map.md §11 updated |
| **PR-9 Alternative deployment** | P1-9 | Q-9 | none | `deployment/*`, README files | `nginx -t` on every remaining nginx file |

---

## 5. Rules for the fixing session (from `CLAUDE.md` and the owner's habits)

1. Read `CLAUDE.md`, `map.md` and this file. Do only what the owner named. Ask the open questions in §2 first.
2. **Every pull request** adds an entry at the top of "Change entries" in `AUDIT_LOG.md` (template at the end of that file): what changed, why, main files, migrations, settings, how to check, how to undo. Every migration gets a row in §2 saying what its downgrade does ("lossless" or "**lossy**"). Update `GUIDE.md` (the section, the troubleshooting table, the quick checklist) when install/config/update/operation changes. Update `AUDIT_LOG.md` §1 when a setting moves between `.env`, the vault and Admin Settings, when roles/permissions change, or when a server-side command is added. Keep `map.md` and this file in step (tick items off here; edit Appendix A/B of the map if routes or foreign keys change).
3. House rules to keep while fixing: only DB/Redis, site address, signing/encryption keys and admin identity in `.env`; four roles and the power rules; Site Functions and Tab access owner-only (every new function gets an entry in `core/site_functions.py` with a real enforcement point, every admin tab one in `core/admin_tabs.py`); visitors' IPs only for the owner and never in a log line; history/bookmarks stay in the browser as the main copy; no reader passwords; translation on the server; no hard-coded admin e-mails; keep the UI looking and behaving the same unless an item says otherwise; keep model names and session links out of the repository.
4. **Checks before every push** (from `CLAUDE.md`): `ruff check backend_fastapi` · `python -m pytest backend_fastapi/tests -q -p no:warnings` (PostgreSQL; **never** a database that holds real data — the fixtures drop all tables) · `npx tsc --noEmit && npx vitest run && npx vite build`. For migrations also `python backend_fastapi/scripts/verify_alembic_chain.py` on an empty database. For nginx changes run `nginx -t` and the R4 harness. Say plainly what was only read and what was run.
5. One branch and one pull request per group in §4. The project's own roadmap rule is to open a pull request only when the owner asks for one — follow what the owner says at the time; either way commit with a clear message and report what was run and what was only read.
6. Each fix gets a **regression test that fails on `c66dc92`**: the recipes in §6 are the failing cases.

---

## 6. How I tested — recipes to reproduce every [L] result

Setup used here: Python 3.11 venv with `backend_fastapi/requirements.lock` + `pytest pytest-timeout pytest-env ruff`; `npm ci`; a throw-away PostgreSQL 16 (`CREATE USER manga SUPERUSER`; databases `manga_test`, `manga_migrations`) and a Redis; nginx 1.24 from apt; Chromium + Playwright (pre-installed).

**R1 — import the app without a `.env`**

```bash
export PYTHONPATH=$PWD JWT_SECRET_KEY=t SECRET_KEY=t MAGIC_LINK_SECRET=t INTEGRATIONS_SECRET=t \
  EMAIL_ENCRYPTION_KEY="XbI7VwMT8sh/IVCrqyVYgK8/XWiwxupCSvJzpuG1Hs8=" OCR_MODE=remote REMOTE_OCR_URL=https://example.com/ocr \
  ALLOW_PLAINTEXT_SECRETS=1 TESTING=1 FORCE_HTTPS_REDIRECTS=false CELERY_BROKER_URL=memory:// CELERY_RESULT_BACKEND=cache+memory:// \
  REDIS_URL= GENERIC_RATE_LIMIT_REQUESTS=100000 DATABASE_URL=sqlite:////tmp/x.db     # or a PostgreSQL URL for R3
```
Route/guard table (map Appendix A): walk `build_api_router().routes` recursively — `_IncludedRouter` objects expose `original_router` and `include_context` (prefix, dependencies); read each route's `dependant` for the guards.

**R2 — guest leaks (P1-1, P1-5)**: with R1 on SQLite create tables (`Base.metadata.create_all(engine)`), insert a `Manga` with `source_url="https://src.example/s/1"`, `last_error="403 from https://src.example/x"`, `added_by=7` and chapters numbered 0, 1, 2, then `TestClient(app)`: `GET /api/v1/manga/batch?ids=1` (leaks), `/manga/1/chapters` (`url`), `/manga/` (no `first_chapter_id`).

**R3 — deletes on PostgreSQL (P0-3)**: R1 with `DATABASE_URL=…/manga_migrations` after `alembic upgrade head`. Create an owner (`role=PERMANENT, is_main_admin=True`) and a reader; a series with one chapter; add `ReadHistory`, `Bookmark(chapter_id=…)`, `OcrCache(chapter_id=…, page_index=0, text_boxes=[])` or `TranslationCache(…, ocr_cache_id=…)`; call with `Authorization: Bearer <create_access_token(owner_id)>`: `DELETE /api/v1/admin/series/{id}`, `POST /api/v1/admin/maintenance/delete-all-manga`, `POST /api/v1/admin/maintenance/purge-all-images`. Expected today: 500. Expected after PR-2: 200/202 and the child rows gone.

**R4 — the Caddy → web nginx → backend chain (P0-1, P0-2, P2-5, P1-2)**: copy `deployment/nginx/nginx.conf` and `site.conf`, change `pid`, add `error_log`/`access_log` and the `*_temp_path` directives under a writable folder, point `root`/`alias` at a built `dist/` and a pictures folder, add `127.0.0.1 backend` to `/etc/hosts`, `nginx -t -c … && nginx -c …`. Start the real backend with `uvicorn backend_fastapi.app.main:app --port 8000` (`FORCE_HTTPS_REDIRECTS=true`) and probe: `curl -si -H 'X-Forwarded-Proto: https' -H 'X-Forwarded-For: 203.0.113.9' http://127.0.0.1:8080/api/v1/config/site-access` (today **307**). Swap the backend for a 15-line Python echo server that prints `X-Forwarded-For`/`-Proto` to see what the backend receives. The tested fix is four lines in the `http {}` block (`set_real_ip_from … ; real_ip_header X-Forwarded-For; real_ip_recursive off; map $http_x_forwarded_proto $fwd_proto { default $scheme; "https" "https"; }`) plus `$fwd_proto` in place of `$scheme`.

**R5 — browser pass (P1-3 … P1-8, P0-4)**: seed 120 series (five genres in Title Case) plus one series with chapters 0, 1, 2; run the production build behind R4's nginx; Playwright/Chromium as a guest: first page load (count API calls, `/ad-slots`), navbar search "Series 077" (expect the URL's `search` to be applied), `/browse?genre=Horror` (expect 24 titles over pages), a series page ("Read Latest" must be chapter 2, "First Chapter" chapter 0), `/auth/magic-complete` (today "Page Not Found"). Signed in: `python -m backend_fastapi.scripts.cli_bootstrap login-link --email … ` gives a one-time link; bookmark, rate, read two chapters and watch `POST /bookmarks`, `/history/sync`, `/history/read`.

**R6 — take-down and sign-in-required vs pictures (P1-2)**: put a real `.webp` under `<alias>/1/1/0001-aaaaaaaaaa.webp`; set `manga.takedown_status='taken_down'`; compare `GET /api/v1/manga/1/chapters/1` (451) with `GET /api/v1/manga/pages/1/1/0001-aaaaaaaaaa.webp` through nginx (today 200); then `system_settings.login_required=true` and repeat as a guest.

**R7 — CI lookahead (P2-10)**: `printf '<script>alert(1)</script>' > t.html; grep -qE '<script(?![^>]*\ssrc=)[^>]*>[^<]' t.html; echo $?` prints **1**; `grep -qP` prints 0.

---

## 7. What I could not verify here

* The real **Docker images and compose stack** (no Docker daemon): the web/nginx behaviour was reproduced with the repo's own nginx files, real nginx 1.24 and the real backend; the *Docker gateway address* itself (what `$remote_addr` is inside the container when Caddy connects through the published port) is the standard Docker behaviour but was not observed.
* **Caddy** itself and real HTTPS; real **Google/Microsoft** sign-in (the landing-page bug was shown by visiting the URL the redirect uses); real **SMTP**; real **source sites**, **MangaUpdates/Anime-Planet**, **OCR/translation providers**; **S3** backups; the systemd/k8s files (read, not run); the **PostgreSQL 14** server (tests ran on 16; the foreign-key rules and the genre operator behave the same).
* The admin pages were not clicked through (the 2026-10-03 bug test already did, with no console errors); I checked their API calls and payload keys by script instead.

---

## 8. Tick-list (update as items are done)

| ID | Status | PR | ID | Status | PR | ID | Status | PR |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0-1 | todo | | P1-9 | todo | | P2-12 | todo | |
| P0-2 | todo | | P1-10 | todo | | P2-13 | todo | |
| P0-3 | todo | | P2-1 | todo | | P2-14 | todo | |
| P0-4 | todo | | P2-2 | todo | | P2-15 | todo | |
| P1-1 | todo | | P2-3 | todo | | P3-1 | todo | |
| P1-2 | todo | | P2-4 | todo | | P3-2 | todo | |
| P1-3 | todo | | P2-5 | todo | | P3-3 | todo | |
| P1-4 | todo | | P2-6 | todo | | P3-4 | todo | |
| P1-5 | todo | | P2-7 | todo | | P3-5 | todo | |
| P1-6 | todo | | P2-8 | todo | | P3-6 | todo | |
| P1-7 | todo | | P2-9 | todo | | P3-7 … P3-12 | todo | |
| P1-8 | todo | | P2-10 / P2-11 | todo | | | | |
