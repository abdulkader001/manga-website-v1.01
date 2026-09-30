#!/usr/bin/env bash
# Back up the pictures volume (compressed chapter pages and covers).
#
# The pictures are WebP files, already compressed, so the archive is a plain
# tar (gzip would cost CPU for almost no saving). Optional symmetric
# encryption mirrors backup_postgres.sh.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STORAGE_DIR=${STORAGE_DIR:-/app/storage}
BACKUP_DIR=${STORAGE_BACKUP_DIR:-"${SCRIPT_DIR}/../backups/storage"}
BACKUP_PREFIX=${STORAGE_BACKUP_PREFIX:-storage}
RETENTION_DAYS=${STORAGE_BACKUP_RETENTION_DAYS:-7}
ENCRYPTION_PASSPHRASE=${STORAGE_BACKUP_ENCRYPTION_PASSPHRASE:-${POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE:-}}
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_PREFIX}-${TIMESTAMP}.tar"

if [[ ! -d "${STORAGE_DIR}" ]]; then
  echo "Storage directory ${STORAGE_DIR} does not exist (set STORAGE_DIR)." >&2
  exit 1
fi
mkdir -p "${BACKUP_DIR}"

if [[ -n "${ENCRYPTION_PASSPHRASE}" ]]; then
  command -v gpg >/dev/null 2>&1 || { echo "gpg not found; install GnuPG or unset the passphrase." >&2; exit 1; }
  BACKUP_PATH="${BACKUP_PATH}.gpg"
  trap 'rm -f "${BACKUP_PATH}"' EXIT
  tar -C "${STORAGE_DIR}" -cf - . | gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase-fd 3 --output "${BACKUP_PATH}" 3<<<"${ENCRYPTION_PASSPHRASE}"
  trap - EXIT
else
  echo "WARNING: no encryption passphrase set -- this pictures backup is written unencrypted." >&2
  trap 'rm -f "${BACKUP_PATH}"' EXIT
  tar -C "${STORAGE_DIR}" -cf "${BACKUP_PATH}" .
  trap - EXIT
fi

if [[ "${RETENTION_DAYS}" =~ ^[0-9]+$ && "${RETENTION_DAYS}" -gt 0 ]]; then
  find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}-*.tar*" -mtime +$((RETENTION_DAYS - 1)) -print -delete
fi

echo "Pictures backup created at ${BACKUP_PATH}"
