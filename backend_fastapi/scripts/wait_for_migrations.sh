#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

: "${DATABASE_URL:?DATABASE_URL environment variable must be set}"

DB_URL="$DATABASE_URL"
DB_URL=${DB_URL/postgresql+psycopg2/postgresql}
export DB_URL

python - <<'PY'
import os
import sys
import time

import psycopg2
from alembic.config import Config
from alembic.script import ScriptDirectory

base_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(base_dir, ".."))
# Enumerating revisions imports every migration module, some of which import
# ``backend_fastapi.app.*`` at module load time. Unlike ``alembic upgrade`` (which
# runs env.py) this direct ScriptDirectory usage never puts the project root on
# sys.path, so add it here to keep the top-level package importable.
if project_root not in sys.path:
    sys.path.insert(0, project_root)
alembic_cfg = Config(os.path.join(project_root, "alembic.ini"))
script = ScriptDirectory.from_config(alembic_cfg)
head_revision = script.get_current_head()

raw_url = os.environ["DB_URL"]

print(f"[wait_for_migrations] Expected head revision: {head_revision}")

while True:
    try:
        with psycopg2.connect(raw_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version_num FROM alembic_version")
                row = cur.fetchone()
                current_revision = row[0] if row else None
    except psycopg2.errors.UndefinedTable:
        current_revision = None
    except Exception as exc:
        print(f"[wait_for_migrations] Waiting for database availability: {exc}")
        time.sleep(2)
        continue

    if current_revision == head_revision:
        print("[wait_for_migrations] Database schema is up to date.")
        break

    print(
        f"[wait_for_migrations] Current revision '{current_revision}' does not match head. "
        "Retrying in 2 seconds..."
    )
    time.sleep(2)
PY
