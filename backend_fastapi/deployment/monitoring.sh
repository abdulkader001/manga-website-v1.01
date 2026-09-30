#!/bin/bash
# =========================================
# Manga Website Health Monitor
# =========================================
# - Polls /api/health endpoint
# - Verifies sshd and fail2ban are running
# - Restarts docker compose if unhealthy
# - Logs everything to /var/log/manga/monitor.log
# =========================================

set -euo pipefail

API_URL=${API_URL:-"http://localhost/api/health"}
LOGFILE=${LOGFILE:-"/var/log/manga/monitor.log"}
COMPOSE_DIR=${COMPOSE_DIR:-"/var/www/manga"}

CURL_OPTIONS=${MONITOR_CURL_OPTIONS:-${CURL_OPTIONS:-""}}

MONITOR_REDIS_URL=${MONITOR_REDIS_URL:-""}
if [ -n "$MONITOR_REDIS_URL" ]; then
  REDIS_URL="$MONITOR_REDIS_URL"
elif [ -n "${REDIS_URL:-}" ]; then
  REDIS_URL="$REDIS_URL"
elif [ -n "${REDIS_PASSWORD:-}" ]; then
  REDIS_USER=${REDIS_USERNAME:-default}
  REDIS_URL="redis://${REDIS_USER}:${REDIS_PASSWORD}@redis:6379/0"
else
  REDIS_URL="redis://redis:6379/0"
fi
QUEUE_NAME=${MONITOR_QUEUE_NAME:-"celery"}
QUEUE_WARN_THRESHOLD=${MONITOR_QUEUE_WARN_THRESHOLD:-100}
QUEUE_ALERT_THRESHOLD=${MONITOR_QUEUE_ALERT_THRESHOLD:-500}
UPTIME_FILE=${UPTIME_FILE:-"/var/log/manga/uptime-success.count"}

timestamp(){ date +"%Y-%m-%d %H:%M:%S"; }
log(){ echo "$(timestamp) $*" >> "$LOGFILE"; }

check_sshd() {
  systemctl is-active --quiet ssh || systemctl is-active --quiet sshd
}

check_fail2ban() {
  systemctl is-active --quiet fail2ban
}

mkdir -p "$(dirname "$LOGFILE")"
mkdir -p "$(dirname "$UPTIME_FILE")"

log "🔍 Running health check..."

API_OK=0
SHOULD_RESTART=0
HEALTH_RESPONSE=""
API_STATUS=""

# shellcheck disable=SC2086  # intentional splitting of CURL_OPTIONS
if HEALTH_RESPONSE=$(curl -fsS --max-time 5 $CURL_OPTIONS "$API_URL" 2>>"$LOGFILE"); then
  API_STATUS=$(python3 -c 'import json, sys
payload = sys.argv[1]
try:
    data = json.loads(payload)
except Exception:
    sys.exit(1)
print(str(data.get("status", "")).lower())' "$HEALTH_RESPONSE" 2>/dev/null || echo "")
  case "$API_STATUS" in
    ok)
      API_OK=1
      log "✅ API healthy (status: ok)."
      ;;
    degraded)
      API_OK=1
      log "⚠️ API degraded (status: degraded)."
      ;;
    down|error)
      log "❌ API unhealthy (status: $API_STATUS)."
      SHOULD_RESTART=1
      ;;
    *)
      log "⚠️ API returned unexpected status '$API_STATUS'."
      ;;
  esac
else
  CURL_EXIT=$?
  log "❌ API request failed (exit $CURL_EXIT)."
  SHOULD_RESTART=1
fi

if [ "$API_OK" -eq 1 ]; then
  CURRENT_UPTIME=0
  if [ -f "$UPTIME_FILE" ]; then
    read -r CURRENT_UPTIME < "$UPTIME_FILE" || CURRENT_UPTIME=0
  fi
  if ! [[ "$CURRENT_UPTIME" =~ ^[0-9]+$ ]]; then
    CURRENT_UPTIME=0
  fi
  CURRENT_UPTIME=$((CURRENT_UPTIME + 1))
  echo "$CURRENT_UPTIME" > "$UPTIME_FILE"
  log "📈 Uptime success count: $CURRENT_UPTIME (status: $API_STATUS)."
else
  echo "0" > "$UPTIME_FILE"
  log "📉 Uptime success count reset."
fi

QUEUE_DEPTH=""
if command -v redis-cli >/dev/null 2>&1; then
  if QUEUE_DEPTH=$(redis-cli -u "$REDIS_URL" LLEN "$QUEUE_NAME" 2>>"$LOGFILE"); then
    if [[ "$QUEUE_DEPTH" =~ ^[0-9]+$ ]]; then
      if [ "$QUEUE_DEPTH" -ge "$QUEUE_ALERT_THRESHOLD" ]; then
        log "❌ Redis queue '$QUEUE_NAME' depth critical: $QUEUE_DEPTH (alert ≥ $QUEUE_ALERT_THRESHOLD)."
      elif [ "$QUEUE_DEPTH" -ge "$QUEUE_WARN_THRESHOLD" ]; then
        log "⚠️ Redis queue '$QUEUE_NAME' depth high: $QUEUE_DEPTH (warn ≥ $QUEUE_WARN_THRESHOLD)."
      else
        log "✅ Redis queue '$QUEUE_NAME' depth healthy: $QUEUE_DEPTH."
      fi
    else
      log "⚠️ Unable to parse Redis queue depth from '$QUEUE_DEPTH'."
    fi
  else
    log "⚠️ Failed to query Redis queue depth."
  fi
else
  log "⚠️ redis-cli not installed; skipping queue depth check."
fi

if [ "$SHOULD_RESTART" -eq 1 ]; then
  log "❌ API unhealthy. Restarting stack..."
  /usr/bin/docker compose down >> "$LOGFILE" 2>&1
  /usr/bin/docker compose up -d >> "$LOGFILE" 2>&1
  log "🔄 Stack restarted."
else
  log "✅ No restart required."
fi

if ! check_sshd; then
  log "❌ SSHD inactive! Attempting restart..."
  if ! (systemctl restart ssh || systemctl restart sshd); then
    log "⚠️ SSHD restart failed"
  else
    log "✅ SSHD restarted."
  fi
else
  log "✅ SSHD active."
fi

if [ "$F2B_OK" -ne 1 ]; then
  if ! check_fail2ban; then
  log "❌ fail2ban inactive! Attempting restart..."
  if ! systemctl restart fail2ban; then
    log "⚠️ fail2ban restart failed"
  else
    log "✅ fail2ban active."
  fi
else
  echo "$(timestamp) ✅ fail2ban active." >> "$LOGFILE"
fi
