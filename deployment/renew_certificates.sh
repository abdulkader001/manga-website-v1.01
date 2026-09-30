#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="/var/log/manga/renew.log"
NGINX_WAS_ACTIVE=false

log() {
  local timestamp
  timestamp="$(date -Iseconds)"
  echo "[${timestamp}] $*"
}

rotate_log_dir() {
  local log_dir
  log_dir="$(dirname "${LOG_FILE}")"
  if [[ ! -d "${log_dir}" ]]; then
    mkdir -p "${log_dir}"
  fi
  if [[ ! -f "${LOG_FILE}" ]]; then
    touch "${LOG_FILE}"
  fi
}

stop_nginx_if_running() {
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet nginx; then
      log "Stopping nginx via systemctl"
      systemctl stop nginx
      NGINX_WAS_ACTIVE=true
    else
      log "nginx is not active; no stop required"
    fi
  elif command -v service >/dev/null 2>&1; then
    if service nginx status >/dev/null 2>&1; then
      log "Stopping nginx via service"
      service nginx stop
      NGINX_WAS_ACTIVE=true
    else
      log "nginx service not reported active; no stop required"
    fi
  else
    log "Warning: Unable to locate systemctl or service; skipping nginx stop"
  fi
}

start_and_reload_nginx() {
  if command -v systemctl >/dev/null 2>&1; then
    if [[ "${NGINX_WAS_ACTIVE}" == true ]]; then
      log "Starting nginx via systemctl"
      systemctl start nginx
    fi
    log "Reloading nginx via systemctl"
    if ! systemctl reload nginx; then
      log "systemctl reload nginx failed; attempting restart"
      systemctl restart nginx
    fi
  elif command -v service >/dev/null 2>&1; then
    if [[ "${NGINX_WAS_ACTIVE}" == true ]]; then
      log "Starting nginx via service"
      service nginx start
    fi
    log "Reloading nginx via service"
    if ! service nginx reload; then
      log "service nginx reload failed; attempting restart"
      service nginx restart
    fi
  else
    log "Warning: Unable to locate systemctl or service; nginx reload skipped"
  fi
}

renew_certificates() {
  if ! command -v certbot >/dev/null 2>&1; then
    log "Error: certbot command not found"
    exit 1
  fi
  log "Running certbot renew"
  certbot renew --quiet
  log "certbot renew completed"
}

main() {
  rotate_log_dir
  exec >>"${LOG_FILE}" 2>&1

  log "==== Starting certificate renewal run ===="
  stop_nginx_if_running
  renew_certificates
  start_and_reload_nginx
  log "==== Certificate renewal run complete ===="
}

main "$@"
