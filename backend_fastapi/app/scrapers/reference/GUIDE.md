# Adding or fixing a site parser: the recipe

This recipe is written so that any assistant, including a small AI model,
can add a site by following it step by step. Everything it needs is in this
repository. Do the steps in order and don't skip the tests.

## What you have

| Piece | Where | What it gives you |
| --- | --- | --- |
| Reference sites | `reference/sites.py` (`SITES`) | For each site the owner chose: series and chapter address patterns, how pictures are delivered, obstacles, and whether it can be read at all |
| Saved homepages | `reference/pages/*.html.gz` (`load_page(name)`) | The real markup of those sites, saved by the owner on 2026-10-03 |
| Built-in parsers | `presets.py` (`SITE_PRESETS`, `FAMILIES`) | Working definitions to copy from: Madara, MangaStream, MangaBox, SinMH, qTcms, manhuagui, AMP, JSON APIs |
| Every key the engine understands | `ai_playbook.py` (`PLAYBOOK`) | The full list of parser keys, the obstacles and the key that handles each, and the hard stops |
| Page facts | `ai_playbook.site_signals(html, url)` | Which family a page looks like, lazy-load attributes, pictures hidden in scripts, AJAX lists, bot checks |
| Script decoders | `script_images.py`, `packed_scripts.py` | SinMH `chapterImages`, qTcms base64, packed `eval`, LZString, image arrays in any script |
| Series discovery | `services/parser_generation_service._find_series_links` | Finds series pages on a homepage or a list page |

## The recipe

1. **Is the site in `SITES`?** Read its entry first. If `status` is
   `unsupported`, stop: the reason is a deliberate access control
   (scrambled pictures, CAPTCHA, login or payment). Never work around it.
2. **Get one series page and two chapter pages.** Save them from a browser
   (Ctrl+S, "Webpage, HTML only"). The build machine cannot open outside
   sites, so tests run on saved pages.
3. **Run `site_signals` on each saved page.** It names the family and the
   obstacles. Start from that family's definition in `presets.py`.
4. **Series page:** find one element per chapter. Write `chapter_list` so it
   matches every chapter and nothing else (no "first chapter" buttons, no
   "related series"). Check the address pattern in `SITES` matches the
   links you get.
5. **Chapter page:** if `site_signals` says the script decoders found
   pictures, use `"image_source": {"decoder": "auto_script"}` and stop.
   Otherwise point `page_images` at the reader container only (not the
   page: sidebars and headers carry thumbnails), and set `image_attr` when
   the real address is in `data-src` / `data-original`.
6. **Obstacles:** for each one in the playbook's "WHAT STOPS SCRAPERS" list
   that applies, add the key it names (`image_referer`, `chapter_ajax`,
   `page_url_template`, `encoding`...).
7. **Register it** in `presets.py` with `_register([...hosts], {...})`. A
   site that changes its domain number gets a `DOMAIN_PATTERNS` entry.
8. **Write the test** next to `tests/test_reference_sites.py`: load the
   saved pages, run the scraper's `_collect_chapters` and
   `_extract_page_images` on them with the network patched out, and assert
   the chapter count, the first chapter address and the first two picture
   addresses.
9. **Add or update the site's entry in `SITES`** with what you saw
   (`seen`) and what you took from elsewhere (`known`).
10. **Run the repository checks** (see `CLAUDE.md`) and record the change
    in `AUDIT_LOG.md`.

## Rules that keep parsers working

- Selectors: stable ids and meaningful class names only. No
  `:nth-child`, no paths from `html`/`body`, no generated class names
  (`css-1x2y3z`, `sc-abc123`).
- Pictures: the full-size address, never a thumbnail. Prefer the largest
  `srcset` entry. Don't re-encode or resize in the parser.
- Requests: only `Accept`, `Accept-Language` and a same-site `Referer`.
  Never cookies, tokens or keys.
- Pace: the engine already waits between requests and honours
  `Retry-After`. Never lower the waits to read faster: that is what gets
  the server blocked.
- Hard stops: CAPTCHA or "checking your browser" pages, login or payment
  walls, scrambled or encrypted pictures, signed API tokens. Report the
  site as unsupported.

## How the public scrapers do it (the ideas this engine borrows)

- **gallery-dl:** one extractor per site, address patterns first, then the
  smallest request that returns the data (often a JSON API rather than the
  HTML page). Retries with backoff, honours `Retry-After`.
- **Mihon / Tachiyomi extensions:** shared "multisrc" themes (Madara,
  MangaThemesia, MangaBox...) with per-site overrides; a site on a known
  theme is a few lines. A stable User-Agent per site, a `Referer` for
  pictures, and rate limiting per host.
- **HakuNeko:** connectors grouped by CMS template; pages decoded from the
  reader's script when the `<img>` tags are built by JavaScript.
- **Scrapy:** AutoThrottle (slow down when responses get slower), retry on
  429/5xx, one polite crawl per host.

This engine follows the same pattern: families in `presets.py`, per-site
overrides, script decoders, a stable User-Agent per site, `Retry-After`,
picture retries, and the Scraper AI for sites with no parser.
