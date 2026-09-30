#!/usr/bin/env bash
set -e

echo "🔍 Running pre-flight checks..."
pytest -q || exit 1
alembic check || exit 1
docker compose ps || exit 1
echo "✅ All checks passed."
