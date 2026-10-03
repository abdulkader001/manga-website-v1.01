# Site Functions, tab access, route audit and hardening: report and recommendations

Date: 2026-10-03. Written for the site owner. Everything below was checked against
the code in this repository; where something could not be run here it says so.

## 1. What you asked for, and the decisions that follow

| You asked for | What was built | Decision I took (change it if you disagree) |
| --- | --- | --- |
| A tab with **all the website's functions**, each with an on/off toggle, like the existing "sign-in first" switch | **Admin → Site Functions**: 18 functions in six groups, each enforced on the server and hidden from the pages | Owner only, **never delegable**: no permission opens it, so not even an Admin you gave every other power sees it. This follows your last instruction ("not accessible to anyone other than the owner") |
| The owner chooses, **person by person**, which admin tabs they see (a report moderator must not see the scraper or the API) | **Role Management → Tab access**, enforced in the API as well as the menu | Owner only, **not delegable** (your latest message). Admins still adjust sub-admins' *permissions*; they can't change anyone's *tabs*. If you want Admins to set tabs for their own sub-admins, it is a small change (see §6) |
| The owner can switch **all** of an Admin's powers off (Admin by name, seat filled, no power) | **Switch all powers off** per person | The title, the seat, the seat counts and succession lines stay. Everything in the admin area answers 403 for that person until you switch it back |
| Hide visitors' **IP addresses** from everyone but the owner; protect against reverse-IP tracking | IP addresses are owner-only in every API; two switches in Site Functions; a catch-all nginx block; a hardening guide in `GUIDE.md` §8 | "Reverse IP" is two different risks, so both were handled (§4) |
| Check **every route/mismatch** and make the site production ready | An automated audit (`tests/test_route_audit.py`) plus 12 real mismatches found and fixed (§3), and two checks kept as permanent tests | |

## 2. What exists now

### 2.1 Site Functions (Admin → Site Functions)

Each function has a real enforcement point; `tests/test_site_functions.py` proves a function that is off refuses its routes and that a switch with nothing behind it fails the build.

| Group | Function | Default | When it is off |
| --- | --- | --- | --- |
| Sign-in and access | Sign-in required for everyone | on | Guests can browse and read (the older switch, now owner-only) |
| | Maintenance mode | off | Everyone below sub-admin sees a maintenance notice |
| | New accounts | on | Only existing accounts can sign in |
| | Sign in with Google / Microsoft / e-mail link | on | The button disappears and the route answers "provider disabled". **At least one must stay on** |
| Reading and community | Comments, Community, Chapter reports, Notifications | on | The routes answer `FUNCTION_DISABLED` (403); the page hides them |
| Translation and OCR | OCR, Translation | on | Same; the reader's auto-translate hides |
| Site content | Ads, Support links, Sitemap/RSS | on | Same |
| Scraping | Scraping and importing | on | Manual imports/re-scrapes, the Scraper AI **and every scheduled scrape** stop (the scheduled tasks skip) |
| Privacy and security | Visitor IP addresses are for the owner only | on | Everyone who can read the audit log sees addresses |
| | Record visitor IP addresses | on | New audit entries and ad clicks keep no address |

Safety nets: the last sign-in method can't be switched off; `cli_bootstrap functions-reset` puts everything back to its default from the server; each server process re-reads the switches every 5 seconds.

### 2.2 Tab access (Role Management, owner only)

- Per person: *follow permissions* (default), a chosen list of tabs, or no tabs. Quick picks: Reports only, Users only, Series only.
- Enforced where every permission is decided (`permissions_service.has_permission`): a person whose list leaves a tab out loses the permissions bound to that tab, so the tab is hidden **and its API refuses them**. Permissions used outside the panel (removing a comment from the reader, translation fixes, re-scraping one chapter from the reader) are bound to no tab and are untouched, so a moderator keeps their everyday tools.
- A sub-admin is never offered the site-owner tabs (Vault, Admin Settings, API Management, Backups, Geolock).
- Seats: promoting someone starts from the Admin defaults; a hand-over passes the seat **as it is** (tab list and powers-off included); leaving the tier clears both.

## 3. Mismatches found by the route audit, and what was done

The audit reads the real route table and the React source (`tests/test_route_audit.py`, helpers in `tests/_support/`). I also proved it works by reintroducing three of the mismatches below: it failed on all three.

| # | Finding | Why it mattered | Fix |
| --- | --- | --- | --- |
| 1 | **System Health tile and page** were guarded by `view_dashboard`, but the page's API needs `view_system_health` | A sub-admin with default powers saw the tile and an error page | Tile, route and tab now use `view_system_health` (shared by the Health and Audit tabs) |
| 2 | **`/admin/series`** route had no permission guard (its tile did) | Anyone staff could open the page by typing the address | Route guard `edit_series` |
| 3 | **User Database** page was owner-only in the UI while the API let anyone with `view_user_list` in | Admins couldn't use a tab the permission system gives them | UI follows the permission |
| 4 | **`GET /admin/users/all`** was open to *any* staff member and returned every user's record including the **Google account id** | A sub-admin without the user-list power could list every user | Now needs `view_user_list`; the Google id is never returned |
| 5 | **11 staff-only admin routes** named no power (ads config, approved websites, parsers, scraper health, scraping jobs, flagged users and their review, series rights, check overrides, website check settings, ad networks) | Any staff seat could read or change them | Each now needs the matching catalogue power (`manage_ads`, `view_websites`, `modify_website`, `view_scraper_health`, `view_user_list`, `ban_account`, `edit_series`, `submit_manga_url`) |
| 6 | **`/admin/admin-tokens`** (a leftover of the removed admin-password bootstrap) was open to any staff | Showed token records with a source IP | Owner only |
| 7 | The **audit log** returned the source IP and the `operator` column (which can hold the acting admin's e-mail) to everyone who could read it | Visitors' and admins' details visible to Admins/sub-admins | IP and e-mail are owner-only |
| 8 | The ad-click handler wrote the visitor's **IP into the application log** | An IP in log files | Removed from the log line |
| 9 | **Maintenance mode, new accounts and sign-in required** could be changed from Admin Settings, which an Admin can hold | Contradicted "functions are the owner's" | Owner-only (Site Functions); the Admin Settings form ignores them for anyone but the owner |
| 10 | The **ads, ad-slots and support** endpoints answered guests even with sign-in required | More guest surface than needed | Behind "Sign-in required" |
| 11 | The admin hub asked for health data even without the power | A needless refusal on every hub load | Only asks when allowed |
| 12 | `AuthGuard` for a person whose powers are off | Would show a broken page | Shows "your admin powers are switched off" |
| 13 | Frontend to backend: **168 API calls**, all have a backend route | (one false alarm in my first matcher, fixed) | Kept as a permanent test |
| 14 | The list of routes a guest can call | Unplanned open routes | Pinned to an explicit list: a new open route fails the build until someone decides |

**Left as they are, on purpose:** `/admin/status`, `/admin/notifications`, the audit-log views (scoped to the viewer's own rows unless they hold the full-audit power), the 2FA routes and `/admin/permissions/me` (a person whose powers are off must still be told so).

## 4. IP addresses and "reverse IP"

Two different risks, both handled:

1. **Visitors' addresses stored by the site** (audit log, ad clicks): now visible to the owner only, and you can stop recording them (Site Functions → Privacy and security). The user table itself keeps no IP.
2. **Your server's real address** (what a reverse-IP lookup or a scanner finds): this cannot be fixed in the application. `GUIDE.md` §8 ("Hide the server's real IP address") gives the steps: a CDN/proxy or tunnel in front, ports 80/443 open only to it, nothing answering the bare IP, no DNS or e-mail leaks, and a test with `curl`. The repo's host-nginx config now has catch-all blocks that close the connection for the bare IP or an unknown name.

Not verified here: the nginx file was not syntax-checked (no nginx in this environment; needs nginx 1.19.4+ for `ssl_reject_handshake`), and the CDN/tunnel steps are guidance, not something code can do.

## 5. Recommendations, in order

1. **Do the IP hiding (§4.2) before you launch.** It is the one hardening step that no code can do for you. A CDN in front also absorbs most of the overload you worried about.
2. **Set up Google first**, then claim the owner seat (`GUIDE.md` §6), set up the authenticator, and only then touch Site Functions. Check `cli_bootstrap admin-status`.
3. **Use Tab access instead of many custom roles** for moderators: give a report moderator the *Chapter Reports* tab only. Keep the owner's ceiling for what no sub-admin may ever hold.
4. **Rate-limit at the edge** (CDN rules for `/api/v1/auth/request-magic-link`, `/api/v1/auth/google`): the site already limits per address, but the edge stops floods before they reach you. Consider a bot challenge on the e-mail-link form.
5. **Back up before every update** (`GUIDE.md` §9, §12). This release adds a migration (lossy to downgrade: your switches and tab lists are dropped).
6. **Remove the dead admin-token code** (model, service, route) in a later change: nothing in the product uses it any more.
7. **Decide on the audit-log IP retention.** The log is append-only by design (database triggers), so addresses can't be pruned; if you want them kept for a limited time, switch *Record visitor IP addresses* off or plan a retention job.
8. **E-mail decryption context**: the admin router sets a context that is meant to allow decrypting e-mails, but in tests no e-mail ever comes back, so it protects you by luck rather than by design. Worth a dedicated test and a clear rule before anyone "fixes" it.
9. **Search engines**: with sign-in required, crawlers see only the login page. That is the trade-off you chose; switch it off in Site Functions if you want to be indexed.
10. **Open question for you:** should Admins be able to set tab lists for the sub-admins they appoint? Your latest message says owner only, so that is what was built.

## 6. If you change your mind

- *Admins set tabs for their own sub-admins*: change `roles_tabs.py` to use `require_power("manage_roles")` for sub-admin targets (and `authorize_change`-style checks); the enforcement in `has_permission` already works for any actor.
- *A function toggle for another feature*: add one entry to `core/site_functions.py`, guard its routes with `require_function("key")`, and the page, the public config and the tests pick it up (the test fails until the function guards something).

## 7. Production-readiness checklist and how to test it

| Check | How | What you should see |
| --- | --- | --- |
| Migration | `docker compose exec backend alembic current` | `20261016_site_functions_and_tab_access (head)` |
| Owner | `cli_bootstrap admin-status` | `Owner: claimed` |
| Sign-in first | Open the site in a private window | The login page, then the site after signing in |
| Site Functions | Sign in as owner → Admin → Site Functions; switch *Comments* off | The comment box disappears; `curl -s https://your-site/api/v1/comments/config` (signed in) answers 403 `FUNCTION_DISABLED`; switch it back on |
| Last sign-in method | Switch Google and Microsoft off, then try the e-mail link | The page refuses to switch off the last one |
| Tab access | Role Management → Tab access → give a test sub-admin *Reports only* | They see one tile; `GET /api/v1/admin/users` as them answers 403 |
| Powers off | *Switch all powers off* for a test Admin | Their admin pages say so; the seat count is unchanged; *Switch powers back on* restores |
| Who sees what | Sign in as an Admin → Admin → Site Functions | Not listed; `/admin/functions` redirects away |
| IP privacy | Admin views the audit log | Source IP is empty; the owner sees it |
| Real IP hidden | The `curl` test in `GUIDE.md` §8 from another computer | No answer on the bare IP |
| Lock-out recovery | `cli_bootstrap functions-reset` | Everything back to its default |
| Automated | `ruff check backend_fastapi`, `pytest backend_fastapi/tests`, `npx tsc --noEmit && npx vitest run && npx vite build` | All green (last run: 1233 backend, 59 frontend tests) |

What I could **not** do here: sign in with a real Google account, run against PostgreSQL locally (CI does), try it in a real browser, or check nginx syntax. Please do the Site Functions and Tab access rows above once on a staging copy before you rely on them.
