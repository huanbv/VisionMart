#!/usr/bin/env bash
# VisionMart -- Logs viewer (DevOps Toolkit Part 9).
#
# One entry point for every log source in the stack: Docker-based
# services via `docker compose logs` (already the right tool -- not
# reimplemented), and `evaluation/` (a CLI, not a container) by tailing
# its rotating log file directly from the filesystem.
#
# Usage:
#   scripts/logs.sh <target> [--follow] [--tail N] [--search PATTERN]
#   scripts/logs.sh --list
#
# Targets:
#   backend, frontend, ai-engine, monitoring, backup, backup-once,
#   celery-worker, celery-beat, celery (both celery-worker + celery-beat),
#   postgres, redis, minio, nginx, evaluation, all (every Docker service)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

usage() {
  cat <<'EOF'
VisionMart Logs

Usage:
  scripts/logs.sh <target> [options]
  scripts/logs.sh --list

Targets:
  backend, frontend, ai-engine, monitoring, backup, backup-once,
  celery-worker, celery-beat, celery, postgres, redis, minio, nginx,
  evaluation, all

Options:
  -f, --follow        Stream new log lines (like tail -f).
  --tail N            Number of historical lines to show. Default: 200.
  --search PATTERN    Only show lines matching PATTERN (grep -E, case-insensitive).
  --list              List valid targets and exit.
  -h, --help          Show this help.
EOF
}

TARGET=""
FOLLOW=0
TAIL_N=200
SEARCH=""

_args=("$@")
i=0
while [ "$i" -lt "${#_args[@]}" ]; do
  arg="${_args[$i]}"
  case "$arg" in
    -f|--follow) FOLLOW=1 ;;
    --tail) i=$((i + 1)); TAIL_N="${_args[$i]:-200}" ;;
    --search) i=$((i + 1)); SEARCH="${_args[$i]:-}" ;;
    --list)
      echo "backend frontend ai-engine monitoring backup backup-once celery-worker celery-beat celery postgres redis minio nginx evaluation all"
      exit "${EXIT_OK}"
      ;;
    -h|--help) usage; exit "${EXIT_OK}" ;;
    -*) error "Unknown option: $arg"; usage; exit "${EXIT_VALIDATION_FAILED}" ;;
    *) [ -z "${TARGET}" ] && TARGET="$arg" ;;
  esac
  i=$((i + 1))
done

if [ -z "${TARGET}" ]; then
  error "No target given."
  usage
  exit "${EXIT_VALIDATION_FAILED}"
fi

_dc_services_for() {
  case "$1" in
    celery) echo "celery-worker celery-beat" ;;
    all) echo "" ;; # empty = every service, docker compose default
    backend|frontend|ai-engine|monitoring|backup|backup-once|celery-worker|celery-beat|postgres|redis|minio|nginx)
      echo "$1" ;;
    *) echo "__invalid__" ;;
  esac
}

show_docker_logs() {
  local services
  services="$(_dc_services_for "${TARGET}")"
  if [ "${services}" = "__invalid__" ]; then
    error "Unknown target: ${TARGET}"
    usage
    exit "${EXIT_VALIDATION_FAILED}"
  fi

  local -a args=(logs "--tail=${TAIL_N}")
  [ "${FOLLOW}" -eq 1 ] && args+=("--follow")
  # shellcheck disable=SC2206
  args+=(${services})

  if [ -n "${SEARCH}" ]; then
    dc "${args[@]}" | grep -iE --line-buffered "${SEARCH}"
  else
    dc "${args[@]}"
  fi
}

show_evaluation_logs() {
  local log_file="${VISIONMART_APP_DIR}/evaluation_results/logs/evaluation.log"
  if [ ! -f "${log_file}" ]; then
    warn "No evaluation log yet at ${log_file} -- no evaluation run has produced one (see evaluation/cli.py --output-dir)."
    return "${EXIT_OK}"
  fi

  if [ "${FOLLOW}" -eq 1 ]; then
    if [ -n "${SEARCH}" ]; then
      tail -n "${TAIL_N}" -f "${log_file}" | grep -iE --line-buffered "${SEARCH}"
    else
      tail -n "${TAIL_N}" -f "${log_file}"
    fi
  else
    if [ -n "${SEARCH}" ]; then
      tail -n "${TAIL_N}" "${log_file}" | grep -iE "${SEARCH}"
    else
      tail -n "${TAIL_N}" "${log_file}"
    fi
  fi
}

case "${TARGET}" in
  evaluation) show_evaluation_logs ;;
  *) show_docker_logs ;;
esac
