# Plan: from "it runs" to a production-ready website

**Status: proposed. Nothing in this plan has been done yet.** Read it, strike out
what you don't want, answer the questions in Section 2, and tell me which items to
do. I only start an item you have approved.

How to approve: write `do 1.1, 1.2` (those items), `do phase 1` (a whole phase),
or `skip 3.4`. Each approved group becomes **one pull request**, with its
`AUDIT_LOG.md` entry, tests and guide updates, and you merge it. After each one we
re-test on your computer ([`TEST_COMPUTER.md`](TEST_COMPUTER.md)) before the next.

Contents

1. [What this plan is based on (and what it is not)](#1-what-this-plan-is-based-on-and-what-it-is-not)
2. [Decisions I need from you](#2-decisions-i-need-from-you)
3. [Phase 0: your test (no code)](#3-phase-0-your-test-no-code)
4. [Phase 1: safe to put on the internet](#4-phase-1-safe-to-put-on-the-internet)
5. [Phase 2: survives real traffic](#5-phase-2-survives-real-traffic)
6. [Phase 3: the reading experience](#6-phase-3-the-reading-experience)
7. [Phase 4: search and discovery](#7-phase-4-search-and-discovery)
8. [Phase 5: found by Google, shared nicely](#8-phase-5-found-by-google-shared-nicely)
9. [Phase 6: finish or remove half-built things](#9-phase-6-finish-or-remove-half-built-things)
10. [Phase 7: quality](#10-phase-7-quality)
11. [Phase 8: running it day to day](#11-phase-8-running-it-day-to-day)
12. [Suggested order](#12-suggested-order)
13. [Corrections to what I told you earlier](#13-corrections-to-what-i-told-you-earlier)

---

## 1. What this plan is based on (and what it is not)

**Based on:**

- **Code I re-checked today** (marked ✔ below): `docker-compose.yml`,
  `make_env.py`, the search function, the reader page, `index.html`, the service
  worker, nginx configs, CI, the `AntiTamperGuard` component, the Dockerfiles.
- **The earlier audits**, which I did not redo (marked ◐): `audit/ROADMAP.md`,
  `audit/bug-test-2026-10-03.md`, `audit/full-audit-2026-10-02.md`,
  `audit/site-functions-tab-access-and-hardening-2026-10-03.md`, and
  `AUDIT_LOG.md` §5 "Open items and known limits".
- **Checks I ran this session:** `ruff` clean; backend tests all passing (about
  1,100 test functions); frontend 85 tests passing; `tsc` clean; `vite build` OK;
  `npm audit` (production dependencies): **0 vulnerabilities**; CI green on the
  latest change.

**Not based on a live test.** I have not run the whole site in a browser for this
plan, and this machine has no Docker, so the Docker build and the real server
steps were **not run by me**. You are about to test on your computer: what you
find there goes in Phase 0 and may change this plan. Also never exercised for
real: Google and Microsoft sign-in, a real SMTP account, the real source sites for
scraping, OCR and translation providers, Let's Encrypt, Cloudflare, and the site
under load.

**Out of scope for now (you asked to test first):** I am not building a RAM/CPU
monitor. Phase 2 only *measures* on your test machine and on the real server, and
then we decide the server size from numbers.

---

## 2. Decisions I need from you

These are yours to make; the plan changes with the answer.

| # | Question | My recommendation |
| --- | --- | --- |
| D1 | **The anti-tamper guard** (`src/components/AntiTamperGuard.jsx`) blocks F12, Ctrl+Shift+I/J/C, Ctrl+U, Ctrl+S and right-click for **everyone** (including you), and prints a warning that inspection "is monitored and will terminate the active session". Nothing is monitored and no session is ended: it only blocks the keys. Anyone can still open the developer tools from the browser menu, and `curl` ignores it entirely. Keep it, or remove it? | **Remove the blocking and the false warning.** It protects nothing, annoys honest readers (and you, when testing), and hurts accessibility. Real protection is server-side (already there: hotlink protection, rate limits, rights checks). Keep the "right-click a series card opens a new tab" feature. |
| D2 | **Sign-in required vs Google.** While *Sign-in required* is on, search engines see only the login page, so the site cannot appear on Google. Off, guests read and Google can index. | Launch with it **off** (as now). Switch it on later only if you decide visibility matters less than control. |
| D3 | **Which languages for the site's own menus and buttons?** Today there is one language and no translation system. | Tell me the 1-3 languages you want first (and whether Arabic/right-to-left is one). |
| D4 | **Offline reading** ("download chapter"): do you want it? It stores pages in the reader's browser only. | Yes, but after Phases 1-4. |
| D5 | **Cloudflare (or another CDN) in front of the server?** It hides the server's real IP and absorbs floods, but needs a few settings (Phase 1, item 1.9). | Yes. |
| D6 | **Drop the unused `users.password_hash` column** (a one-way migration: the old password logins can never come back). | Yes, in Phase 6, after the site has run a few weeks. |
| D7 | **Community** (emojis, realms, ranks), parked by you. Keep parked? | Keep parked; hide its switch until it has a page (item 6.3). |
| D8 | **How big a server will you rent?** | Decide in Phase 2 from measured numbers, not before. |

---

## 3. Phase 0: your test (no code)

Do this first. It finds what no reading of the code can.

| # | Do | Result I need |
| --- | --- | --- |
| 0.1 | Follow [`TEST_COMPUTER.md`](TEST_COMPUTER.md) to Section 6 (site running, you are the owner). | Anything that failed, with the "What to send" output (Section 8 of that guide) |
| 0.2 | Go through its Section 7 test list: visitor, import a series, readers on two windows, admin pages, backup, optional translation. | A list of "wrong / slow / odd" things, with what you clicked |
| 0.3 | While a chapter is being imported, run `docker stats --no-stream`, `free -h` and `df -h /` three times (idle, during import, while reading). | The three outputs. This is the start of the sizing in Phase 2 |
| 0.4 | **Owner actions** (open since the first audit; only you can do them): **U1** rotate the Google client secret that was committed in the old `Manga-Website` repository; **U2** make sure `ALLOW_PLAINTEXT_SECRETS` is not set on the server; **U4** get a Sentry (or similar) DSN for error alerts. | Done / not done |
| 0.5 | Real-site checks (roadmap items 24-27): one series from each supported source in *Test & Live Preview*, one real MangaUpdates link, one book-format and one long-strip series by eye, one real translated chapter. | What each one showed |

---

## 4. Phase 1: safe to put on the internet

Do not point a domain at the server before these are done.

| # | Problem (evidence) | Fix | Size / risk |
| --- | --- | --- | --- |
| 1.1 | ✔ `docker-compose.yml` publishes the API (`8000:8000`, lines 274-275) and the website (`8080:8080`, lines 417-418) on **every network interface**, and Docker bypasses the firewall for published ports. It also hard-codes `APP_ENV: development` (lines 53, 207, 239, 366). `GUIDE.md` works around both with a server-only override file, but a forgotten override means an open, development-mode server. | Make the safe setting the default: publish on `127.0.0.1` only, and take the mode from `.env` (production unless `make_env.py --local`). Keep the override file working. Tests: `docker compose config` shows no public bind. | S / low. Test computer keeps working at `localhost`; reaching it from another machine then needs an explicit opt-in. **Needs a real `docker compose` run, which I cannot do here: you will check it.** |
| 1.2 | ✔ `make_env.py` writes `.env` with the default permissions (readable by every user on the server); only the guide's `chmod 600` fixes it. | Create it as owner-read-only from the start; refuse to run if the file exists with wider permissions. Test. | S / none |
| 1.3 | ✔ Anti-tamper guard (decision **D1**). | Per your decision. | S / none |
| 1.4 | ✔ CI never builds the Docker images or checks `docker-compose.yml`. Real failures found so far (workers running the API, nginx refusing to start, an image-build race) were found on a real machine. | Add a CI job: `docker compose config`, build `backend` and `web`, start the stack with a throw-away `.env`, wait for healthy, `curl /healthz` and the home page. | M / low (adds a few minutes to CI) |
| 1.5 | ◐ Behind a proxy or CDN that hides visitors' addresses, the rate limiter (300 requests a minute per address; a full page load makes about 10 API calls) sees **one address for everybody** and can lock the whole site out. `TRUSTED_PROXY_CIDRS` fixes it but is easy to forget. | Add a start-up warning and an Admin → System Health line: "every request seems to come from one address: set `TRUSTED_PROXY_CIDRS`". Document the CDN ranges in `GUIDE.md` (partly done). | M / low |
| 1.6 | ◐ `backend_fastapi/deployment/setup-server.sh` turns off SSH password and root login (locks you out without an SSH key) and expects the project in `/var/www/manga`; the backup scripts there assume a database on `localhost:5432` and pictures in `/app/storage`, which is not how Docker runs it. They invite mistakes. | Delete or rewrite them to match the Docker setup (the guide already has working commands). | S / low |
| 1.7 | `GUIDE.md` has no step for key-only SSH, `fail2ban`, or a non-root deploy user. (`ufw` and automatic security updates are there.) | Add them as careful, tested, optional steps (never as a script that can lock you out). Docs only. | S / none |
| 1.8 | ◐ Roadmap item 33: the base image's `pg_dump` is version 17, the server is PostgreSQL 14. It should read older servers, but was never checked on the real build. | Take one backup and restore it on a spare database during the first real run; record the result. | S / none |
| 1.9 | ◐ Hiding the real IP (`GUIDE.md` Section 12) was written but **never run for real** (Cloudflare, tunnel, bare-IP test). | Rehearse it once on the first server, fix the guide from what happens. Decision **D5**. | M / none |
| 1.10 | ✔ Not yet done end to end: the whole of `GUIDE.md` on a fresh server (Docker install, build, Caddy and Let's Encrypt, reboot test, restore test). Marked "not run" at the top of the guide. | A dry run on a cheap rented server (or your VM for everything except DNS and certificates), then fix the guide from every surprise. | M / none |

**Done when:** a fresh server built only from `GUIDE.md` passes the bare-IP test,
has no public port except 22/80/443, runs in production mode, and a backup of it
restores on a second machine.

---

## 5. Phase 2: survives real traffic

You said: measure first, then decide. Nothing here builds a monitor.

| # | What | How |
| --- | --- | --- |
| 2.1 | **Baseline numbers** on your test machine (from Phase 0.3): memory and CPU per container when idle, while importing and while reading. | `docker stats --no-stream`, `free -h`. I turn them into a table. |
| 2.2 | **Load test** with what is already in the repo (`backend_fastapi/loadtest/`): 50, 200, 500 readers browsing and reading, on the full stack and on the small profile. | Run on the real server once, off-peak. I read the results and tell you where it bends first (database, API workers, nginx, disk). |
| 2.3 | **Size the server from the numbers**: RAM, CPU, disk, swap, and how fast pictures fill the disk (`chapters.pages_bytes` already records sizes; Admin shows a storage report). | One page in `GUIDE.md`: "N readers needs this server". Decision **D8**. |
| 2.4 | **Limits so one service can't eat the machine**: memory caps for the full stack (the small profile has them; the full one has none), Redis `maxmemory`, Postgres connection and memory settings. | Set from 2.1-2.3, not guessed. |
| 2.5 | **Heavy work never blocks readers**: confirm scraping, compression, OCR and translation stay on their own queues while the site is under load. (The architecture already separates them; this proves it.) | Run an import and a translation during the load test; readers' response times must stay flat. |
| 2.6 | **Disk growth plan**: when the picture folder passes a threshold, move pictures to S3/R2 or a CDN (design exists: `audit/storage-design.md`). | Build only if 2.3 says the disk will run out within a year. |

---

## 6. Phase 3: the reading experience

What readers feel every day.

| # | Problem (evidence) | Fix | Size / risk |
| --- | --- | --- | --- |
| 3.1 | ✔ `ChapterViewer.js` has **no keyboard, tap-zone or swipe controls** (no key handler at all); readers can only scroll and use the dropdown. | Arrow/Space/PageUp-Down keys, tap left/right zones on touch screens, swipe in paged layouts, "next chapter" at the end; respect the series' reading direction (right-to-left for manga). Tests. | M / low |
| 3.2 | ✔ Nothing loads the next pages or the next chapter ahead of time. | Preload the next few images and the next chapter's first pages while reading; stop when the connection is slow (data saver). | M / low |
| 3.3 | ✔ `public/sw.js` caches only the basic page files and (without limit) cover images. | Optional "download chapter" button that stores its pages in the browser (decision **D4**), with a size cap and a "remove downloads" button. Fits your rule that reading data stays on the reader's device. | L / medium |
| 3.4 | ◐ Each full page load makes about 10 API calls (BT-15), and the login page asks for footer, support links and ads and gets 401 for guests while *Sign-in required* is on (BT-13, noise). | Combine the start-up calls into one; skip the calls guests can't use. | S-M / low |

---

## 7. Phase 4: search and discovery

| # | Problem (evidence) | Fix | Size / risk |
| --- | --- | --- | --- |
| 4.1 | ✔ Search (`services/manga_service.py:225-232`) matches **four fields** with `icontains` (title, original title, alternative titles and authors, the last two converted to text). A trigram index exists **only for the title** (migration `20260510_add_manga_title_trgm_index`), so the OR of four fields can't use it: it scans the whole table. It also forgives no typos ("one pice"). | PostgreSQL trigram indexes on every searched field (or one generated search column) and a typo-tolerant match (`pg_trgm` similarity) ranked best-first; keep the SQLite fallback for tests. Migration with a safe downgrade. Tests with misspellings. | M / medium (a migration; `CREATE EXTENSION pg_trgm` is already needed by the old one) |
| 4.2 | ✔ No "Popular this week", "Top rated" or "Similar series" lists. The data is already there: a per-day view counter (`MangaDailyView`, written when a chapter is read), ratings and genres. | Build the three lists from those. No new tracking, so your privacy rules hold. Cached for a few minutes. | M / low |
| 4.3 | ◐ Genre filtering casts the genre list to text and uses `LIKE` (`manga_service.py:123-134`). Fine for hundreds of series, slow for tens of thousands. | Measure in Phase 2; fix (a proper array/JSON index) only if it shows. | S-M / low |

---

## 8. Phase 5: found by Google, shared nicely

| # | Problem (evidence) | Fix | Size / risk |
| --- | --- | --- | --- |
| 5.1 | ✔ Every shared link shows the same generic "Manga Reader" preview: the only Open Graph/Twitter tags are the fixed ones in `index.html`. Link previews in chat apps don't run the site's JavaScript. | For a series (and chapter) address, serve a small head with that series' title, cover and description to crawlers and link-preview bots (from the API, through nginx), plus `application/ld+json` structured data. Normal readers still get the same app. | M / medium |
| 5.2 | ✔ There is **no `robots.txt`** (the file isn't in `public/` and nothing serves one), so `/robots.txt` returns the app's home page. The sitemap exists (`/sitemap.xml`, `/rss.xml`). | Serve a real `robots.txt` that points to the sitemap and keeps `/admin` and `/api` out. | S / none |
| 5.3 | ◐ `<link rel="canonical">`, and a per-page `<title>` and description (the app is a single-page app). | Set them per page. | S / low |
| 5.4 | Decision **D2**: Google can't read the site while *Sign-in required* is on. | Documented in the guide and shown next to the switch. | S / none |

---

## 9. Phase 6: finish or remove half-built things

You asked what should be removed, edited, fixed and rerouted. These are the
leftovers.

| # | Item (evidence) | Action |
| --- | --- | --- |
| 6.1 | ◐ **Features with a server but no page** (BT-11): notification preferences; comment edit, vote, react, report and moderation. | Build the pages (notification preferences first: small). |
| 6.2 | ◐ About **60 functions in `src/services/api.js`** are never called (BT-10), and `suggestion_service` is unused. | Remove the ones with no page planned; keep those for 6.1. |
| 6.3 | ◐ **Community** has a Site Functions switch and no page (decision **D7**). | Hide the switch until there is a page. |
| 6.4 | ◐ **Legacy API aliases:** every route is registered three times under old and new prefixes (roadmap item 9, "doing"). A log line and a metric already show which old ones are still called. | After a few weeks of real logs, remove the old mounts. |
| 6.5 | ◐ **`users.password_hash`** is unused (readers have no passwords). | Drop in a migration (decision **D6**); mark it lossy in `AUDIT_LOG.md` §2. |
| 6.6 | ◐ `deployment/manga-site.conf` (host nginx) and `deployment/nginx/site.conf` (container) are two copies of similar rules that can drift apart. The guide uses Caddy. | Keep one as the tested reference and delete or clearly label the other. |
| 6.7 | ◐ SQLite development databases miss several tables (BT-14). | State "use PostgreSQL locally" in the developer notes (the guides already do) and stop pretending SQLite works. |

---

## 10. Phase 7: quality

| # | Item | Fix |
| --- | --- | --- |
| 7.1 | ✔ **One interface language**, no translation system. | Add one (decision **D3**), move the texts out of the components, support right-to-left layout. |
| 7.2 | ✔ Only about **45** accessibility labels/roles across the whole frontend; the anti-tamper guard blocks right-click and shortcuts. | A pass for screen readers and keyboard use: labels, focus order, contrast, the reader. Test with a screen reader once. |
| 7.3 | ✔ Only unit tests; **no browser test** of "open site → series → read a chapter". | A Playwright test in CI (Chromium is available), starting with that one path, then sign-in and a bookmark. |
| 7.4 | ◐ A few features were verified only against synthetic pages (per-site scraper settings, bubble shapes, the Anime-Planet parser): `AUDIT_LOG.md` §5. | Check each on one real example (Phase 0.5) and fix what shows. |
| 7.5 | ◐ Tailwind 3 pulls in one build-time advisory (`braces`); the upgrade to Tailwind 4 is blocked (roadmap item 40). | Do it when you allow the upgrade tool; remove the CI exception. |

---

## 11. Phase 8: running it day to day

| # | Item | Fix |
| --- | --- | --- |
| 8.1 | An outside **uptime check** (it can't run on the server it watches). | Free external monitor on `/healthz` and the home page; alert to your phone. |
| 8.2 | **Error alerts** (roadmap item 13): code is ready, needs your DSN (**U4**). | Set `SENTRY_DSN` in the Secret Vault. |
| 8.3 | **Backup alerts**: today a failed backup is only visible if you look. | A notification to the owner when a scheduled backup fails or is more than a week old. |
| 8.4 | **Disk alert** exists (storage report, 80%); confirm it reaches you. | Test it once on purpose. |
| 8.5 | **Update routine**: Dependabot is configured; someone has to read its pull requests. | A monthly 20-minute routine in `GUIDE.md`: read, merge, update the server with Section 14 (backup first). |
| 8.6 | **Restore drill**: a backup is only real once restored. | Do it once a quarter on a spare machine (steps are in the guide). |

---

## 12. Suggested order

1. **Phase 0** (you): test, answer Section 2.
2. **Phase 1** in two pull requests: *1.1-1.3 + 1.6* (the code and defaults), then
   *1.4, 1.5, 1.7* (CI, proxy warning, guide steps). Then **1.8-1.10** on the first
   real server.
3. **Phase 2** measurements from your test numbers, then on the real server.
4. **Phases 3, 4, 5** (what readers and Google notice), one pull request each:
   reader controls and preloading; search and the three lists; link previews and
   `robots.txt`.
5. **Phase 6, 7, 8** alongside, smallest first.

Why this order: Phase 1 is what an attacker would find first and what is hardest
to undo after launch; Phase 2 stops you renting the wrong server; Phases 3-5 are
what makes people stay and arrive; the rest is polish and upkeep.

I will keep this file up to date: each item is marked done with its pull request
when it ships, and anything the test finds is added here with the next number.

---

## 13. Corrections to what I told you earlier

Checked against the code while writing this plan:

- **Search** (my earlier suggestion 3): I said the search "can't use an index".
  More exactly: a trigram index **does exist for the title**, but the search also
  matches three other fields without an index, so the database can't use it. Item
  4.1 is therefore "index all searched fields and add typo tolerance", not "add
  the first trigram index".
- **Read history** (your question): the `read_history` table is **not** unused any
  more. It now holds the chapters signed-in readers have opened, so a new phone
  shows their dimmed chapters (pull request 45). I withdrew the suggestion to drop it.
- **F12 and right-click:** the guide I wrote told you to press F12 for the console;
  the site blocks it (item 1.3). `TEST_COMPUTER.md` now says to use the browser menu.
