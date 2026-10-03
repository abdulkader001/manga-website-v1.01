# Working rules for this repository

## Every change is recorded

1. **Audit log.** Every pull request adds an entry at the top of the
   "Change entries" section in `AUDIT_LOG.md`, using the template at the end
   of that file. The entry covers what changed, why, the main files, database
   migrations, settings, how to check it, and how to undo it. Fill in the
   merge commit SHA when it is known. If you can't, the next PR fills it in.
2. **Migrations.** Every new Alembic migration gets a row in `AUDIT_LOG.md`
   §2 saying what its downgrade does. Mark it **lossy** if a downgrade can't
   restore the data.
3. **Guides.** If a change affects how the site is installed, configured,
   updated, or operated by the admin, update `GUIDE.md` (live Linux server) in
   the same PR (the relevant section, the troubleshooting table, and the quick
   checklist), and `TEST_COMPUTER.md` (trial on the owner's own computer) when
   the steps or the test list there change.
4. **"How the site is put together"** (`AUDIT_LOG.md` §1) is updated when a
   change moves a setting between `.env`, the Secret Vault and Admin
   Settings, changes roles/permissions, or adds a server-side command.

## House rules the owner has set

- Only database/Redis connection, the site address, signing/encryption keys
  and the admin identity stay in `.env`. Every other setting belongs in the
  Secret Vault.
- Four roles: **owner** (one; never changed, removed or touched by anyone;
  ownership never passes), **Admin** (at most two), **sub-admin** (many, within
  seats) and **user**. Power over a person needs a strictly higher tier: Admins
  over sub-admins and users, sub-admins over users.
- Site-owner powers: the Secret Vault, Admin Settings (including its cache
  purge and delete-all actions), API Management (OCR / translation / AI
  providers), the Scraper AI (its key and Custom Parser), branding,
  donations, Storage & Backups, Geolock, revealing e-mails and Role
  Management. An Admin holds all but Admin Settings, cache and delete-all by
  default; only the owner switches an Admin's powers (switching one on needs the
  owner's authenticator code). A holder needs an authenticator and a fresh code
  to use them. Sub-admins can never hold them; they are never in presets. Admins
  can't change another Admin, themselves or the owner, and see sub-admins' and
  users' e-mail only.
- The owner shares 50 sub-admin seats between the Admins (25 each unless set),
  sets a ceiling on what a sub-admin may hold, and alone creates roles (presets).
- Each Admin keeps a succession line of two sub-admins. Automatic succession
  (owner only, off by default, owner's code to change): an Admin idle longer than
  the chosen days (default 60) becomes a user and the first eligible sub-admin in
  their line takes the seat as it is. The owner can hand a seat over at once.
  Every change is audited and sent to the owner.
- Roles: owner, admin, sub-admin, user.
- Readers sign in with a magic link, Google or Microsoft only. No reader
  passwords. One inbox gives one account, for life.
- "Sign-in required" is **off by default**: guests can browse and read, and
  bookmarks work for them (kept in the browser by series ID). The owner switches
  it on in Admin -> Site Functions once the Admins are in place; then nobody sees
  the site before signing in. Sign-in, sign-up and the admin area are never
  behind it.
- **Site Functions** (Admin -> Site Functions: the on/off switch of every main
  website function) and **Tab access** (Role Management: which admin tabs each
  Admin / sub-admin sees, and "switch all powers off") are for the **owner only and
  can never be delegated**: no permission opens them, not even for an Admin. Every
  new main website function gets an entry in `core/site_functions.py` with a real
  enforcement point, and every new admin tab an entry in `core/admin_tabs.py`
  (`tests/test_route_audit.py` fails when the frontend, the routes and the tab
  registry disagree).
- Visitors' IP addresses are for the owner only (Site Functions -> Privacy and
  security): never return an IP address from an API to anyone but the owner, and
  never write one to a log line.
- Reading history and bookmarks live in the reader's browser, which stays the
  main copy. For a **signed-in** reader the server also keeps two things under
  their account so they follow them to a new phone or computer: the bookmarked
  series ids (these also feed new-chapter alerts) and which chapters they have
  opened with when (chapter ids and times, nothing else: no pages, no
  scrolling, no reading time). Guests' bookmarks and history stay in their
  browser only. (Owner's decision, 2026-10-03: a reader who signs in on a new
  phone must see their dimmed chapters; before this the history never left
  the browser.)
- Never hard-code admin credentials or e-mails in source.
- Translation runs on the server through API providers (no in-browser
  models).

## Checks before pushing

```bash
ruff check backend_fastapi
python -m pytest backend_fastapi/tests -q -p no:warnings
npx tsc --noEmit && npx vitest run && npx vite build
```
