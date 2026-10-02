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
3. **Guide.** If a change affects how the site is installed, configured,
   updated, or operated by the admin, update `GUIDE.md` in the same PR (the
   relevant section, the troubleshooting table, and the quick checklist).
4. **"How the site is put together"** (`AUDIT_LOG.md` §1) is updated when a
   change moves a setting between `.env`, the Secret Vault and Admin
   Settings, changes roles/permissions, or adds a server-side command.

## House rules the owner has set

- Only database/Redis connection, the site address, signing/encryption keys
  and the admin identity stay in `.env`. Every other setting belongs in the
  Secret Vault.
- Site-owner powers: the Secret Vault, Admin Settings (including its cache
  purge and delete-all actions), API Management (OCR / translation / AI
  providers), the Scraper AI (its key and Custom Parser), branding,
  donations, Storage & Backups, Geolock, revealing e-mails and Role
  Management (permissions, presets, appointing or removing sub-admins).
  The owner (main admin) can give any of them to a trusted sub-admin and
  take them back at any time. Guardrails that must stay: only the owner
  gives or takes them, giving needs the owner's authenticator code; at most
  two sub-admins ("deputies") hold any of them; a holder needs an
  authenticator and a fresh code to use them; they are never in presets; a
  sub-admin can never pass them on, change their own permissions, or change,
  reset or demote a deputy; demotion strips them.
- Automatic succession (owner only, off by default, owner's code to change):
  a deputy idle longer than the chosen days (default 60) becomes a user and
  the most active eligible sub-admin inherits their site-owner powers.
  Switching it on never demotes anyone at once; every change is audited and
  sent to the owner.
- Roles: admin (main, the owner), sub-admin (per-person permission toggles;
  up to two can be deputies), user.
- Readers sign in with a magic link, Google or Microsoft only. No reader
  passwords. One inbox gives one account, for life.
- Bookmarks and reading history stay in the reader's browser, not on the
  server.
- Never hard-code admin credentials or e-mails in source.
- Translation runs on the server through API providers (no in-browser
  models).

## Checks before pushing

```bash
ruff check backend_fastapi
python -m pytest backend_fastapi/tests -q -p no:warnings
npx tsc --noEmit && npx vitest run && npx vite build
```
