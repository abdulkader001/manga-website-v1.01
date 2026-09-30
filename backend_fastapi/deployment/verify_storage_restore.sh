#!/usr/bin/env bash
# Restore test for the pictures volume: back it up, restore the archive into a
# scratch directory and compare every file (path and SHA-256) with the source.
# Exits non-zero on any difference. Read-only on the live volume.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STORAGE_DIR=${STORAGE_DIR:-/app/storage}
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

STORAGE_BACKUP_DIR="${WORK}/archive" STORAGE_BACKUP_RETENTION_DAYS=0 \
  bash "${SCRIPT_DIR}/backup_storage.sh" >"${WORK}/backup.log"
ARCHIVE=$(ls "${WORK}"/archive/storage-*.tar*)
bash "${SCRIPT_DIR}/restore_storage.sh" "${ARCHIVE}" "${WORK}/restored" >/dev/null

manifest() { (cd "$1" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum); }
manifest "${STORAGE_DIR}" >"${WORK}/source.sha"
manifest "${WORK}/restored" >"${WORK}/restored.sha"

if diff -q "${WORK}/source.sha" "${WORK}/restored.sha" >/dev/null; then
  echo "Pictures restore verified: $(wc -l <"${WORK}/source.sha") files identical."
else
  echo "Pictures restore verification FAILED: restored files differ from the source." >&2
  diff "${WORK}/source.sha" "${WORK}/restored.sha" | head -20 >&2 || true
  exit 1
fi
