#!/usr/bin/env bash
# VisionMart -- Status (DevOps Toolkit Part 12).
#
# One-screen operational snapshot. Reuses the existing monitoring
# service's /api/overview endpoint (already aggregates Health Score,
# camera counts, host resources, Redis/PostgreSQL/Celery reachability --
# see monitoring/server.py) instead of re-collecting any of that itself;
# only git/Docker-Compose/host-uptime facts that monitoring doesn't
# already expose are gathered directly here.
#
# Usage: scripts/status.sh [--json]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

JSON_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --json) JSON_ONLY=1 ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--json]"
      echo "Prints a one-screen operational status snapshot. --json prints monitoring's raw /api/overview response instead."
      exit "${EXIT_OK}"
      ;;
  esac
done

cd "${VISIONMART_APP_DIR}"

VERSION_STR="$(cat "${VISIONMART_APP_DIR}/VERSION" 2>/dev/null || echo unknown)"
GIT_BRANCH="unknown"; GIT_COMMIT="unknown"
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  GIT_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
fi

MONITORING_PORT="$(env_get MONITORING_PORT)"
MONITORING_PORT="${MONITORING_PORT:-8200}"
MONITORING_TOKEN="$(env_get MONITORING_API_TOKEN)"

overview="{}"
overview_ok=0
if [ -n "${MONITORING_TOKEN}" ] && command -v curl >/dev/null 2>&1; then
  if resp="$(curl -fsS --max-time 5 -H "Authorization: Bearer ${MONITORING_TOKEN}" "http://127.0.0.1:${MONITORING_PORT}/api/overview" 2>/dev/null)"; then
    overview="${resp}"
    overview_ok=1
  fi
fi

if [ "${JSON_ONLY}" -eq 1 ]; then
  if [ "${overview_ok}" -eq 1 ]; then
    echo "${overview}" | python3 -m json.tool 2>/dev/null || echo "${overview}"
  else
    error "Could not reach the monitoring service's /api/overview -- is it running? (docker compose ps monitoring)"
    exit "${EXIT_GENERAL_ERROR}"
  fi
  exit "${EXIT_OK}"
fi

log "VisionMart Status"
info "Version       : ${VERSION_STR}"
info "Git           : ${GIT_BRANCH} @ ${GIT_COMMIT}"
if command -v uptime >/dev/null 2>&1; then
  info "Host uptime   : $(uptime -p 2>/dev/null || uptime)"
fi

log "Containers"
dc ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || dc ps

if [ "${overview_ok}" -ne 1 ]; then
  warn "Monitoring service unreachable at http://127.0.0.1:${MONITORING_PORT}/api/overview -- remaining sections skipped."
  warn "Check: docker compose ps monitoring / docker compose logs monitoring / MONITORING_API_TOKEN in .env"
  exit "${EXIT_OK}"
fi

python3 -c "
import json, sys
d = json.loads(sys.stdin.read())

def fmt_bool(b):
    return 'yes' if b else 'no'

hs = d.get('health_score') or {}
print()
print('==> Health Score')
print(f\"  Score  : {hs.get('score', 'n/a')} ({hs.get('status', 'unknown')})\")
if hs.get('reasons'):
    for r in hs['reasons'][:5]:
        print(f'    - {r}')

sh = d.get('service_health') or {}
print()
print('==> Services')
for name in ('backend', 'ai_engine'):
    info = sh.get(name) or {}
    print(f\"  {name:12s}: {'OK' if info.get('ok') else 'DOWN'} {('- ' + str(info.get('reason'))) if info.get('reason') else ''}\")

sysinfo = d.get('system') or {}
host = sysinfo.get('host') or {}
print()
print('==> Host Resources')
print(f\"  CPU   : {host.get('cpu_percent', 'n/a')}%\")
print(f\"  RAM   : {host.get('ram_percent', 'n/a')}% ({host.get('ram_used_gb','?')} / {host.get('ram_total_gb','?')} GB)\")
print(f\"  Disk  : {host.get('disk_percent', 'n/a')}% ({host.get('disk_used_gb','?')} / {host.get('disk_total_gb','?')} GB)\")
print(f\"  GPU   : {'available, ' + str(host.get('gpu_util_percent')) + '% util' if host.get('gpu_available') else 'not available (CPU-only)'}\")

redis = sysinfo.get('redis') or {}
pg = sysinfo.get('postgres') or {}
celery = sysinfo.get('celery') or {}
print()
print('==> Data & Workers')
print(f\"  Redis      : {'reachable' if redis.get('reachable') else 'UNREACHABLE'} ({redis.get('connected_clients','?')} clients, {redis.get('used_memory_mb','?')} MB used)\")
print(f\"  PostgreSQL : {'reachable' if pg.get('reachable') else 'UNREACHABLE'} (v{pg.get('version','?')}, {pg.get('active_connections','?')} active conns)\")
print(f\"  Celery     : {celery.get('worker_count', 0)} worker(s) responding\" if celery.get('reachable') else '  Celery     : UNREACHABLE')

cams = d.get('camera_summary') or {}
print()
print('==> Cameras')
print(f\"  Total     : {cams.get('total', 0)}\")
print(f\"  Online    : {cams.get('online', 0)}\")

ev = d.get('evaluation') or {}
print()
print('==> Evaluation')
if ev.get('note'):
    print(f\"  {ev['note']}\")
else:
    print(f\"  Last run reported (see: scripts/logs.sh evaluation, or evaluation_results/ for full reports)\")

alerts = d.get('active_alert_count', 0)
print()
print(f'==> Active Alerts: {alerts}')
" <<< "${overview}"
