#!/usr/bin/env sh
if ! set -euo pipefail 2>/dev/null; then
  set -eu
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
: "${APP_ENV:=development}"
export APP_ENV
python <<'PY'
from backend_fastapi.app.utils.crypto_utils import ensure_encrypted_env_loaded

ensure_encrypted_env_loaded()
PY
python "${SCRIPT_DIR}/wait_for_services.py"
python -m compileall "${SCRIPT_DIR}/../app/models"
"${SCRIPT_DIR}/wait_for_migrations.sh"

: "${APP_HOST:=0.0.0.0}"
: "${APP_PORT:=8000}"

# Without -c gunicorn silently ignores backend_fastapi/deployment/gunicorn.conf.py and runs a
# single worker on the 30s default timeout. Resolve the config relative to the
# repository root so it works both in the container (/app) and from a checkout.
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
: "${GUNICORN_CONF:=${REPO_ROOT}/backend_fastapi/deployment/gunicorn.conf.py}"

if [ ! -f "${GUNICORN_CONF}" ]; then
  echo "start_backend: gunicorn config not found at ${GUNICORN_CONF}" >&2
  exit 1
fi

exec gunicorn \
  -c "${GUNICORN_CONF}" \
  -k uvicorn.workers.UvicornWorker \
  --bind "${APP_HOST}:${APP_PORT}" \
  backend_fastapi.app.main:app
