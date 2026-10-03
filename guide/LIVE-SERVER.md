# Live server: the real website people visit

This is the path for **the** website: one Linux server on the internet, your
own domain, HTTPS, where readers come to read. Do it in this order. Each part
links to the exact section of [`GUIDE.md`](../GUIDE.md) with the commands, so
there is one copy of every command to keep up to date.

Just want to try the site on your own computer first, with no domain? Use the
local guide for your system instead ([README](README.md), path A). Nothing you
do there is public, and you can throw it away.

---

## What you need before you start

| Thing | Notes |
| --- | --- |
| A Linux server | Ubuntu 22.04/24.04 or Debian 12. 2 CPU / 4 GB RAM is comfortable; 1 GB works with the small profile ([`GUIDE.md` §4.2](../GUIDE.md#42-small-server-about-1-gb-ram-1-cpu)). |
| A domain name | For example `manga.example.com`. You will point it at the server. |
| A Google sign-in client for that domain | You become the owner by signing in with Google. Redirect address: `https://YOUR-DOMAIN/api/auth/google/callback` ([`GOOGLE_LOGIN_SETUP.md`](../GOOGLE_LOGIN_SETUP.md), use your domain instead of `localhost`). |
| A phone with an authenticator app | Google Authenticator, Microsoft Authenticator, Aegis, 1Password… |
| E-mail sending (SMTP) | For readers' sign-in links. Can be added later in the Secret Vault. |

---

## Part 1: Server, firewall and DNS

1. Firewall: only ports **22, 80, 443** open
   ([`GUIDE.md` §8 Step 1](../GUIDE.md#step-1--server-and-firewall)).
2. DNS: an `A` record from your domain to the server's IP
   ([§8 Step 2](../GUIDE.md#step-2--dns)).

## Part 2: Install the site

3. Install Docker and download the code: [`INSTALL-LINUX.md`](INSTALL-LINUX.md)
   Steps 1 and 2.
4. Create `.env` **without** `--local` (that one is for localhost only):
   `python3 backend_fastapi/scripts/make_env.py`, then set your domain lines
   ([`GUIDE.md` §3.3](../GUIDE.md#33-variables-for-your-domain-production)).
5. Put the owner line and the Google client in `.env`
   ([`INSTALL-LINUX.md` Step 6](INSTALL-LINUX.md#step-6--tell-the-site-who-the-owner-is)),
   protect `.env` and keep a copy off the server
   ([§8 Step 4](../GUIDE.md#step-4--protect-and-back-up-env)).

## Part 3: Production mode and HTTPS

6. Production mode and private ports: the small `docker-compose.override.yml`
   ([§8 Step 5](../GUIDE.md#step-5--production-mode-and-private-ports)).
7. Start it ([§8 Step 6](../GUIDE.md#step-6--start)) and wait until
   `docker compose ps` shows everything healthy.
8. HTTPS with Caddy ([§8 Step 7](../GUIDE.md#step-7--https-with-caddy)) and
   start on boot ([§8 Step 8](../GUIDE.md#step-8--start-on-boot)).
9. Open `https://YOUR-DOMAIN`. You should see the home page with the padlock.

## Part 4: Become the owner

10. **Over HTTPS only**, sign in with Google using the owner e-mail, complete
    your profile, then open **Admin** and set up your authenticator
    ([`GUIDE.md` §6](../GUIDE.md#6-become-the-owner-sign-in-with-google)).
    `admin-status` must now say `Owner: claimed`.

## Part 5: First settings (in the admin area)

11. **Secret Vault**: SMTP for sign-in e-mails, OCR / translation keys,
    Microsoft sign-in if wanted
    ([§6.1](../GUIDE.md#61-move-the-remaining-settings-into-the-secret-vault)).
12. **Branding and footer**: site name, logo, your own social links. Save them
    as the owner: what the server stores is what every visitor sees.
13. **Site Functions**
    ([§6.4](../GUIDE.md#64-site-functions-switch-the-websites-functions-on-and-off-owner-only)).
    *Sign-in required* starts **off**, so guests can read and keep bookmarks in
    their browser. Leave it off while you set up; switch it on once your Admins
    are in place if you want every visitor to log in first
    ([§6.2](../GUIDE.md#62-sign-in-required-off-at-the-start-you-switch-it-on-when-ready)).
14. **Role Management**: Admins, sub-admins, seats, succession and tab access
    ([§6.3](../GUIDE.md#63-admins-sub-admins-and-automatic-succession),
    [§6.5](../GUIDE.md#65-tab-access-and-switch-all-powers-off-owner-only)).
15. Import your first series ([§7](../GUIDE.md#7-start-using-the-sites-functions)).

## Part 6: Keep it safe

16. Backups before you add much content: nightly script and
    **Admin → Storage & Backups**
    ([§9](../GUIDE.md#9-backups-do-this-before-you-add-content)).
17. Hide the server's real IP behind a CDN or tunnel
    ([§8](../GUIDE.md#hide-the-servers-real-ip-address-recommended)).
18. Every update: back up, update, and know how to roll back
    ([§12](../GUIDE.md#12-updating-safely-and-rolling-back)). Read the newest
    entries in [`AUDIT_LOG.md`](../AUDIT_LOG.md) first.

When something goes wrong: [`GUIDE.md` §10 Troubleshooting](../GUIDE.md#10-troubleshooting).
The full list to tick off: [`GUIDE.md` §11 Quick checklist](../GUIDE.md#11-quick-checklist).

---

## Local test vs live server at a glance

| | Local test (your computer) | Live server (the real site) |
| --- | --- | --- |
| Guide | `INSTALL-WINDOWS/MACOS/LINUX.md` | this page |
| Address | `http://localhost:8080` | `https://your-domain` |
| `.env` made with | `make_env.py --local` | `make_env.py` + domain lines (§3.3) |
| HTTPS | no | yes (Caddy) |
| `docker-compose.override.yml` | not needed | needed (§8 Step 5) |
| Google redirect address | `http://localhost:8000/api/auth/google/callback` | `https://your-domain/api/auth/google/callback` |
| Who can see it | only you | everyone |
| Backups | not needed | required (§9) |
