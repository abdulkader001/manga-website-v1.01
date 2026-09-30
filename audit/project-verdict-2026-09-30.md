# Project verdict — 2026-09-30

Scope: the v1.01 React UI wired to the FastAPI backend, the scraping pipeline,
chapter-picture compression and series layouts (pull requests #4 and #5).
Everything below was checked in the code or by running it; anything that could
not be verified is listed as such.

## What was done

- The UI's in-browser mock backend was replaced by the real backend (FastAPI,
  Postgres, Redis, Celery). All 173 API calls the UI makes map to a backend route.
- Backend added for every screen: sign-in (password, magic link, Google,
  Microsoft), profile completion, ratings, chapter likes, broken-chapter
  reports, announcements, admin schedules and settings, maintenance mode,
  sitemap and RSS.
- Scraping was rebuilt on real data: MangaUpdates metadata, per-site parsers,
  a Custom Parser panel, moved-domain handling, chapter grouping, book-format
  page splitting, ordered pagination.
- Chapter pictures are downloaded, compressed to WebP and served from this site.
- A worker database bug was fixed (transactions idle >10 s were killed during
  slow downloads).

## Verified

- Backend tests: 833 passed on Postgres 16 in a clean lockfile environment.
- CI (backend, frontend, dependency audit) green on both pull requests.
- Live run with a fixture site: preview, parser generation, import, pagination,
  grouping, spread splitting, compression and serving all worked.
- Route check over all 790 registered routes: the only unauthenticated write
  endpoints are login, logout, refresh and the two magic-link requests.
- No secrets committed.

## Not verified

- The real source sites (parser selectors) and MangaUpdates id decoding.
- A real OCR / translation run (needs providers configured in the admin).
- Compression ratios and gutter detection on real scans (only synthetic images).

## Mismatches and unconnected paths

| Finding | Where | Severity |
| --- | --- | --- |
| Icons load from external CDNs; the production Content-Security-Policy only allows the site's own styles/fonts, so icons would not show. | `index.html` vs `deployment/nginx/site.conf` | High (visible) |
| "Western Comic" is offered on the import form but the backend only knows manga/manhwa/manhua and saves it as manga (right-to-left default). | `SeriesManagement.jsx`, `scraper_workflow_service.py` | Medium |
| Translation overlay needs an OCR/translation provider configured; none is set up. | Admin → API management | Medium |
| Re-compress and change-layout endpoints exist only as API calls (no buttons). Group size is fixed at import. | `site_admin.py` | Low |
| Whole site requires login while the sitemap/RSS advertise pages crawlers can't reach; ads only show to logged-in users. | `src/app.js`, `seo.py` | Design decision |
| Frontend has no automated tests (CI type-checks and builds only). | `.github/workflows/ci.yml` | Low |

## Recommendations, in order

1. Bundle the icon fonts and CSS into the build (removes the CDN dependency and fixes the CSP problem).
2. Hide `source_url`, `mangaupdates_url` and `scrape_layout` from non-admin API responses.
3. Run Test & Live Preview on one series per site; fix parsers from what it shows.
4. Configure an OCR and translation provider and test one real chapter.
5. Add hotlink protection and rate limits for the public picture files in nginx.
6. Run picture compression on its own worker queue so it cannot starve scraping.
7. Monitor storage; back up Postgres and the pictures volume; move pictures to S3/CDN as the library grows.
8. Rotate the Google OAuth client secret that was committed in the old `Manga-Website` repository.
9. Consider a second factor for the main admin account.
10. Reconsider login-only browsing (SEO and ad revenue).

See also: `frontend.md` (this folder) and `../backend_fastapi/audit/security-review-2026-09-30.md`.
