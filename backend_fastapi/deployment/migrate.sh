#!/bin/bash
# Run database migrations inside backend container
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

cd "$ROOT_DIR"

LOG_DIR="$ROOT_DIR/backend_fastapi/deployment/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/migrate_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

FAILED_STEP=""
declare -a COMPLETED_STEPS=()

timestamp() {
    date +"%Y-%m-%d %H:%M:%S"
}

step_failed() {
    local exit_code=$?
    FAILED_STEP="$1"
    echo ""
    echo "ERROR: Step '$1' failed with exit code $exit_code." >&2
    echo "Review the log for details: $LOG_FILE" >&2
    echo "If data changes were applied, revert them manually via SQL or your migration tooling." >&2
    echo "If data changes were applied, revert them manually via SQL as needed." >&2
    exit "$exit_code"
}

record_completion() {
    COMPLETED_STEPS+=("$1")
}

execute_step() {
    local step_name="$1"
    shift

    trap "step_failed '$step_name'" ERR

    echo "[$(timestamp)] Starting $step_name..."
    "$@"
    trap - ERR

    echo "[$(timestamp)] Completed $step_name."
    record_completion "$step_name"
}

summarize() {
    local exit_code=$?
    trap - EXIT

    echo ""
    echo "==== Migration Summary ===="
    if [ "$exit_code" -eq 0 ]; then
        echo "Status: success"
    else
        echo "Status: failed"
        if [ -n "$FAILED_STEP" ]; then
            echo "Failed step: $FAILED_STEP"
            echo "Review the log: $LOG_FILE"
            echo "Recommended rollback: revert the migration manually (for example via SQL or your migration tooling)."
        else
            echo "Failure occurred outside tracked steps. Review the log: $LOG_FILE"
        fi
    fi

    if [ "${#COMPLETED_STEPS[@]}" -gt 0 ]; then
        echo "Completed steps:"
        for step in "${COMPLETED_STEPS[@]}"; do
            echo "  - $step"
        done
    else
        echo "No steps completed before exit."
    fi

    echo "Log file: $LOG_FILE"

    exit "$exit_code"
}

trap summarize EXIT
if [ -z "${DATABASE_URL:-}" ]; then
    echo "DATABASE_URL is not set. Export a Postgres DSN before running migrations."
    exit 1
fi

case "$DATABASE_URL" in
    postgresql://*|postgresql+psycopg2://*|postgres://*)
        ;;
    *)
        echo "DATABASE_URL must point to Postgres for production deployments. Current value: $DATABASE_URL"
        exit 1
        ;;
esac

python3 - <<'PY'
import os
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

url = os.environ.get("DATABASE_URL", "")
try:
    safe = make_url(url).render_as_string(hide_password=True)
except (ArgumentError, AttributeError, TypeError):
    safe = "<unparseable>"

print(f"Using DATABASE_URL={safe}")
PY

run_fastapi_migrate() {
    execute_step "FastAPI metadata migration" python3 -m backend_fastapi.app.cli migrate
}

echo "Ensuring database schema via FastAPI CLI..."
run_fastapi_migrate

echo "Database schema ensured."
