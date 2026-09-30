#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BACKUP_DIR=${REDIS_BACKUP_DIR:-"${SCRIPT_DIR}/../backups/redis"}
REDIS_DATA_DIR=${REDIS_DATA_DIR:-/var/lib/redis}
REDIS_DUMP_FILENAME=${REDIS_DUMP_FILENAME:-dump.rdb}
REDIS_SERVICE_NAME=${REDIS_SERVICE_NAME:-redis-server}
REDIS_USER=${REDIS_USER:-redis}
REDIS_GROUP=${REDIS_GROUP:-redis}
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "This script must be run as root (or via sudo)." >&2
  exit 1
fi

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

if [[ ! -d "${REDIS_DATA_DIR}" ]]; then
  echo "Redis data directory ${REDIS_DATA_DIR} does not exist." >&2
  exit 1
fi

TARGET_PATH="${REDIS_DATA_DIR}/${REDIS_DUMP_FILENAME}"
BACKUP_COPY="${TARGET_PATH}.${TIMESTAMP}.bak"

cat <<WARNING
About to restore Redis snapshot:
  Source: ${BACKUP_FILE}
  Target dump: ${TARGET_PATH}
  Service: ${REDIS_SERVICE_NAME}
WARNING

read -r -p "This will replace the current Redis dump. Continue? [y/N] " CONFIRM
if [[ ! ${CONFIRM} =~ ^[Yy]$ ]]; then
  echo "Restore cancelled." >&2
  exit 1
fi

read -r -p "Type the word RESTORE to continue: " DOUBLE_CHECK
if [[ "${DOUBLE_CHECK}" != "RESTORE" ]]; then
  echo "Confirmation failed. Restore cancelled." >&2
  exit 1
fi

stop_service() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl stop "${REDIS_SERVICE_NAME}"
  elif command -v service >/dev/null 2>&1; then
    service "${REDIS_SERVICE_NAME}" stop
  else
    echo "Unable to control Redis service automatically. Please stop it manually." >&2
    exit 1
  fi
}

start_service() {
  if command -v systemctl >/dev/null 2>&1; then
    systemctl start "${REDIS_SERVICE_NAME}"
  elif command -v service >/dev/null 2>&1; then
    service "${REDIS_SERVICE_NAME}" start
  else
    echo "Unable to control Redis service automatically. Please start it manually." >&2
    exit 1
  fi
}

stop_service

echo "Backing up existing dump (if present)..."
if [[ -f "${TARGET_PATH}" ]]; then
  cp "${TARGET_PATH}" "${BACKUP_COPY}"
fi

echo "Placing restored dump..."
cp "${BACKUP_FILE}" "${TARGET_PATH}"
chown "${REDIS_USER}:${REDIS_GROUP}" "${TARGET_PATH}" || true
chmod 640 "${TARGET_PATH}" || true

start_service

echo "Redis restore complete. A copy of the previous dump (if any) was saved to ${BACKUP_COPY}."
