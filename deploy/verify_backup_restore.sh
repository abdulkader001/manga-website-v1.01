#!/usr/bin/env bash
# Automated restore verification (SRS 4A.7): "backups tested by actual
# restore, not by the absence of errors." Dumps the live database, restores
# that dump into a disposable scratch database, and compares the table list
# and row counts against the source -- a pg_dump/pg_restore that both exit 0
# is not proof the data actually round-trips; this checks that it did.
#
# Intended to run on a schedule (e.g. after the nightly backup) against a
# staging/replica instance, not the production primary, since it performs a
# full dump of whatever ${POSTGRES_DB} points at.
set -euo pipefail

PGHOST=${POSTGRES_HOST:-localhost}
PGPORT=${POSTGRES_PORT:-5432}
PGDATABASE=${POSTGRES_DB:-manga}
PGUSER=${POSTGRES_USER:-postgres}
PGPASSWORD=${POSTGRES_PASSWORD:-}
SCRATCH_DB=${POSTGRES_RESTORE_VERIFY_DB:-"${PGDATABASE}_restore_verify"}
ENCRYPTION_PASSPHRASE=${POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE:-}

export PGHOST PGPORT PGUSER PGPASSWORD

if [[ "${SCRATCH_DB}" == "${PGDATABASE}" ]]; then
  echo "POSTGRES_RESTORE_VERIFY_DB must differ from POSTGRES_DB (refusing to restore over the source)." >&2
  exit 1
fi

for cmd in pg_dump pg_restore psql createdb dropdb; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "${cmd} not found. Please install PostgreSQL client tools." >&2
    exit 1
  fi
done

WORKDIR=$(mktemp -d)
cleanup() {
  dropdb --if-exists "${SCRATCH_DB}" >/dev/null 2>&1 || true
  rm -rf "${WORKDIR}"
}
trap cleanup EXIT

DUMP_PATH="${WORKDIR}/verify.dump"

echo "Dumping ${PGDATABASE}..."
if [[ -n "${ENCRYPTION_PASSPHRASE}" ]]; then
  if ! command -v gpg >/dev/null 2>&1; then
    echo "gpg not found. Please install GnuPG, or unset POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE." >&2
    exit 1
  fi
  # Round-trips through encryption too, so this verifies the exact path
  # backup_postgres.sh/restore_postgres.sh take in production.
  pg_dump --dbname="${PGDATABASE}" --format=custom --no-owner \
    | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-fd 3 \
      --output "${DUMP_PATH}.gpg" 3<<<"${ENCRYPTION_PASSPHRASE}"
  gpg --batch --yes --decrypt --passphrase-fd 3 --output "${DUMP_PATH}" \
    "${DUMP_PATH}.gpg" 3<<<"${ENCRYPTION_PASSPHRASE}"
else
  pg_dump --dbname="${PGDATABASE}" --format=custom --no-owner --file="${DUMP_PATH}"
fi

echo "Creating scratch database ${SCRATCH_DB}..."
dropdb --if-exists "${SCRATCH_DB}"
createdb "${SCRATCH_DB}"

echo "Restoring into ${SCRATCH_DB}..."
pg_restore --no-owner --exit-on-error --dbname="${SCRATCH_DB}" "${DUMP_PATH}"

echo "Comparing table row counts between ${PGDATABASE} and ${SCRATCH_DB}..."
LIST_TABLES_SQL="select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by 1;"

SOURCE_TABLES=$(psql --dbname="${PGDATABASE}" -Atc "${LIST_TABLES_SQL}")
SCRATCH_TABLES=$(psql --dbname="${SCRATCH_DB}" -Atc "${LIST_TABLES_SQL}")

if [[ "${SOURCE_TABLES}" != "${SCRATCH_TABLES}" ]]; then
  echo "FAIL: table list differs between source and restored database." >&2
  diff <(echo "${SOURCE_TABLES}") <(echo "${SCRATCH_TABLES}") >&2 || true
  exit 1
fi

MISMATCHES=0
TABLE_COUNT=0
while IFS= read -r table; do
  [[ -z "${table}" ]] && continue
  TABLE_COUNT=$((TABLE_COUNT + 1))
  # Table names here come from information_schema on our own database, not
  # user input, so this is schema introspection, not an injection surface.
  source_count=$(psql --dbname="${PGDATABASE}" -Atc "select count(*) from \"${table}\"")
  scratch_count=$(psql --dbname="${SCRATCH_DB}" -Atc "select count(*) from \"${table}\"")
  if [[ "${source_count}" != "${scratch_count}" ]]; then
    echo "FAIL: ${table} has ${source_count} rows in source but ${scratch_count} in the restore." >&2
    MISMATCHES=$((MISMATCHES + 1))
  fi
done <<<"${SOURCE_TABLES}"

if [[ "${MISMATCHES}" -gt 0 ]]; then
  echo "Restore verification FAILED: ${MISMATCHES} of ${TABLE_COUNT} table(s) mismatched." >&2
  exit 1
fi

echo "Restore verification passed: ${TABLE_COUNT} tables match row-for-row."
