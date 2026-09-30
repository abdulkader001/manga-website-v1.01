# Runbook

Four jobs that come up over the life of the site. Each one says what to check
first, the steps, and how to know it worked. Commands assume the repository
root; adjust for your compose project or systemd paths.

## 1. A source site changes its domain

Sites move (`example.com` becomes `example.net`) and usually keep the same
layout. Nothing needs re-importing: the series' chapters are re-mapped onto the
new address.

Signs: the daily source check (`GET /api/v1/admin/sources/health`, and an admin
notification) reports the site unreachable or 0 chapters, or new chapters stop
appearing for every series from that site.

1. Open the new address in a browser and check it is the same site, with the
   same series.
2. Admin, Series: for each affected series, edit its schedule and change
   **Source URL** to the new address. Saving queues a job that re-maps the
   existing chapters onto the new domain (it does not re-download everything).
3. Run **Test & Live Preview** on one series first. It must show the title,
   the chapter count and page images. The pipeline tries the parser of the old
   domain first, then every other known parser, then auto-detection, then the
   Scraper AI, so a moved site normally matches without any work.
4. If the preview finds nothing, the layout changed too: follow "Adding a new
   source site" below, step 3.
5. Check: the next scheduled scrape adds new chapters, and
   `GET /api/v1/admin/sources/health` lists the new host as healthy.

If the old domain hosted pictures you already saved, they are unaffected:
pictures are compressed and served from this site, not from the source.

## 2. Restore from backup

Use this after data loss or a bad deploy. The full procedure, scripts and
timings are in
[backend_fastapi/deployment/backups.md](../backend_fastapi/deployment/backups.md)
(section "Restore drill"). The short version:

1. Stop the API and the workers so nothing writes while you restore
   (Docker: `docker compose stop backend` plus every `celery_*` service listed by
   `docker compose config --services`; systemd: `systemctl stop manga-api
   manga-worker manga-worker-compress manga-beat`).
2. Database: `backend_fastapi/deployment/restore_postgres.sh <dump>`. It asks
   twice before replacing anything. Pass the `.gpg` file directly when the
   backup is encrypted (the passphrase comes from `/etc/manga/backup.env`).
3. Pictures: `STORAGE_RESTORE_FORCE=1 backend_fastapi/deployment/restore_storage.sh <archive> /app/storage`
   (only if the pictures volume was lost).
4. Redis is a cache and queue: restoring it is optional
   (`restore_redis.sh`). Pending jobs are simply re-created by the schedule.
5. Start the services and run migrations
   (`backend_fastapi/deployment/migrate.sh`), then check `/api/v1/health`.
6. If the backup pre-dates a key rotation, put the keys that were current at
   backup time into `EMAIL_ENCRYPTION_KEY` / `INTEGRATIONS_SECRET_PREVIOUS`
   (see section 3) and re-run the rotation script.

Check: log in, open a series and a chapter (pictures load), and the admin
Storage report (`GET /api/v1/admin/storage`) shows the expected size.

Rehearse this every quarter on a spare machine, not in production. The weekly
verification timers only prove the dumps restore; they do not prove you know
the steps.

## 3. Rotate encryption keys

Step by step in [key-rotation.md](key-rotation.md): add the new key in front of
the old one, redeploy, run
`python -m backend_fastapi.scripts.rotate_encryption_key`, then drop the old
key. Pin `EMAIL_HASH_SECRET` first or logins stop matching.

## 4. Add a new source site

1. Admin, Series, **Import & Scrape Manga**. Enter the site's base URL and one
   series URL from it, then **Test & Live Preview**.
2. Read the preview: title, author, chapter count, a cover, and page images for
   two sample chapters. Nothing is saved until you press **Start Auto-Scrape**.
3. If the preview finds nothing, the site is not covered by a built-in parser
   (`backend_fastapi/app/scrapers/presets.py` lists them, including the Madara,
   MangaStream and Manganato families that cover most WordPress sites). Open
   **Custom Parser**, and let the Scraper AI write one for the domain (needs a
   Scraper AI key under the same panel). It is saved as a candidate: review the
   test results it shows, then approve and activate it. Each parser version can
   be rolled back.
4. Sites that scramble or encrypt their images (see "Not scrapable" in
   [backend_fastapi/README.md](../backend_fastapi/README.md)) cannot be
   imported; the import says so instead of saving an empty series.
5. After the first import, open the series page in the reader and check the
   page order and picture quality by eye, and check the site's rights: only
   import what you are allowed to host.
6. Check: the site appears in `GET /api/v1/admin/sources/health` after the next
   daily check. If it reports 0 chapters later, the layout changed: repeat step
   3 (the health check already saves a candidate parser for you to review).

To make a parser permanent in the code (so a fresh install has it), add it to
`SITE_PRESETS` in `presets.py` with a test.
