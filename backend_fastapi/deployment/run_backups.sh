#!/usr/bin/env bash
# Nightly run: Postgres, Redis and the pictures volume. Every step runs even if
# an earlier one fails, and the script exits non-zero if any did, so the
# systemd unit shows as failed (and alerts) rather than silently skipping.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
failed=0
for step in backup_postgres.sh backup_redis.sh backup_storage.sh; do
  echo "== ${step}"
  bash "${SCRIPT_DIR}/${step}" || { echo "FAILED: ${step}" >&2; failed=1; }
done
exit "${failed}"
