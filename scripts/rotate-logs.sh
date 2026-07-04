#!/usr/bin/env bash
# VisionMart -- Rotate Logs (DevOps Toolkit Part 1).
#
# Docker's "local" logging driver (docker-compose.yml's shared
# x-logging anchor) and each standalone Python service's
# RotatingFileHandler (monitoring/backup/evaluation, see
# docs/18_LOGGING.md) already rotate and gzip their own logs
# automatically by size -- there is nothing to "force rotate" there,
# and this script does not pretend otherwise.
#
# What this script actually does:
#   1. Reports current on-disk size of every log source in the project.
#   2. --compact: proactively gzip-compresses this toolkit's own
#      logs/devops/*.log files older than 1 day (the one log source
#      this toolkit fully owns) ahead of cleanup.sh's deletion
#      threshold -- genuinely useful, nothing more is claimed.
#
# Usage: scripts/rotate-logs.sh [--compact]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

COMPACT=0
for arg in "$@"; do
  case "$arg" in
    --compact) COMPACT=1 ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit "${EXIT_OK}"
      ;;
  esac
done

init_logging "$0"

log "Log sizes"

if [ -d "${DEVOPS_LOG_DIR}" ]; then
  info "This toolkit's own logs (${DEVOPS_LOG_DIR}): $(du -sh "${DEVOPS_LOG_DIR}" 2>/dev/null | cut -f1)"
else
  info "This toolkit's own logs: none yet"
fi

EVAL_LOG_DIR="${VISIONMART_APP_DIR}/evaluation_results/logs"
if [ -d "${EVAL_LOG_DIR}" ]; then
  info "Evaluation logs (${EVAL_LOG_DIR}): $(du -sh "${EVAL_LOG_DIR}" 2>/dev/null | cut -f1)"
else
  info "Evaluation logs: none yet (no evaluation run has produced one)"
fi

for svc in monitoring backup; do
  size="$(dc exec -T "${svc}" du -sh /data/logs 2>/dev/null | cut -f1)"
  if [ -n "${size}" ]; then
    info "${svc} service logs (container:/data/logs): ${size} (auto-rotated by RotatingFileHandler)"
  else
    info "${svc} service logs: container not running or /data/logs not found"
  fi
done

info "Docker container logs (driver: local, auto-rotated -- see docker-compose.yml x-logging anchor):"
dc ps --format '{{.Name}}' 2>/dev/null | while read -r cname; do
  [ -z "${cname}" ] && continue
  size="$(docker inspect --format='{{.LogPath}}' "${cname}" 2>/dev/null | xargs -r du -sh 2>/dev/null | cut -f1)"
  info "  ${cname}: ${size:-n/a (local driver stores logs outside a simple host path)}"
done

if [ "${COMPACT}" -eq 1 ]; then
  log "Compacting this toolkit's own logs older than 1 day"
  if [ -d "${DEVOPS_LOG_DIR}" ]; then
    compacted=0
    while IFS= read -r f; do
      gzip -f "$f" && compacted=$((compacted + 1))
    done < <(find "${DEVOPS_LOG_DIR}" -maxdepth 1 -type f -name '*.log' -mtime +1)
    ok "Compacted ${compacted} file(s)"
  else
    info "Nothing to compact yet"
  fi
else
  info "Pass --compact to gzip this toolkit's own logs older than 1 day."
fi

info "Docker/RotatingFileHandler rotation is automatic -- see docs/18_LOGGING.md. Old backups/logs are pruned by scripts/cleanup.sh."
