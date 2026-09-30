#!/bin/sh
# Renders /config.json from the API_BASE env var at container start so the
# frontend can be repointed at a different backend without a rebuild (the
# build-time REACT_APP_API_BASE bakes into the JS bundle instead).
set -eu

export API_BASE="${API_BASE:-/api/v1}"

envsubst '${API_BASE}' \
  < /etc/nginx/runtime-config/config.json.template \
  > /usr/share/nginx/html/config.json

exec "$@"
