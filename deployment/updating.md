# Keeping dependencies and images up to date

Everything is pinned, so nothing changes unless someone merges a change. That
makes builds repeatable and puts every update in a pull request you can read.

## What is pinned, and where

| What | How | Where |
| --- | --- | --- |
| Python packages | exact versions, plus a full lock of every dependency | `backend_fastapi/requirements.txt`, `requirements.lock` |
| JavaScript packages | exact versions (`save-exact` in `.npmrc`), plus the lock | `package.json`, `package-lock.json` |
| Base images | tag **and** digest (`image:tag@sha256:...`) | `backend_fastapi/Dockerfile`, `deployment/web.Dockerfile`, `docker-compose.yml` |
| GitHub Actions | major version tags | `.github/workflows/ci.yml` |
| Node version | `.nvmrc` (22; Vite 7 needs 22.12 or newer) | `.nvmrc` |

A digest pins the exact image bytes: a tag such as `python:3.11-slim` moves
whenever the maintainers publish, a digest never does. The tag stays in the
line so a person can read what it is.

## When

- **Weekly, automatic:** Dependabot (`.github/dependabot.yml`) opens pull
  requests for Python and JavaScript packages: one grouped PR for minor and
  patch updates, separate PRs for majors. Monthly for GitHub Actions and base
  images.
- **Weekly, automatic:** the `Dependency audit` CI job runs every Monday even
  when nobody pushes. It fails on a Python advisory (`pip-audit` against the
  lock) or a high or critical npm advisory. A red run means an advisory needs
  attention this week, not "someday".
- **Security advisory:** do not wait for the weekly run; merge the fix as soon
  as CI is green.

## How to merge an update

1. Open the Dependabot pull request and wait for CI (backend tests on
   PostgreSQL, frontend lint, tests and build).
2. Read the release notes for anything major. Vite 8 is deliberately ignored by
   Dependabot: it replaces the bundler and needs a config change, so upgrade it
   on purpose, in its own pull request.
3. For base images, CI does not build the Docker images. Before merging an
   image bump, build them once:
   `docker compose build` and start the stack, then load the site.
4. Merge. Deploy as usual (the image rebuild picks up the new pins).

## Updating by hand

- **Python:** edit `requirements.txt`, then
  `pip-compile --output-file=requirements.lock requirements.txt` and run the
  backend tests. Commit both files.
- **JavaScript:** `npm install <package>@<exact version>` (exact, thanks to
  `.npmrc`), then `npm test`, `npm run lint`, `npm run build`.
- **A base image digest:** look up the new digest for the tag, for example
  `docker buildx imagetools inspect public.ecr.aws/docker/library/python:3.11-slim`,
  and replace the `@sha256:...` part in every file that uses that image. Build
  before merging.

## Do not

- Do not loosen a pin to `^` or `latest` to "fix" a build. Find out why it
  failed.
- Do not edit `requirements.lock` or `package-lock.json` by hand.
- Do not point base images at an untagged or `latest` image.

## Known gaps

- The CI PostgreSQL and Redis service images (`postgres:16-alpine`,
  `redis:7-alpine`) are tags, not digests, and differ from the compose file's
  PostgreSQL 14. They only run the tests, but bring them in line with
  production when you next touch either.
- `edoburu/pgbouncer:1.23.1-p2` (scale compose file) is pinned to an exact
  version tag but not a digest.
