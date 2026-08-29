#!/usr/bin/env bash
# VisionMart DevOps & Deployment Toolkit -- shared shell library.
#
# Sourced (never executed directly) by every script in scripts/*.sh so
# there is exactly ONE implementation of: colored logging, execution
# logging to file, prerequisite checks, confirmation prompts, repo-root
# detection, and the `docker compose` vs `docker-compose` shim -- per the
# "avoid duplicate functionality" requirement. Follows the same
# ==>/OK/!/X output convention already used by scripts/deploy.sh so this
# toolkit feels native to the existing project, not bolted on.
#
# Usage (from any scripts/*.sh):
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck disable=SC1091
#   source "${SCRIPT_DIR}/lib/common.sh"
#
# This file makes NO changes to business logic, Docker images, or the
# application itself -- it only orchestrates existing, already-built
# components (docker compose, backup/cli.py, visionmart doctor,
# scripts/generate_release_info.py, alembic, app.scripts.seed_initial).

# Do not `set -euo pipefail` here -- the sourcing script controls its own
# strict-mode settings; this library must not silently change caller
# behavior. Every function below is defensive on its own.

# --------------------------------------------------------------------
# Colors (disabled automatically when stdout isn't a terminal, e.g. when
# redirected to a log file or piped -- keeps log files clean).
# --------------------------------------------------------------------
if [ -t 1 ]; then
  C_RESET='\033[0m'; C_BOLD='\033[1m'
  C_RED='\033[1;31m'; C_GREEN='\033[1;32m'; C_YELLOW='\033[1;33m'
  C_BLUE='\033[1;34m'; C_CYAN='\033[1;36m'; C_GRAY='\033[0;90m'
else
  C_RESET=''; C_BOLD=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_CYAN=''; C_GRAY=''
fi

# --------------------------------------------------------------------
# Exit code contract -- every script in this toolkit uses these
# consistently so calling automation (cron, CI, `&&` chains) can branch
# on *why* a script failed, not just that it failed.
# --------------------------------------------------------------------
EXIT_OK=0
EXIT_GENERAL_ERROR=1
EXIT_MISSING_PREREQ=2
EXIT_USER_ABORT=3
EXIT_VALIDATION_FAILED=4
EXIT_UNHEALTHY=5

# --------------------------------------------------------------------
# Repo root detection -- auto-detected from this file's location so the
# toolkit works identically whether checked out at /opt/visionmart,
# /var/www/visionmart, or a developer's local clone, without hardcoding
# a path. Override with VISIONMART_APP_DIR if scripts/ is ever copied
# somewhere detached from the repo (not a supported/expected setup, but
# fails loudly rather than silently operating on the wrong tree).
# --------------------------------------------------------------------
_COMMON_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# common.sh lives at <repo>/scripts/lib/common.sh, so the repo root is
# two levels up from this file's own directory.
VISIONMART_APP_DIR="${VISIONMART_APP_DIR:-$(cd "${_COMMON_SH_DIR}/../.." && pwd)}"
export VISIONMART_APP_DIR

# --------------------------------------------------------------------
# Logging -- every invocation of a toolkit script appends a plain-text
# transcript to logs/devops/<script-name>-<timestamp>.log (reuses the
# existing gitignored `logs/` convention -- see .gitignore's
# "Storage / Logs" section) in addition to colored stdout. Call
# `init_logging "$0"` once near the top of each script.
# --------------------------------------------------------------------
DEVOPS_LOG_DIR="${VISIONMART_APP_DIR}/logs/devops"
DEVOPS_LOG_FILE=""

init_logging() {
  local script_name
  script_name="$(basename "${1:-script}" .sh)"
  mkdir -p "${DEVOPS_LOG_DIR}" 2>/dev/null || true
  if [ -w "${DEVOPS_LOG_DIR}" ] 2>/dev/null; then
    DEVOPS_LOG_FILE="${DEVOPS_LOG_DIR}/${script_name}-$(date -u +%Y%m%dT%H%M%SZ).log"
    : > "${DEVOPS_LOG_FILE}" 2>/dev/null || DEVOPS_LOG_FILE=""
  fi
  if [ -n "${DEVOPS_LOG_FILE}" ]; then
    _write_log "=== ${script_name} started $(date -u +%FT%TZ) (user=$(id -un 2>/dev/null || echo unknown), pwd=$(pwd)) ==="
  fi
}

_write_log() {
  [ -n "${DEVOPS_LOG_FILE}" ] && echo "$*" >> "${DEVOPS_LOG_FILE}" 2>/dev/null
  return 0
}

log()   { printf "\n${C_CYAN}==> %s${C_RESET}\n" "$*"; _write_log "==> $*"; }
info()  { printf "${C_BLUE}  i %s${C_RESET}\n" "$*"; _write_log "  i $*"; }
ok()    { printf "${C_GREEN}  OK %s${C_RESET}\n" "$*"; _write_log "  OK $*"; }
warn()  { printf "${C_YELLOW}  ! %s${C_RESET}\n" "$*" >&2; _write_log "  WARN $*"; }
error() { printf "${C_RED}  X %s${C_RESET}\n" "$*" >&2; _write_log "  ERROR $*"; }
die()   { error "$*"; exit "${2:-$EXIT_GENERAL_ERROR}"; }

# --------------------------------------------------------------------
# Confirmation prompt -- respects --yes/-y (or ASSUME_YES=1 env var) so
# every interactive script can also run unattended in automation. Never
# defaults to "yes" when input is genuinely ambiguous or non-interactive
# without an explicit flag -- a script piped into non-interactively with
# no --yes will abort rather than silently proceeding with a destructive
# action.
# --------------------------------------------------------------------
ASSUME_YES="${ASSUME_YES:-0}"

confirm() {
  local prompt="${1:-Continue?}"
  if [ "${ASSUME_YES}" = "1" ]; then
    info "${prompt} [auto-confirmed: --yes]"
    return 0
  fi
  if [ ! -t 0 ]; then
    error "${prompt} -- refusing to assume 'yes' on a non-interactive terminal. Re-run with --yes to proceed unattended."
    return 1
  fi
  local reply
  read -r -p "$(printf "${C_YELLOW}?${C_RESET} %s [y/N] " "${prompt}")" reply
  case "${reply}" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

# --------------------------------------------------------------------
# Prerequisite checks
# --------------------------------------------------------------------
require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Required command not found: $1" "${EXIT_MISSING_PREREQ}"
  fi
}

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    die "This script must be run as root (or via sudo)." "${EXIT_MISSING_PREREQ}"
  fi
}

require_file() {
  [ -f "$1" ] || die "Required file not found: $1" "${EXIT_MISSING_PREREQ}"
}

require_env_file() {
  if [ ! -f "${VISIONMART_APP_DIR}/.env" ]; then
    die "No .env found at ${VISIONMART_APP_DIR}/.env -- run scripts/generate-secrets.sh first." "${EXIT_MISSING_PREREQ}"
  fi
}

# --------------------------------------------------------------------
# docker compose shim -- prefers the modern `docker compose` plugin,
# falls back to the legacy `docker-compose` binary if that's all a given
# host has installed. Every script calls `dc <args...>` instead of
# hardcoding either form.
# --------------------------------------------------------------------
dc() {
  if docker compose version >/dev/null 2>&1; then
    (cd "${VISIONMART_APP_DIR}" && docker compose "$@")
  elif command -v docker-compose >/dev/null 2>&1; then
    (cd "${VISIONMART_APP_DIR}" && docker-compose "$@")
  else
    die "Neither 'docker compose' nor 'docker-compose' is available." "${EXIT_MISSING_PREREQ}"
  fi
}

# --------------------------------------------------------------------
# .env helpers -- read a single key without exporting the whole file
# (avoids clobbering the calling shell's environment with every app
# setting). Returns empty string, never errors, if the file or key is
# absent.
# --------------------------------------------------------------------
env_get() {
  local key="$1" file="${2:-${VISIONMART_APP_DIR}/.env}"
  [ -f "${file}" ] || return 0
  grep -E "^${key}=" "${file}" 2>/dev/null \
    | tail -n1 \
    | cut -d'=' -f2- \
    | sed -E 's/[[:space:]]+#.*$//' \
    | sed -E 's/[[:space:]]+$//' || true
}

# --------------------------------------------------------------------
# Generic "wait until healthy" poll -- reused by setup-production.sh,
# update-production.sh, and health-check.sh instead of three copies of
# the same retry loop (mirrors the pattern already in scripts/deploy.sh).
# --------------------------------------------------------------------
wait_for_http() {
  local url="$1" timeout="${2:-60}" label="${3:-$1}"
  local i=0
  while [ "${i}" -lt "${timeout}" ]; do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  warn "${label} did not become reachable within ${timeout}s"
  return 1
}

container_health() {
  # Prints "healthy" / "unhealthy" / "starting" / "none" (no healthcheck
  # defined) / "missing" (container doesn't exist). Never errors out.
  local name="$1"
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${name}" 2>/dev/null || echo "missing"
}

print_version_banner() {
  local version
  version="$(cat "${VISIONMART_APP_DIR}/VERSION" 2>/dev/null || echo "unknown")"
  printf "${C_BOLD}VisionMart${C_RESET} %s\n" "${version}"
}
