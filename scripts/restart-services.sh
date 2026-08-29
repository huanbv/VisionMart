#!/usr/bin/env bash
# VisionMart -- Restart Services (DevOps Toolkit Part 1).
#
# Restarts one, several, or all services via `docker compose restart`
# (in-place restart, no rebuild/recreate -- code/image changes need
# scripts/update-production.sh instead). Optionally waits for the
# restarted containers to report healthy using the same polling logic
# setup/update use (scripts/lib/deploy_engine.sh), so this never leaves
# the operator guessing whether a restart actually came back up clean.
#
# Usage:
#   scripts/restart-services.sh [service...] [--wait] [--timeout N]
#
# With no service names, restarts every service in docker-compose.yml.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/deploy_engine.sh"

WAIT=0
TIMEOUT=120
declare -a SERVICES=()

_args=("$@")
i=0
while [ "$i" -lt "${#_args[@]}" ]; do
  arg="${_args[$i]}"
  case "$arg" in
    --wait) WAIT=1 ;;
    --timeout) i=$((i + 1)); TIMEOUT="${_args[$i]:-120}" ;;
    -h|--help)
      echo "Usage: $(basename "$0") [service...] [--wait] [--timeout N]"
      echo "With no service names, restarts every service."
      exit "${EXIT_OK}"
      ;;
    *) SERVICES+=("$arg") ;;
  esac
  i=$((i + 1))
done

init_logging "$0"
require_env_file

if [ "${#SERVICES[@]}" -eq 0 ]; then
  log "Restarting all services"
  dc restart
else
  log "Restarting: ${SERVICES[*]}"
  dc restart "${SERVICES[@]}"
fi

if [ "${WAIT}" -eq 1 ]; then
  wait_for_stack_healthy "${TIMEOUT}" || exit "${EXIT_UNHEALTHY}"
fi

ok "Restart complete"
dc ps
