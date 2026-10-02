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
- The Secret Vault, Admin Settings, API Management (OCR / translation / AI
  providers), branding, donations and Role Management (permissions,
  presets, appointing or removing sub-admins, any role change) are
  main-admin only and can never be granted to sub-admins — not even read
  access.
- The Scraper AI is main-admin only: its API key (Series Management →
  Scraper AI API) and creating parsers with it (Custom Parser). Sub-admins
  don't see those sections, can't be granted them, and scrapes they start
  never call the AI.
- Roles: admin (main), sub-admin (per-person permission toggles), user.
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
