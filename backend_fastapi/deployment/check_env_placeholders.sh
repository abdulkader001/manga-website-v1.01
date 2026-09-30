#!/usr/bin/env bash
set -euo pipefail

REQUIRED_VARS=(
  POSTGRES_USER
  POSTGRES_PASSWORD
  DATABASE_URL
  SECRET_KEY
  JWT_SECRET_KEY
  MAGIC_LINK_SECRET
)

failed=false

for var in "${REQUIRED_VARS[@]}"; do
  value="${!var-}"
  if [[ -z "${value}" ]]; then
    echo "[env-check] Missing required environment variable: ${var}" >&2
    failed=true
    continue
  fi

  if [[ "${value}" == *"<"* || "${value}" == *">"* ]]; then
    echo "[env-check] ${var} still contains template placeholder characters (< or >)." >&2
    failed=true
  fi

done

if [[ "${failed}" == "true" ]]; then
  echo "[env-check] Resolve the environment variables listed above before starting the stack." >&2
  exit 1
fi

echo "[env-check] All required environment variables are set with non-placeholder values."
