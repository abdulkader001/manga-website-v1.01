#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
SCRIPT_DIR="$ROOT_DIR/backend_fastapi/scripts"

missing=()

for script in start_backend.sh wait_for_migrations.sh; do
  path="$SCRIPT_DIR/$script"
  if [[ ! -x "$path" ]]; then
    missing+=("$path")
  fi
done

if (( ${#missing[@]} == 0 )); then
  echo "All backend scripts are executable."
  exit 0
fi

echo "The following backend scripts are missing the execute bit:" >&2
for path in "${missing[@]}"; do
  echo "  - $path" >&2
  echo "    Fix with: chmod +x \"$path\"" >&2
  echo >&2
fi

exit 1
