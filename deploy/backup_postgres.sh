#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BACKUP_DIR=${POSTGRES_BACKUP_DIR:-"${SCRIPT_DIR}/../backups/postgres"}
BACKUP_PREFIX=${POSTGRES_BACKUP_PREFIX:-postgres}
RETENTION_DAYS=${POSTGRES_BACKUP_RETENTION_DAYS:-7}
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
FILENAME="${BACKUP_PREFIX}-${TIMESTAMP}.dump"
BACKUP_PATH="${BACKUP_DIR}/${FILENAME}"

PGHOST=${POSTGRES_HOST:-localhost}
PGPORT=${POSTGRES_PORT:-5432}
PGDATABASE=${POSTGRES_DB:-manga}
PGUSER=${POSTGRES_USER:-postgres}
PGPASSWORD=${POSTGRES_PASSWORD:-}

# 4A.7: backups must be encrypted. Set this to enable it -- the dump is
# never written to disk unencrypted (piped straight through gpg).
ENCRYPTION_PASSPHRASE=${POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE:-}

# 4A.7: regenerable data (OCR/translation caches) can be excluded from the
# dump's row data to keep backups small and fast -- losing them costs
# reprocessing time, not data, so they are not a backup priority. Schema is
# still backed up either way; only row data is skipped. Off by default.
EXCLUDE_REGENERABLE_DATA=${POSTGRES_BACKUP_EXCLUDE_REGENERABLE_DATA:-0}

mkdir -p "${BACKUP_DIR}"

export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "pg_dump command not found. Please install PostgreSQL client tools." >&2
  exit 1
fi

DUMP_ARGS=(--format=custom --no-owner)
if [[ "${EXCLUDE_REGENERABLE_DATA}" == "1" ]]; then
  DUMP_ARGS+=(--exclude-table-data=ocr_cache --exclude-table-data=translation_cache)
fi

if [[ -n "${ENCRYPTION_PASSPHRASE}" ]]; then
  if ! command -v gpg >/dev/null 2>&1; then
    echo "gpg command not found. Please install GnuPG, or unset POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE." >&2
    exit 1
  fi
  BACKUP_PATH="${BACKUP_PATH}.gpg"
  trap 'rm -f "${BACKUP_PATH}"' EXIT
  pg_dump "${DUMP_ARGS[@]}" | gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase-fd 3 --output "${BACKUP_PATH}" 3<<<"${ENCRYPTION_PASSPHRASE}"
  trap - EXIT
else
  echo "WARNING: POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE is not set -- this backup will be written unencrypted (SRS 4A.7 requires encrypted backups)." >&2
  trap 'rm -f "${BACKUP_PATH}"' EXIT
  pg_dump "${DUMP_ARGS[@]}" --file="${BACKUP_PATH}"
  trap - EXIT
fi

if [[ -n "${RETENTION_DAYS}" && "${RETENTION_DAYS}" =~ ^[0-9]+$ && "${RETENTION_DAYS}" -gt 0 ]]; then
  # Delete files older than the configured retention window (both plain and
  # .gpg dumps, in case the encryption setting changed between runs).
  find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}-*.dump*" -mtime +$((RETENTION_DAYS - 1)) -print -delete
fi

echo "PostgreSQL backup created at ${BACKUP_PATH}"
