#!/usr/bin/env sh
if ! set -euo pipefail 2>/dev/null; then
  set -eu
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
: "${APP_ENV:=development}"
export APP_ENV
python "${SCRIPT_DIR}/wait_for_services.py"

exec celery \
  -A backend_fastapi.app.core.celery_app:celery_app \
  beat \
  --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
  --pidfile=""
