#!/usr/bin/env sh
if ! set -euo pipefail 2>/dev/null; then
  set -eu
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
: "${APP_ENV:=development}"
export APP_ENV
python "${SCRIPT_DIR}/wait_for_services.py"

: "${CELERY_CONCURRENCY:=8}"

# Optional per-queue binding. Tasks are routed to named queues (scrape/compress/
# ocr/translation/email/maintenance — see celery_app task_routes); set CELERY_QUEUES
# to consume a specific subset so one busy job type can't starve the others. When
# unset the worker consumes only the default queue, which would strand routed
# tasks, so callers that rely on the routed queues must set this (the scale
# docker-compose overlay wires one worker per queue).
set -- \
  -A backend_fastapi.app.core.celery_app:celery_app \
  worker \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --concurrency="${CELERY_CONCURRENCY}" \
  --hostname="celery@%h"

if [ -n "${CELERY_QUEUES:-}" ]; then
  set -- "$@" --queues="${CELERY_QUEUES}"
fi

exec celery "$@"
