# Frontend audit — 2026-09-30

## Build and dependencies

- `vite build` and `tsc --noEmit` pass; CI runs both.
- Runtime dependencies are now 5 (`react`, `react-dom`, `react-router-dom`,
  `@tanstack/react-query`, `express` for the dev/standalone gateway). Six unused
  packages were removed in the clean-up: `dompurify`, `lucide-react`,
  `onnxruntime-web`, `prop-types`, `web-vitals`, `tesseract.js`.
- `npm audit`: 4 findings (1 high in `vite`, 3 moderate in `esbuild` and
  `react-router`/`react-router-dom`). They affect the development server and
  router SSR features, not the production bundle. Fixing them needs major
  upgrades (`vite` 6+, `react-router-dom` 7); do it as its own change with a
  full click-through.

## Content-Security-Policy vs external resources

`index.html` loads two stylesheets from external hosts:

- `https://fonts.googleapis.com/icon?family=Material+Icons…`
- `https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css`

The production policy (`deployment/nginx/site.conf`) sets
`style-src 'self' 'unsafe-inline'` and `font-src 'self' data:`, which blocks
both, so icons disappear once deployed behind that nginx. Fix: install
`@fortawesome/fontawesome-free` and `material-icons` from npm, import their CSS
in `src/index.jsx`, and delete the two `<link>` tags. (Inferred from the policy;
not loaded against the real CDNs from the build environment.)

## Login gate

Every page except `/login`, `/complete-profile` and the magic-link routes is
behind `AuthGuard`. Consequences: search engines cannot index series or
chapters (while `/sitemap.xml` and `/rss.xml` list them), and ads reach logged-in
users only. This is the original design; consider public browsing with login
required only for actions (bookmarks, ratings, comments, translation).

## Mismatches with the backend

- Import form offers "Western Comic / Webcomic" (`comic`); backend accepts
  `manga`, `manhwa`, `manhua` only and stores anything else as `manga`.
- Series layout after import (spread splitting, reading order) and re-compression
  are available only as API endpoints, not in the UI.

## Removed in the clean-up (unused)

`CustomTabs.js`, `Homepage.css`, `MangaCard.js`, `utils/adminUsers.js`,
`plugins/ocr/tesseract.ts` (never imported), `RoleManagement.test.jsx` (no test
runner or `@testing-library` installed), and the five font files in
`public/fonts/` (referenced nowhere).
