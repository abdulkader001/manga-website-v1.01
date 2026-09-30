# Backend security review — 2026-09-30

Method: read the code and ran the checks below; nothing here is from memory.

## In place (checked)

- Emails are stored encrypted and looked up by keyed hash; passwords use
  Argon2id with per-user salt and lockout (8 failures → 15 minutes); OAuth
  tokens and AI/API keys are encrypted at rest and shown masked.
- Cookie authentication uses a double-submit CSRF token; bearer-token requests
  are exempt by design.
- Outbound fetches (scraping, covers, page pictures, image proxy) go through the
  SSRF-safe client: every redirect hop is validated and the connection is pinned
  to a validated address. Downloads are size-capped and decoded with a
  decompression-bomb guard.
- The signed image proxy rejects unsigned or tampered requests; stored page
  files are only served for names the service itself wrote (no path traversal).
- Route audit of all 790 registered routes (each API route is mounted three
  times for legacy aliases): the only write endpoints without an auth dependency
  are `login-password`, `logout`, `refresh`, `request-magic-link` and
  `magic/request`, which must be public. Every admin read endpoint requires auth.
- The new reader write endpoints (rate, like, report, bookmark import) are
  rate-limited. Ad HTML is sanitized server-side; it is the only raw HTML the
  UI renders.
- No credentials are committed (pattern scan; only key-prefix detectors matched).

## Findings

1. **Public `source_url`.** List, detail and search responses include each
   series' `source_url` (and `mangaupdates_url`, `scrape_layout`) for every
   visitor; the UI never uses them. This reveals where content is scraped from.
   Return them to admins only.
2. **Public picture files.** Compressed pages and covers are public,
   content-addressed static files (needed for CDN caching). Anyone can
   hotlink them. Add nginx hotlink protection (`valid_referers`) and
   `limit_req`/`limit_conn` on `/api/v1/manga/pages/` and `/covers/`, or put a CDN
   in front.
3. **Compression shares the scraping queue.** Picture compression is CPU-heavy
   and long-running and runs on the `scrape` queue, so a large import can delay
   new-chapter checks. Give it its own queue and worker service.
4. **Storage growth is unbounded.** Files are deleted with their series/page,
   but there is no quota or usage report. Add a size metric (`chapters.pages_bytes`
   already stores it) and alert on the storage volume.
5. **Google OAuth client secret** was committed in the old `Manga-Website`
   repository's `.env.example`. It was left out of this repository; rotate it.
6. **`ALLOW_PLAINTEXT_SECRETS`** is set for local development. Make sure it is
   not set in production.
7. **Admin accounts** sign in by magic link/Google only. Consider a second factor
   or re-authentication for the main administrator.
8. **Hosting copies of third-party pictures** raises takedown exposure. The
   `may_host` rights gate and takedown fields exist; add a public contact and a
   documented takedown procedure.

## Fixed during this work

- Workers held a database transaction open across slow network calls while
  Postgres kills transactions idle for more than 10 s: chapters taking longer to
  fetch failed. Worker connections now get a longer allowance
  (`CELERY_IDLE_IN_TXN_TIMEOUT_MS`), are reset in forked children, and the
  chapter and picture tasks end their transaction before downloading.
- Scraper cache invalidation used the Celery broker's Redis database instead of
  the app's, so newly scraped series stayed hidden from cached list queries.
- Website approval is not bypassed by imports: a bare series URL from an
  unapproved site is rejected; supplying the site's base URL approves it.
