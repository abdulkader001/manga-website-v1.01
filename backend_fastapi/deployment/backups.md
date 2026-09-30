# Database and Cache Backups

The `deploy` folder now includes helper scripts for capturing and restoring
PostgreSQL and Redis snapshots. They share a few guiding principles:

* Backups are written to timestamped files (defaulting to `backups/<service>`
  relative to the repository) so you can keep multiple versions side-by-side.
* Destinations and retention periods are controlled through environment
  variables, enabling different policies per environment (production vs.
  staging, etc.).
* Restore scripts include interactive confirmations to avoid accidental data
  loss, and attempt to safely stop and start the relevant services.

> **Note**: Always test your backup and restore process in a staging
> environment before relying on it for production. `backend_fastapi/deployment/verify_backup_restore.sh`
> (below) automates exactly that test.

## PostgreSQL

### Backups

Run `backend_fastapi/deployment/backup_postgres.sh` to create a compressed custom-format dump using
`pg_dump`. The script honours the following environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| `POSTGRES_BACKUP_DIR` | Directory where dumps are stored. | `backups/postgres` (relative to repo) |
| `POSTGRES_BACKUP_PREFIX` | Filename prefix for dumps. | `postgres` |
| `POSTGRES_BACKUP_RETENTION_DAYS` | Delete dumps older than this many days. Set to `0` to disable. | `7` |
| `POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE` | Symmetric passphrase (SRS 4A.7 requires encrypted backups). When set, the dump is piped straight through `gpg --symmetric --cipher-algo AES256` and never touches disk unencrypted; the output filename gets a `.gpg` suffix. **Set this in every real environment** — left unset only for local/throwaway use, and the script prints a loud warning if it is. | *(unset — unencrypted, with a warning)* |
| `POSTGRES_BACKUP_EXCLUDE_REGENERABLE_DATA` | Set to `1` to skip the *row data* of `ocr_cache`/`translation_cache` (schema is still backed up). These caches regenerate from source images on demand, so losing them costs reprocessing time, not data (SRS 4A.7) — worth excluding once they're large enough to matter for backup size/time. Off by default. | `0` |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Connection details passed to `pg_dump`. | `localhost`, `5432`, `manga`, `postgres`, *(empty)* |

Example:

```bash
POSTGRES_BACKUP_DIR=/var/backups/manga \
POSTGRES_BACKUP_RETENTION_DAYS=14 \
POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE="$(pass show prod/manga/backup-passphrase)" \
POSTGRES_HOST=db.internal \
POSTGRES_USER=manga_app \
POSTGRES_PASSWORD="$(pass show prod/manga/db-password)" \
./backend_fastapi/deployment/backup_postgres.sh
```

The passphrase must be stored in the same secret store as the database
credentials (1H.2/1H.3) — never in the crontab, a script, or source control.

### Restores

`backend_fastapi/deployment/restore_postgres.sh` takes the path (or filename inside the backup
folder) of the dump to restore. It terminates active connections, then invokes
`pg_restore --clean` to rebuild the database. You will be prompted twice before
anything destructive happens. If the filename ends in `.gpg` it is decrypted
first (`POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE` must be set to the same
passphrase used at backup time) into a `chmod 600` temp file that is removed
on exit, decrypted or not.

```
sudo -u postgres POSTGRES_DB=manga \
  POSTGRES_BACKUP_DIR=/var/backups/manga \
  POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE="$(pass show prod/manga/backup-passphrase)" \
  ./backend_fastapi/deployment/restore_postgres.sh postgres-20240101-030000.dump.gpg
```

### Restore verification — tested by actual restore, not by the absence of errors

`pg_dump`/`pg_restore` both exiting `0` is not proof a backup is usable — SRS
4A.7 requires backups to be verified by an actual restore. `backend_fastapi/deployment/verify_backup_restore.sh`
automates that: it dumps `POSTGRES_DB` (round-tripping through encryption too,
if `POSTGRES_BACKUP_ENCRYPTION_PASSPHRASE` is set, so it exercises the exact
path production restores take), restores into a disposable scratch database
(`POSTGRES_RESTORE_VERIFY_DB`, defaulting to `<db>_restore_verify`), compares
the table list and row counts against the source table-for-table, and exits
non-zero on any mismatch. Run it against a staging replica (never the
production primary — it performs a full dump of whatever `POSTGRES_DB` points
at) on the same schedule as backups themselves, e.g. immediately after the
nightly `backup_postgres.sh` cron job:

```bash
POSTGRES_HOST=staging-replica.internal \
POSTGRES_DB=manga \
POSTGRES_USER=manga_app \
POSTGRES_PASSWORD="$(pass show staging/manga/db-password)" \
./backend_fastapi/deployment/verify_backup_restore.sh
```

### Point-in-time recovery and RPO/RTO (D17 — needs the platform owner's sign-off)

The scripts above are a full logical snapshot (`pg_dump`), taken on whatever
schedule you cron them — that alone gives an RPO (Recovery Point Objective,
the maximum acceptable data loss) equal to the gap between backups, e.g. 24h
for a nightly job. **If the platform owner needs a tighter RPO** (minutes,
not a day), a nightly logical dump isn't the right tool — continuous
point-in-time recovery (PITR) is, and hand-rolling WAL archiving is exactly
the kind of novel-when-a-conventional-answer-exists approach 4.0 says to
avoid. The boring, conventional choice is a **managed Postgres service**
(RDS, Cloud SQL, Azure Database for PostgreSQL, etc.) with its built-in
automated-backups-plus-PITR feature turned on — this is a checkbox in every
major provider's console, not infrastructure to build and operate by hand.
`backend_fastapi/deployment/backup_postgres.sh`/`restore_postgres.sh` remain useful as an
environment-portable fallback and for the encrypted-offsite-copy requirement
below regardless of which path is chosen.

Recommended defaults, pending the platform owner's actual sign-off:

| | Recommended default | Rationale |
|---|---|---|
| RPO | ≤ 24h (nightly logical backup); ≤ 5 min if PITR is enabled | Matches the cron cadence above; tighten only if the owner decides the data is worth the added operational complexity of PITR |
| RTO | ≤ 4h | Time to provision a replacement database and run `restore_postgres.sh` (or a managed-service point-in-time restore) against it, tested via a rehearsal, not assumed |

Whatever numbers the owner picks, they belong in an incident-response
database-failover runbook as the numbers on-call staff
are held to — not just in this file.

## Redis

### Backups

`backend_fastapi/deployment/backup_redis.sh` uses `redis-cli --rdb` to capture the dataset. The
command blocks until Redis produces the snapshot, making it easy to integrate
with cron or other automation.

| Variable | Purpose | Default |
|----------|---------|---------|
| `REDIS_BACKUP_DIR` | Directory where `.rdb` snapshots are stored. | `backups/redis` (relative to repo) |
| `REDIS_BACKUP_PREFIX` | Filename prefix for backups. | `redis` |
| `REDIS_BACKUP_RETENTION_DAYS` | Delete snapshots older than this many days. Set to `0` to disable. | `7` |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD`, `REDIS_SOCKET` | Connection options forwarded to `redis-cli`. | `localhost`, `6379`, `0`, *(empty)*, *(disabled)* |
| `REDIS_CLI` | Path to the `redis-cli` binary. | `redis-cli` |

Example:

```bash
REDIS_BACKUP_DIR=/var/backups/manga \
REDIS_BACKUP_RETENTION_DAYS=3 \
REDIS_PASSWORD="$(pass show prod/manga/redis-password)" \
./backend_fastapi/deployment/backup_redis.sh
```

### Restores

`backend_fastapi/deployment/restore_redis.sh` replaces the Redis dump file (`dump.rdb` by default)
with a chosen backup and restarts the Redis service. The script must run as
root (or via `sudo`) so it can stop the service and write to the data
directory.

```
sudo REDIS_DATA_DIR=/var/lib/redis \
  REDIS_BACKUP_DIR=/var/backups/manga \
  REDIS_SERVICE_NAME=redis \
  ./backend_fastapi/deployment/restore_redis.sh redis-20240101-030000.rdb
```

A copy of the existing dump is preserved alongside the target file with a
`.bak` suffix and timestamp in case you need to roll back.

## Sample cron entry

Schedule nightly backups at 03:00 with a single cron entry that runs both
scripts and logs output:

```
0 3 * * * POSTGRES_BACKUP_DIR=/var/backups/manga POSTGRES_BACKUP_RETENTION_DAYS=14 REDIS_BACKUP_DIR=/var/backups/manga REDIS_BACKUP_RETENTION_DAYS=7 /opt/manga/backend_fastapi/deployment/backup_postgres.sh >> /var/log/manga/postgres_backup.log 2>&1 && REDIS_BACKUP_DIR=/var/backups/manga REDIS_BACKUP_RETENTION_DAYS=7 /opt/manga/backend_fastapi/deployment/backup_redis.sh >> /var/log/manga/redis_backup.log 2>&1
```

Adjust paths, retention, and logging to suit your environment. Consider
separating the jobs or staggering their run times if both services live on the
same host to reduce load.

Add a weekly restore-verification run against staging so backups are tested
by actual restore on a recurring basis, not just once at setup time:

```
0 4 * * 0 POSTGRES_HOST=staging-replica.internal POSTGRES_DB=manga POSTGRES_USER=manga_app POSTGRES_PASSWORD="$(cat /etc/manga/staging-db-password)" /opt/manga/backend_fastapi/deployment/verify_backup_restore.sh >> /var/log/manga/restore_verify.log 2>&1
```

Alert if this job's exit code is non-zero — a failing restore-verification
run means the backups being taken right now are not actually restorable, the
exact failure mode this check exists to catch before it's discovered during
a real incident.
