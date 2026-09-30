#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BACKUP_DIR=${REDIS_BACKUP_DIR:-"${SCRIPT_DIR}/../backups/redis"}
BACKUP_PREFIX=${REDIS_BACKUP_PREFIX:-redis}
RETENTION_DAYS=${REDIS_BACKUP_RETENTION_DAYS:-7}
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
FILENAME="${BACKUP_PREFIX}-${TIMESTAMP}.rdb"
BACKUP_PATH="${BACKUP_DIR}/${FILENAME}"
TMP_PATH="${BACKUP_PATH}.tmp"

REDIS_CLI=${REDIS_CLI:-redis-cli}
REDIS_HOST=${REDIS_HOST:-localhost}
REDIS_PORT=${REDIS_PORT:-6379}
REDIS_DB=${REDIS_DB:-0}
REDIS_PASSWORD=${REDIS_PASSWORD:-}
REDIS_SOCKET=${REDIS_SOCKET:-}

if ! command -v "${REDIS_CLI}" >/dev/null 2>&1; then
  echo "${REDIS_CLI} command not found. Please install redis-tools." >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

CLI_ARGS=()
if [[ -n "${REDIS_SOCKET}" ]]; then
  CLI_ARGS=(-s "${REDIS_SOCKET}")
else
  CLI_ARGS=(-h "${REDIS_HOST}" -p "${REDIS_PORT}")
fi
CLI_ARGS+=(-n "${REDIS_DB}" --rdb "${TMP_PATH}")

if [[ -n "${REDIS_PASSWORD}" ]]; then
  export REDISCLI_AUTH="${REDIS_PASSWORD}"
fi

trap 'rm -f "${TMP_PATH}"' EXIT

# Produce an RDB snapshot directly from redis-cli. The command blocks until the dump is ready.
"${REDIS_CLI}" "${CLI_ARGS[@]}"

if [[ -n "${REDIS_PASSWORD}" ]]; then
  unset REDISCLI_AUTH
fi

mv "${TMP_PATH}" "${BACKUP_PATH}"
trap - EXIT

if [[ -n "${RETENTION_DAYS}" && "${RETENTION_DAYS}" =~ ^[0-9]+$ && "${RETENTION_DAYS}" -gt 0 ]]; then
  find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${BACKUP_PREFIX}-*.rdb" -mtime +$((RETENTION_DAYS - 1)) -print -delete
fi

echo "Redis backup created at ${BACKUP_PATH}"
