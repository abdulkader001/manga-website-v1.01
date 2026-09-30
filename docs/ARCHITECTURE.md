# Manga Reader Platform Architecture

Welcome to the **Manga Reader** platform documentation. This repository powers a full-stack, enterprise-grade web application for reading manga, manhwa, and manhua with automated content ingestion, multi-source scraping, AI OCR translation, and offline PWA capabilities.

---

## Technical Stack Overview

- **Frontend**: React 18, Vite, React Router 6, Tailwind CSS, Lucide Icons, DOMPurify.
- **Backend API**: Node.js Express server (`server.ts`) providing full RESTful JSON endpoints.
- **Database Engine**: File-backed SQLite (`manga_reader.sqlite`) via `sql.js`, managing series, chapters, domain mappings, user bookmarks, reading history, page translations, and background job logs.
- **AI Engine**: `@google/genai` TypeScript SDK (`gemini-2.5-flash`) for speech bubble detection and multi-language manga page translation.
- **Scraper Engine**: Unified 7-component declarative engine (`HttpFetcher`, `SelectorEngine`, `ChapterNormalizer`, `RateLimiter`, `WatermarkStore`, `ImagePipeline`, `HealthProbe`).
- **PWA & Offline Mode**: Service Worker (`sw.js`) and Web App Manifest (`manifest.json`) for chapter page caching and mobile installation.
- **SEO & RSS**: Dynamic meta tags, OpenGraph cards, Schema.org JSON-LD structured data, dynamic `/sitemap.xml`, and standard `/rss.xml` publication feeds.

---

## Directory Structure

```
.
├── docs/                      # Platform technical documentation
│   ├── ARCHITECTURE.md        # Technical architecture overview
│   ├── API_SURFACE.md         # Express REST API endpoint reference
│   ├── SCRAPER_ENGINE.md      # Scraper engine & 16-source specification
│   ├── OCR_TRANSLATION.md     # Gemini OCR speech bubble translation guide
│   └── SOURCE_SURVEY.md       # Pre-survey intel & domain parser cards
├── src/
│   ├── components/            # Reusable UI elements (Navbar, Reader, OCR Overlay)
│   ├── db/                    # SQLite repository database layer (`repository.ts`)
│   ├── pages/                 # Page view routing (Home, MangaDetail, Reader, Admin)
│   ├── scraper/               # Ingestion & Scraper Engine
│   │   ├── HttpFetcher.ts     # Request fetcher with charset & SSRF checks
│   │   ├── scraper-engine.ts  # 7 core component classes
│   │   ├── sharedEngine.ts    # Unified extraction engine
│   │   ├── sourceSpecs.ts     # Declarative parser specs for 16 sites
│   │   ├── daemon.ts          # 60s ticker background scraper daemon
│   │   └── mangaupdates.ts   # MangaUpdates metadata adapter
│   └── utils/                 # Sharp WebP image processing & Gemini translator
├── server.ts                  # Node.js Express server entry point & REST endpoints
└── public/                    # Static assets, WebP covers, Service Worker, Manifest
```

---

## System Workflows

### 1. Chapter Ingestion & Background Ticker
The scraper daemon (`daemon.ts`) executes every 60 seconds, querying due series from SQLite (`crawl_interval_minutes`), executing the target domain's JSON parser spec, checking watermark hashes (`SHA-256`), downloading new chapters, and re-encoding page images.

### 2. AI Speech Bubble OCR & Reader Overlay
When a reader enables AI Translation, the client invokes `/api/v1/translate/pipeline`. Gemini 2.5 Flash detects original text, calculates normalized bounding box coordinates (`[ymin, xmin, ymax, xmax]`), and returns English translations rendered as responsive speech bubble overlays over the original image.

### 3. Catalog Backup & Import
Admins can download full JSON database dumps via `/api/v1/admin/database/export` and restore catalogs across environments via `/api/v1/admin/database/import`.
