# Manga Reader API Surface Reference

All endpoints are mounted on `/api/v1` and `/api` for backward compatibility.

---

## 1. Catalog & Series Endpoints

- `GET /api/v1/manga` — Retrieves all catalog manga series with filter parameters (`genre`, `status`, `query`).
- `GET /api/v1/manga/:id` — Retrieves single series detailed metadata and chapter list.
- `GET /api/v1/chapters/:id` — Retrieves chapter details, page image URLs, and pre-computed translations.
- `POST /api/v1/manga/ingest` — Ingests a new series using 2 source URLs (primary + backup fallback) and MangaUpdates metadata lookup.

---

## 2. AI Speech Bubble Translation Pipeline

- `POST /api/v1/translate/pipeline`
  - **Payload**: `{ chapter_id, page_index, target_language }`
  - **Response**: Extracted speech bubble bounding box coordinates and translations powered by `gemini-2.5-flash`.
- `POST /api/v1/chapters/:id/translate-all` — Triggers background batch translation for all pages in a chapter.

---

## 3. Scraper & System Health Diagnostics

- `GET /api/v1/system/stats` — Returns live server memory usage (RSS/Heap), uptime, series counts, chapter counts, and daemon status.
- `POST /api/v1/chapters/:id/verify-health` — Scans page image availability, returns health status (`healthy`/`degraded`), and triggers auto-rescrape if pages are missing.
- `POST /api/v1/admin/scraper/test-fixtures` — Executes regression tests against sanitized HTML fixture snapshots.

---

## 4. Admin Database Backup & Maintenance

- `GET /api/v1/admin/database/export` — Downloads full SQLite database JSON dump file.
- `POST /api/v1/admin/database/import` — Restores full database state from uploaded JSON dump.
- `POST /api/v1/admin/scrape/trigger-all` — Triggers immediate manual rescrape across all series.

---

## 5. Feeds & SEO

- `GET /sitemap.xml` — Dynamic XML sitemap for search engine crawlers.
- `GET /rss.xml` / `GET /feed.xml` — RSS 2.0 publication feed for feed readers.
