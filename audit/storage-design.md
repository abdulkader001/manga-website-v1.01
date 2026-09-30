# Design: moving pictures off the local disk (roadmap item 23)

Status: design only. Nothing here is built. Build it when the trigger below
fires, not before.

## Today

- The backend downloads each chapter's pictures, compresses them to WebP and
  writes them to a local volume (`/app/storage/pages/<manga>/<chapter>/NNNN-<sha1>.webp`,
  covers in `/app/storage/covers/`). Names are content-addressed, so a file
  never changes once written.
- nginx serves those folders directly with a one-year immutable cache, hotlink
  protection and per-IP rate limits (`deployment/nginx/site.conf`). The API
  never handles image bytes on the read path.
- Chapters store the public URL (`/api/v1/manga/pages/...`). The volume is
  backed up nightly (`backup_storage.sh`) and restore-tested weekly.
- Code that touches the files directly: `page_image_service` (write, delete,
  `path_from_url`), `processing.py` (OCR reads the stored file), and
  `storage_report_service` (`disk_usage`).

## Trigger: when to build

Item 12 already measures this. Start when **either** holds:

1. `GET /admin/storage` shows the pictures volume above 70% and the growth
   over the last three months would fill it within six months; or
2. readers are far from the server and picture load time (not the API) is the
   complaint.

Until then the single disk is the cheaper, simpler and better-tested option.
Rough sizing: `total bytes = chapters x pages x average page size`. Read the
average from the storage report's `pages_bytes`, do not guess.

## Options

| | Change | Fixes | Cost of change |
| --- | --- | --- | --- |
| A. CDN in front of today's nginx | none in the app; point a pull CDN at the site as origin | speed far from the server, bandwidth on the server | very small: DNS/CDN settings, cache rules |
| B. Object storage (S3-compatible) as the store, CDN in front | new storage layer in the backend | disk size, backups, several servers | medium: see below |
| C. Bigger disk / network volume | none | disk size for a while | small, but every server still needs the volume |

## Recommendation

Do **A first** whenever speed is the problem: the files are immutable and
content-addressed, which is exactly what a CDN caches best, and nothing in the
app changes. Keep hotlink protection working by making the CDN forward or
enforce the `Referer` rule (or sign URLs at the CDN).

Do **B** only when the disk itself is the limit (trigger 1) or a second server
needs the same pictures. Keep the local disk as the default; make object
storage a setting so small installs stay simple.

## How B would work

1. **Storage interface.** Add `PageStore` with `put(key, bytes) -> url`,
   `delete(key)`, `open(key)` and `usage()`. Two implementations: `LocalStore`
   (today's behaviour) and `S3Store` (any S3-compatible service; `boto3`, or
   plain signed HTTP). Selected by `STORAGE_BACKEND=local|s3`.
2. **Write path.** `page_image_service` stops building filesystem paths and calls
   `put`. Keys are the same relative names as today, so nothing about naming
   changes.
3. **Read path.** Public URLs become `PAGES_PUBLIC_BASE/<key>` (the CDN host).
   Chapters already store full public URLs, so old and new pictures can coexist;
   a one-off job copies old files across and rewrites the stored URL per chapter
   (resumable, chapter by chapter, and only after the copy is verified by size
   and checksum).
4. **OCR.** `processing.py` reads the stored file; with S3 it fetches through
   `open`, with a small local cache. Text coordinates keep matching because it is
   still the same canonical file.
5. **Hotlink and rate limits** move from nginx to the CDN (referer rule, or
   signed, short-lived URLs). This is the one real loss of control; check the
   provider supports it before choosing.
6. **Storage report and alerts.** `usage()` replaces `disk_usage`; the alert
   threshold becomes a bucket-size budget.
7. **Backups.** Turn on bucket versioning and a second-region or second-provider
   copy; the pictures backup script stays for `LocalStore` only. Rehearse the
   restore the same way as today's.

## Risks and how to check them

- **Egress and request cost** can exceed disk cost. Estimate from real traffic
  before choosing a provider; a CDN in front is what keeps this small.
- **Partial migration.** Copy, verify, then switch the URL, never the other
  way round; keep the local files until a week after the last switch.
- **Deleting a series** must delete its objects (`delete_page_file` today):
  cover this in the interface tests.
- **Provider lock-in:** stay on the S3 API subset (put, get, delete, list) so a
  change of provider is a settings change.

## Not decided

Provider and region, whether to sign URLs or use a referer rule, and the
retention for deleted pictures. These need the owner's budget and traffic
numbers, so they are decided when the trigger fires.
