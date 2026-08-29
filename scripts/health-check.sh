#!/usr/bin/env bash
# VisionMart -- Quick Health Check (DevOps Toolkit Part 1).
#
# Fast pass/fail check suitable for cron/uptime-monitor use: hits each
# service's own /health endpoint plus Docker's healthcheck status.
# Deliberately shallow and quick (a few seconds) -- for the deep,
# category-by-category validation with fix recommendations, use
# scripts/doctor.sh (wraps the existing `visionmart doctor` engine)
# instead. This script never inspects business data.
#
# Usage: scripts/health-check.sh [--quiet]
# Exit codes: 0 = all healthy, 5 (EXIT_UNHEALTHY) = at least one is not.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

QUIET=0
for arg in "$@"; do
  case "$arg" in
    --quiet|-q) QUIET=1 ;;
    -h|--help) echo "Usage: $(basename "$0") [--quiet]"; exit "${EXIT_OK}" ;;
  esac
done

_say() { [ "${QUIET}" -eq 1 ] || printf '%s\n' "$*"; }

BACKEND_PORT="$(env_get BACKEND_PORT)"; BACKEND_PORT="${BACKEND_PORT:-8000}"
AI_ENGINE_PORT="$(env_get AI_ENGINE_PORT)"; AI_ENGINE_PORT="${AI_ENGINE_PORT:-8100}"
MONITORING_PORT="$(env_get MONITORING_PORT)"; MONITORING_PORT="${MONITORING_PORT:-8200}"

overall=0

check_http() {
  local name="$1" url="$2"
  if curl -fsS --max-time 5 "${url}" >/dev/null 2>&1; then
    _say "  OK   ${name} (${url})"
  else
    _say "  FAIL ${name} (${url}) -- not reachable"
    overall=1
  fi
}

check_container_health() {
  local label="$1" name="$2"
  local status
  status="$(container_health "${name}")"
  case "${status}" in
    healthy|none)
      _say "  OK   ${label} container: ${status}"
      ;;
    *)
      _say "  FAIL ${label} container: ${status}"
      overall=1
      ;;
  esac
}

_say "VisionMart Health Check ($(date -u +%FT%TZ))"
check_http "Backend"    "http://127.0.0.1:${BACKEND_PORT}/health"
check_http "AI Engine"  "http://127.0.0.1:${AI_ENGINE_PORT}/health"
check_http "Monitoring" "http://127.0.0.1:${MONITORING_PORT}/health"

check_container_health "PostgreSQL" "visionmart-postgres"
check_container_health "Redis"      "visionmart-redis"
check_container_health "MinIO"      "visionmart-minio"

if [ "${overall}" -eq 0 ]; then
  _say "Result: HEALTHY"
else
  _say "Result: UNHEALTHY -- run scripts/doctor.sh for details and fix recommendations"
fi

exit $([ "${overall}" -eq 0 ] && echo "${EXIT_OK}" || echo "${EXIT_UNHEALTHY}")
