# Scraper Engine Specification

The Scraper Engine (`src/scraper/scraper-engine.ts` & `src/scraper/HttpFetcher.ts`) is a unified, 7-component declarative ingestion engine.

---

## The 7 Core Engine Components

1. **HttpFetcher (`src/scraper/HttpFetcher.ts`)**:
   - Manages per-source headers (`User-Agent`, `Referer`, `Accept-Language`).
   - Charset detection & decoding supporting `utf-8`, `euc-kr`, and `gbk`/`gb18030` using `iconv-lite`.
   - Domain cookie jars for session continuity.
   - SSRF protection check (`isPrivateIp`) blocking loopback and private IP address ranges.

2. **SelectorEngine**:
   - Cheerio HTML parser.
   - Fallback image attribute chain (`[data-src -> data-original -> src -> data-url -> srcset]`).
   - Embedded JSON state extractor reading `window.__NEXT_DATA__`, `__NUXT__`, `__INITIAL_STATE__`, or viewer config scripts with dot-notation `jsonPath` queries.

3. **ChapterNormalizer**:
   - Language-aware regex normalization for CN (`第...話/话/回`), KR (`...화`), JP (`第...話/话`), and Generic (`#...`).
   - Suffix mapping (`prologue` -> 0.01, `extra`/`side story` -> 0.5x, `epilogue` -> 999.5).

4. **RateLimiter**:
   - Token bucket algorithm enforcing 1 req/sec/domain default with exponential backoff on 429/5xx.

5. **WatermarkStore**:
   - SHA-256 hash calculation of chapter-list HTML. Unchanged hash skips fetching.

6. **ImagePipeline**:
   - Image fetcher with source `Referer`, magic-byte checking, and WebP conversion via `sharp`.

7. **HealthProbe**:
   - GET probe tests for per-source health status logging.

---

## Registered Source Specs (16 Publishers)

- **Chinese (CN)**: `baozimh`, `wujinmh`, `yueman1`, `kuaikanmanhua`, `mkzhan`
- **Japanese (JP)**: `tonarinoyj`, `senmanga`, `comicdays`, `mangaz`, `comicwalker`, `sundaywebry`, `pocketshonen`, `shonenjumpplus`
- **Korean (KR)**: `naver`, `rawkuma`, `wfwf505`
