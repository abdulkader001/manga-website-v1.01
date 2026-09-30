#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BACKUP_DIR=${POSTGRES_BACKUP_DIR:-"${SCRIPT_DIR}/../backups/postgres"}

PGHOST=${POSTGRES_HOST:-localhost}
PGPORT=${POSTGRES_PORT:-5432}
PGDATABASE=${POSTGRES_DB:-manga}
PGUSER=${POSTGRES_USER:-postgres}
PGPASSWORD=${POSTGRES_PASSWORD:-}

usage() {
  cat <<USAGE
Usage: $0 <backup-file>

Provide either an absolute path or a filename located in ${BACKUP_DIR}.
Available backups:
$(ls -1 "${BACKUP_DIR}" 2>/dev/null | sed 's/^/  - /')
USAGE
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

CANDIDATE=$1
if [[ -f "${CANDIDATE}" ]]; then
  BACKUP_FILE=$(realpath "${CANDIDATE}")
elif [[ -f "${BACKUP_DIR}/${CANDIDATE}" ]]; then
  BACKUP_FILE=$(realpath "${BACKUP_DIR}/${CANDIDATE}")
else
  echo "Backup file ${CANDIDATE} not found." >&2
  usage >&2
  exit 1
fi

if ! command -v pg_restore >/dev/null 2>&1; then
  echo "pg_restore command not found. Please install PostgreSQL client tools." >&2
  exit 1
fi

export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

RESTORE_FILE="${BACKUP_FILE}"
DECRYPTED_TMP=""
cleanup_decrypted_tmp() {
  if [[ -n "${DECRYPTED_TMP}" && -f "${DECRYPTED_TMP}" ]]; then
    rm -f "${DECRYPTED_TMP}"
  fi
}
trap cleanup_decrypted_tmp EXIT

if [[ "${BACKUP_FILE}" == *.gpg ]]; then
  if ! command -v gpg >/dev/null 2>&1; then
    echo "gpg command not found. Please install GnuPG to restore an encrypted backup." >&2
    exit 1
  fi
  if [[ -z "${POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE:-}" ]]; then
    echo "This backup is encrypted; set POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE to decrypt it." >&2
    exit 1
  fi
  DECRYPTED_TMP=$(mktemp)
  chmod 600 "${DECRYPTED_TMP}"
  echo "Decrypting ${BACKUP_FILE}..."
  gpg --batch --yes --decrypt --passphrase-fd 3 --output "${DECRYPTED_TMP}" \
    "${BACKUP_FILE}" 3<<<"${POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE}"
  RESTORE_FILE="${DECRYPTED_TMP}"
fi

echo "About to restore ${BACKUP_FILE} into database ${PGDATABASE} on ${PGHOST}:${PGPORT} as ${PGUSER}."
read -r -p "This will overwrite the existing database. Continue? [y/N] " CONFIRM
if [[ ! ${CONFIRM} =~ ^[Yy]$ ]]; then
  echo "Restore cancelled." >&2
  exit 1
fi

read -r -p "Type the database name (${PGDATABASE}) to confirm: " DOUBLE_CHECK
if [[ "${DOUBLE_CHECK}" != "${PGDATABASE}" ]]; then
  echo "Database name did not match. Restore cancelled." >&2
  exit 1
fi

TERMINATE_SQL="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();"
if command -v psql >/dev/null 2>&1; then
  echo "Terminating existing connections to ${PGDATABASE}..."
  psql --dbname="${PGDATABASE}" --command "${TERMINATE_SQL}" >/dev/null || true
fi

echo "Restoring backup..."
pg_restore --clean --if-exists --no-owner --exit-on-error --dbname="${PGDATABASE}" "${RESTORE_FILE}"

echo "Restore completed successfully."
