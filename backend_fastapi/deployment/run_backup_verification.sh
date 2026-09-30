#!/usr/bin/env bash
# Weekly restore test: database restore into a scratch database, pictures
# restore into a scratch directory. Exits non-zero if either comparison fails.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
failed=0
for step in verify_backup_restore.sh verify_storage_restore.sh; do
  echo "== ${step}"
  bash "${SCRIPT_DIR}/${step}" || { echo "FAILED: ${step}" >&2; failed=1; }
done
exit "${failed}"
