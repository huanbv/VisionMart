#!/usr/bin/env bash
# VisionMart -- Disable maintenance mode (DevOps Toolkit Part 10).
#
# Reverses scripts/maintenance-mode.sh: restores the real default.conf
# and reloads nginx. See that script's header for the full design notes.
#
# Usage: scripts/exit-maintenance.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit "${EXIT_OK}"
      ;;
  esac
done

init_logging "$0"

CONF_DIR="${VISIONMART_APP_DIR}/docker/nginx/conf.d"
ACTIVE="${CONF_DIR}/default.conf"
DISABLED="${CONF_DIR}/default.conf.disabled"
MAINT_ACTIVE="${CONF_DIR}/maintenance.conf"

if [ ! -f "${MAINT_ACTIVE}" ]; then
  ok "Maintenance mode is not currently enabled (no ${MAINT_ACTIVE}) -- nothing to do."
  exit "${EXIT_OK}"
fi

if [ ! -f "${DISABLED}" ]; then
  die "Cannot restore -- ${DISABLED} not found. If default.conf already exists and looks correct, just remove ${MAINT_ACTIVE} manually and reload nginx." "${EXIT_GENERAL_ERROR}"
fi

log "Disabling maintenance mode"
rm -f "${MAINT_ACTIVE}"
mv "${DISABLED}" "${ACTIVE}"
ok "Restored default.conf, removed maintenance.conf"

log "Validating nginx configuration"
NGINX_TEST_LOG="$(mktemp)"
if ! dc exec -T nginx nginx -t >"${NGINX_TEST_LOG}" 2>&1; then
  error "nginx -t failed against the restored config:"
  sed 's/^/  /' "${NGINX_TEST_LOG}" >&2
  rm -f "${NGINX_TEST_LOG}"
  die "Restored default.conf does not pass nginx -t -- investigate before reloading (site is still serving the maintenance page)." "${EXIT_VALIDATION_FAILED}"
fi
rm -f "${NGINX_TEST_LOG}"

log "Reloading nginx"
if ! dc exec -T nginx nginx -s reload; then
  warn "nginx -s reload failed -- container may not be running. Try: docker compose up -d nginx"
fi

ok "Maintenance mode DISABLED. Site is back to normal routing."
