# Source Survey Intel & Pre-Survey Audit (Section 13)

This document contains pre-survey intel and classification for all 16 target publishers across CN, JP, and KR markets.

---

## 13.C FOUR EXTRACTION ARCHETYPES

### ARCHETYPE A — Static CMS
*Plain cheerio HTML parsing; images located in `[data-src/src/data-original/srcset]`.*
- **baozimh**
- **wujinmh**
- **yueman1**
- **mkzhan**
- **rawkuma** (WordPress Madara)
- **senmanga**

### ARCHETYPE B — JS-Rendered State Sites
*HTML shell + embedded JSON blob (e.g., `__NEXT_DATA__`, `__NUXT__`, or `__INITIAL_STATE__`). NO headless browser required.*
- **tonarinoyj**
- **comic-days**
- **comic-walker**
- **sunday-webry**
- **shonenjumpplus**
- **mangaz**
- **pocket.shonenmagazine**
- **kuaikanmanhua**
- **naver**

### ARCHETYPE C — Viewer-Config Image Loading
*Chapter images listed inside page-embedded JSON viewer configurations or dedicated CDN parameters.*
- **shonenjumpplus** (`viewerConfig.pages[]`)
- **naver** (`div.wt_viewer img`, `image-comic.pstatic.net`)

### ARCHETYPE D — High-Risk / Volatile
*Flagged chapters, auth/app signatures, or volatile DOM structures.*
- **kuaikanmanhua** (App API signatures)
- **wfwf505** (Volatile domain rotation)

---

## 13.D PER-SITE BUILD CARDS

### Chinese Publishers (CN)
1. **baozimh.com** (Archetype A)
   - **Series URL**: `/comic/<slug>` | **Chapter URL**: `/chapter/<slug>/<id>`
   - **Encoding**: `utf-8`
   - **Images**: `<img data-src>` on chapter pages; CDN `s*.baozimh.com`
   - **Gotcha**: Chapter list may be sectioned/grouped — flatten all sections into a unified list.

2. **wujinmh.com** (Archetype A)
   - **Series URL**: `/manhua/<id>.html` | **Chapter URL**: `/chapter/<id>.html`
   - **Encoding**: `utf-8` / `gbk`
   - **Images**: `img[data-original]`

3. **m.yueman1.cc** (Archetype A)
   - **Series URL**: `m.yueman1.cc/manhua/<id>`
   - **Encoding**: `utf-8`
   - **Images**: Mobile site lazy-loaded attributes `data-src` / `src`.

4. **kuaikanmanhua.com** (Archetype D)
   - **Series URL**: `/web/topic/<id>/`
   - **Encoding**: `utf-8`
   - **Gotcha**: Content behind signed app API. Flags login walls & sets `requires_login = true`.

5. **mkzhan.com** (Archetype A)
   - **Series URL**: `/<numeric-id>/`
   - **Encoding**: `utf-8`
   - **Images**: CDN `ac.mkzhan.com`, `srcset` attribute (extract largest variant).

### Japanese Publishers (JP)
6. **tonarinoyj.jp** (Archetype B)
   - **Episode URL**: `/episode/<id>`
   - **Encoding**: `utf-8`
   - **Images**: `cdn.tonarinoyj.jp`, embedded JSON state blob.

7. **raw.senmanga.com** (Archetype A)
   - **Series URL**: `/<slug>` | **Chapter URL**: `/<slug>/<chapter>/`
   - **Encoding**: `utf-8`
   - **Images**: `data-src` on reader page. Strict chapter number normalization.

8. **comic-days.com** (Archetype B)
   - **State Source**: `__NEXT_DATA__.props.pageProps`
   - **Encoding**: `utf-8`
   - **Images**: `cdn.comic-days.com`, URL parameters like `!w_1200` (strip for full resolution).

9. **mangaz.com** (Archetype B)
   - **Series URL**: `/title/<id>/` | **Chapter URL**: `/chapter/<id>/`
   - **Encoding**: `utf-8`

10. **comic-walker.com** (Archetype B)
    - **State Source**: `__NEXT_DATA__`
    - **Encoding**: `utf-8`
    - **Gotcha**: Multi-title episodes array paged inside Next.js state.

11. **sunday-webry.com** (Archetype B)
    - **Episode URL**: `/episode/<id>`
    - **Encoding**: `utf-8`
    - **Images**: `cdn.sunday-webry.com`, embedded state blob.

12. **pocket.shonenmagazine.com** (Archetype B/C)
    - **State Source**: `__NEXT_DATA__`
    - **Encoding**: `utf-8`
    - **Images**: Signed/short-lived CDN URLs. Download immediately after page fetch. Flags paid chapters (`is_paid`).

13. **shonenjumpplus.com** (Archetype B/C)
    - **State Source**: `__NEXT_DATA__` + `viewerConfig` JSON
    - **Encoding**: `utf-8`
    - **Images**: `cdn.shonenjumpplus.com`. Distinguishes free vs paid chapters (`is_paid`).

### Korean Publishers (KR)
14. **comic.naver.com** (Archetype B/C)
    - **Series URL**: `/webtoon/list?titleId=<id>`
    - **Chapter URL**: `/webtoon/detail?titleId=<id>&no=<n>`
    - **Encoding**: `utf-8`
    - **Images**: `div.wt_viewer img` -> `image-comic.pstatic.net`. First image is header banner (`skipFirstImage: true`).

15. **rawkuma.com** (Archetype A)
    - **Series URL**: `/manga/<slug>/` (WordPress Madara)
    - **Encoding**: `utf-8`
    - **Images**: `img[data-src]` or `img[src]` in `.main version-chap`.

16. **wfwf505.com** (Archetype D)
    - **Encoding**: `euc-kr` / `utf-8`
    - **Gotcha**: Volatile domain rotation. Parser Studio fallback case.

---

## 13.E BUILD PROTOCOL
1. **SURVEY**: Fetch live or fixture HTML, record URL patterns & state blob paths.
2. **SPEC**: Register 13.B JSON spec in `sourceSpecs.ts`.
3. **FIXTURE TEST**: Verify fixture extraction against stored HTML snapshots.
4. **LIVE TEST**: Execute Shared Engine against live endpoint with rate-limiting.
5. **VERSION**: Version spec (`parser_version = 1`).
