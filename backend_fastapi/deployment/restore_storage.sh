#!/usr/bin/env bash
# Restore a pictures backup made by backup_storage.sh into a directory.
#
#   restore_storage.sh <archive> [target-dir]
#
# The target (default STORAGE_DIR, else /app/storage) must be empty unless
# STORAGE_RESTORE_FORCE=1, in which case files are extracted over it. Stop the
# API and workers first when restoring onto the live volume.
set -euo pipefail

ARCHIVE=${1:-}
TARGET=${2:-${STORAGE_DIR:-/app/storage}}
BACKUP_DIR=${STORAGE_BACKUP_DIR:-}
ENCRYPTION_PASSPHRASE=${STORAGE_BACKUP_ENCRYPTION_PASSPHRASE:-${POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE:-}}

[[ -n "${ARCHIVE}" ]] || { echo "usage: $0 <archive> [target-dir]" >&2; exit 2; }
if [[ ! -f "${ARCHIVE}" && -n "${BACKUP_DIR}" && -f "${BACKUP_DIR}/${ARCHIVE}" ]]; then
  ARCHIVE="${BACKUP_DIR}/${ARCHIVE}"
fi
[[ -f "${ARCHIVE}" ]] || { echo "Archive not found: ${ARCHIVE}" >&2; exit 1; }

mkdir -p "${TARGET}"
if [[ -n "$(ls -A "${TARGET}")" && "${STORAGE_RESTORE_FORCE:-0}" != "1" ]]; then
  echo "${TARGET} is not empty. Empty it, pick another directory, or set STORAGE_RESTORE_FORCE=1." >&2
  exit 1
fi

if [[ "${ARCHIVE}" == *.gpg ]]; then
  [[ -n "${ENCRYPTION_PASSPHRASE}" ]] || { echo "Archive is encrypted: set STORAGE_BACKUP_ENCRYPTION_PASSPHRASE." >&2; exit 1; }
  gpg --batch --quiet --decrypt --passphrase-fd 3 "${ARCHIVE}" 3<<<"${ENCRYPTION_PASSPHRASE}" | tar -C "${TARGET}" -xf -
else
  tar -C "${TARGET}" -xf "${ARCHIVE}"
fi

echo "Restored ${ARCHIVE} into ${TARGET}"
