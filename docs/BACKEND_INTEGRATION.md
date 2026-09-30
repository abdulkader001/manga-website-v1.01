# Backend integration (v1.01 UI + FastAPI backend)

The React UI in `src/` is unchanged in look and behaviour. All data, auth,
scraping and security now live in `backend_fastapi/` (FastAPI, Postgres, Redis,
Celery). `server.ts` is only a thin gateway that serves the UI and forwards
`/api/*`, `/sitemap.xml`, `/rss.xml` and `/feed.xml` to the backend.

## Run it (development)

```bash
cp .env.example .env            # fill in the secrets (see the comments in the file)
docker compose up -d db redis
alembic upgrade head            # creates every table, including the new ones
npm run backend                 # API on :8000
celery -A backend_fastapi.app.core.celery_app:celery_app worker -Q scrape,celery -l info
npm install && npm run dev      # UI + gateway on :3000
```

`docker compose` ships secure defaults: `FORCE_HTTPS_REDIRECTS=true` redirects
plain-HTTP requests, so the stack expects TLS in front of nginx (the backend
refuses to start in production with it off). To try the compose stack over
plain `http://localhost:8080`, set `FORCE_HTTPS_REDIRECTS=false` and
`ENVIRONMENT=development` in `.env` first.

Production: `docker compose up` (web image is built with Vite, nginx proxies
`/api/`, the SEO feeds and serves `dist/`).

## What was connected

| UI feature | Backend |
| --- | --- |
| Email magic-link, Google and Microsoft sign-in, password login, profile completion, username check | `api/routers/account.py`, `auth.py` |
| Browse / search / sort (latest, new, views today/week/month, popular, rating, A-Z, chapters, random), series detail, chapters, reader | `api/routers/manga.py`, `services/catalogue_service.py` |
| Ratings, chapter likes, "report broken chapter" (+ alert banner), announcements, bookmark import | `api/routers/reader.py` |
| Admin: series schedule, batch schedule, reports, broadcasts, ad networks, site settings, maintenance mode, API registry, audit report, health, cache/purge tools | `api/routers/site_admin.py` |
| Series Management: preview, import, Scraper AI settings, **Custom Parser** panel | `api/routers/scraper_admin.py`, `admin.py`, `scrapers/source_pipeline.py` |
| Page translation overlay | existing `/processing/chapter/{id}/page/{n}` (real OCR + translation) |

## How a series is imported

1. Admin enters a **MangaUpdates link** and the **source series URL**.
2. The worker fetches metadata from MangaUpdates (title, description, genres,
   authors, type, status, cover) and downloads/re-encodes the cover.
3. It finds a parser for the source site (see below), lists every chapter and
   scrapes each chapter's page images. Chapters and counts come from the source
   site; metadata never gets overwritten by the source for MangaUpdates-managed
   series.
4. New chapters are picked up on the series' schedule.

Approving a new website (SRS 1G.6.0) happens when the admin supplies the site's
base URL with the import, or by using the Custom Parser panel.

## Parsers and domain changes

For every source page the pipeline tries, in order:

1. the parser stored/approved for that domain (including parent domains and
   domain patterns such as `wfwf<number>.com`);
2. every known parser (built-in presets plus every active parser of *any*
   domain), so a site that moved to a new domain matches its old parser;
3. structural auto-detection (biggest group of chapter-like links, biggest
   group of page images) - needs no site knowledge;
4. the Scraper AI (up to 3 attempts, each fed the test results of the last).

A candidate is accepted only if it extracts a title, chapters, and at least one
image on two sample chapters; hotlink protection is detected and handled with
a signed image proxy. Changing a series' source URL queues a job that re-maps
its existing chapters onto the new domain instead of re-importing.

### Built-in parsers

`baozimh`/`twmanga`/`webmota`, `comic.naver.com`, `wujinmh`, `yueman1`,
`mkzhan`, `manhuagui` (packed image list decoded server-side), `51manga`,
`zymk`, `mh03`, `mh160mh`, `senmanga`, `mangaz`, `rawkuma`, `wfwf`, plus the
Madara, MangaStream and Manganato CMS families.

### Not scrapable (reported, never faked)

`tonarinoyj`, `comic-days`, `sunday-webry`, `pocket.shonenmagazine`,
`shonenjumpplus` (scrambled GigaViewer images), `comic-walker` (encrypted
viewer API) and `kuaikanmanhua` (signed app API).

## Known limits

* The selectors for the built-in sites come from public knowledge of their
  markup and were **not** checked against the live sites (no outbound access
  from the build environment). They are validated on every scrape, and the
  fallbacks above take over when a site differs.
* The MangaUpdates series-id decoding (base-36 path ids) was implemented from
  the API documentation and is tested against synthetic payloads only.
* The 64 tests that fail in some sandboxes (cookie handling of the test client)
  fail identically on the original backend.
