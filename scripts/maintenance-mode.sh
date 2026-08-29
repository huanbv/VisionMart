#!/usr/bin/env bash
# VisionMart -- Enable maintenance mode (DevOps Toolkit Part 10).
#
# Swaps nginx's active vhost for a static "under maintenance" page and
# reloads nginx (never restarts it, never touches any other container).
# Internal services (backend, celery-worker/beat, postgres, redis,
# minio, ai-engine, monitoring) keep running exactly as before -- this
# only changes what external visitors see at the reverse proxy. See
# docker/nginx/conf.d/maintenance.conf.disabled for the template and
# scripts/exit-maintenance.sh for the reverse operation.
#
# Usage: scripts/maintenance-mode.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
      exit "${EXIT_OK}"
      ;;
  esac
done

init_logging "$0"

CONF_DIR="${VISIONMART_APP_DIR}/docker/nginx/conf.d"
ACTIVE="${CONF_DIR}/default.conf"
DISABLED="${CONF_DIR}/default.conf.disabled"
MAINT_TEMPLATE="${CONF_DIR}/maintenance.conf.disabled"
MAINT_ACTIVE="${CONF_DIR}/maintenance.conf"

require_file "${MAINT_TEMPLATE}"

if [ -f "${MAINT_ACTIVE}" ]; then
  ok "Maintenance mode is already enabled (${MAINT_ACTIVE} exists) -- nothing to do."
  exit "${EXIT_OK}"
fi

if [ ! -f "${ACTIVE}" ]; then
  die "Expected active config not found at ${ACTIVE} -- refusing to guess. Check ${CONF_DIR} manually." "${EXIT_GENERAL_ERROR}"
fi

log "Enabling maintenance mode"
mv "${ACTIVE}" "${DISABLED}"
cp "${MAINT_TEMPLATE}" "${MAINT_ACTIVE}"
ok "Swapped in maintenance.conf, moved default.conf aside as default.conf.disabled"

log "Validating nginx configuration"
NGINX_TEST_LOG="$(mktemp)"
if ! dc exec -T nginx nginx -t >"${NGINX_TEST_LOG}" 2>&1; then
  error "nginx -t failed against the maintenance config -- rolling back:"
  sed 's/^/  /' "${NGINX_TEST_LOG}" >&2
  rm -f "${MAINT_ACTIVE}" "${NGINX_TEST_LOG}"
  mv "${DISABLED}" "${ACTIVE}"
  die "Rolled back -- site is unaffected." "${EXIT_VALIDATION_FAILED}"
fi
rm -f "${NGINX_TEST_LOG}"

log "Reloading nginx (graceful -- no downtime for in-flight connections)"
if ! dc exec -T nginx nginx -s reload; then
  warn "nginx -s reload failed -- container may not be running. Try: docker compose up -d nginx"
fi

ok "Maintenance mode ENABLED. Visitors now see the maintenance page; internal services are untouched."
info "Disable with: scripts/exit-maintenance.sh"
