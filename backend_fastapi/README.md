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
celery -A backend_fastapi.app.core.celery_app:celery_app worker -Q default,celery,scrape,compress,ocr,translation,email,maintenance,notifications -l info
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

## Pictures, page order and layouts

Every chapter's pictures are downloaded when the chapter is scraped and served
from this site (nginx serves the files straight from the storage volume, cached
for a year). A JPEG/PNG/WebP that needs no change is stored exactly as the
source sent it (`PAGE_KEEP_ORIGINALS`, default on); everything else is
re-encoded to **WebP**. Width is capped (`PAGE_MAX_WIDTH`, default 2000px),
quality never drops below a floor that keeps text edges clean for OCR
and for erasing the original lettering, flat art is stored losslessly, and very
tall strips are cut into slices of at most 3000px on blank rows. The stored
file is the one picture the reader shows *and* OCR reads, so detected text
coordinates line up exactly. Pages that fail to download keep their source URL.
Set `MIRROR_PAGE_IMAGES=false` to turn this off. Existing series can be
converted with `POST /admin/series/{id}/mirror-images` (or
`/admin/maintenance/mirror-all-images`).

**Page order.** Pages are read in the order the source gives them; a chapter
spread over several HTML pages is followed through a "next" link, a page
dropdown / numbered links (auto-detected) or numbered URLs, and a page that
cannot be fetched fails the chapter instead of dropping it. If every image is
named by its own number and the source lists them out of order, the numbers
win. Everything ends up as one vertical, top-to-bottom flow.

**Layout of a source** (set on the import form under *Page Layout*; the
preview scans real chapters and pre-fills a suggestion):

| Source format | What it does |
| --- | --- |
| Detect automatically | wide two-page scans are split, everything else is kept |
| Vertical strips / normal pages | nothing is split or merged |
| Book format (two pages per picture) | every picture is cut at its gutter into two pages |
| One page per chapter | consecutive source chapters are merged (10 by default, or 5 / 20 / any size up to 50) into one long chapter |

*Reading order* decides which half of a two-page scan comes first (right-to-left
for manga, left-to-right for manhwa/manhua by default). Grouped chapters are
published in full groups as they complete; the last partial group appears once
enough chapters exist or the series is marked completed. Spread splitting and
reading order can be changed later with `POST /admin/series/{id}/layout`
(re-compresses from the kept source URLs); the grouping size is fixed at import.

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

### What the engine can read

Besides plain `<img>`/`<a>` tags (lazy-load attributes, `srcset`, `amp-img`
included), a parser can use:

| Obstacle on the site | Handled by |
| --- | --- |
| Page images kept in a script (SinMH `chapterImages`, qTcms base64, packed `eval`, any image array) | `image_source: {"decoder": "sinmh" / "qtcms" / "script_array" / "auto_script" / "manhuagui"}`; also tried automatically when a reader page has no page `<img>` |
| Page images from a JSON API keyed by ids in the chapter URL | `image_api` (same-site only) |
| Chapter list loaded by AJAX after the page opens (WordPress Madara) | `chapter_ajax: {"kind": "madara"}` (part of the Madara family) or a generic same-site `{url, method, data}` |
| Chapter list hidden LZString-compressed in a form field (manhuagui age gate) | `hidden_chapter_list` |
| `href="javascript:…"` with the real address in `data-href` / `data-hreflink` | automatic |
| Chapter links through a redirector | automatic; numbered pages use where the link landed |
| One chapter split over several URLs | `next_page`, `page_list`, `page_url_template` (`{url}`, `{stem}`, `{ext}`, `{base}`, `{n}`); a page that redirects away ends the chapter |
| Hotlink protection | `image_referer` (tested automatically) |
| Cloudflare / CAPTCHA check page | detected and reported as such (not bypassed) |

### Built-in parsers (per requested site)

| Site | How it is read |
| --- | --- |
| baozimh / twmanga / webmota | HTML list; split chapters via `{stem}_{n}{ext}` |
| comic.naver.com | JSON episode API (paid episodes skipped); `naver.com` itself is answered with "use comic.naver.com" |
| manhuagui (www / m / tw) | packed + LZString image list; hidden age-gate chapter list |
| mkzhan | HTML list (`data-hreflink` links); page images from its chapter JSON API |
| wujinmh, yueman1, 51manga, zymk, mh03, mh160mh | HTML list; page images from `<img>` or, if none, from the script decoders |
| raw.senmanga | HTML list; one page per URL via `{url}/{n}` |
| rawkuma (any TLD) | MangaStream family (`ts_reader.run` JSON) |
| wfwf<number>.com | HTML list + lazy images; any `wfwf<n>` domain |
| mangaz | HTML selectors (may be a protected viewer; reported if no images) |
| mangaraw4u and other WordPress manga sites | recognised by family (Madara / MangaStream), no preset needed |

A list page (`m.manhuagui.com/list/lianzai/`, `m.yueman1.cc/.../m_waplistindex.html`)
pasted into **Custom Parser** is handled: the first series it links to is used.

### Not scrapable (reported, never faked)

`tonarinoyj`, `comic-days`, `sunday-webry`, `pocket.shonenmagazine`,
`shonenjumpplus` (scrambled GigaViewer images), `comic-walker` (encrypted
viewer API) and `kuaikanmanhua` (signed app API). The scraper does not try to
get past bot checks, logins, paywalls or image scrambling.

### Scraper AI

The AI receives `app/scrapers/ai_playbook.py`: every key the engine runs, the
known site families, each common obstacle with the key that handles it, the
hard stops (bot check, login/paywall, scrambled images, signed APIs) where it
must answer `{"unsupported": "…"}`, worked examples, plus measured *site
signals* for the page (family, lazy attributes, script-hidden images, AJAX
holder, bot check). Every answer passes `app/scrapers/definition_guard.py`
before use: unknown keys dropped, selectors must compile and avoid
`:nth-child`, fetch URLs must stay on the same site, only `Accept`,
`Accept-Language` and same-site `Referer` headers. What it removes is sent
back to the AI on the next attempt; extracted results are checked too
(chapter links mostly on-site and distinct, page images not logos/icons).
Failures carry `next_steps` (shown under the error in Custom Parser).

## Known limits

* The selectors for the built-in sites come from public knowledge of their
  markup and were **not** checked against the live sites (no outbound access
  from the build environment). They are validated on every scrape, and the
  fallbacks above take over when a site differs.
* The MangaUpdates series-id decoding (base-36 path ids) was implemented from
  the API documentation and is tested against synthetic payloads only.
* The 64 tests that fail in some sandboxes (cookie handling of the test client)
  fail identically on the original backend.
