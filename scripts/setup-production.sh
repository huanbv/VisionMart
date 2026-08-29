#!/usr/bin/env bash
# VisionMart -- Production Setup (DevOps Toolkit Part 2).
#
# First-time provisioning of a fresh Ubuntu VPS: installs prerequisites
# and Docker, clones (or updates) the repository, then hands off to the
# shared deployment engine (scripts/lib/deploy_engine.sh) for the exact
# same pull/build/up/migrate/seed/doctor sequence update-production.sh
# uses -- no duplicated deployment logic between the two entry points.
#
# Safe to run more than once: OS package installs are idempotent (apt
# skips already-installed packages), Docker install/enable is a no-op if
# already present, the repo step does `git pull` instead of `git clone`
# if the target directory already holds this repo, and every step below
# it (secrets, migrations, seed) is itself idempotent by design.
#
# Usage:
#   sudo bash scripts/setup-production.sh [options]
#
# Options:
#   --repo-url URL     Git remote to clone (HTTPS or SSH). Default:
#                       https://github.com/huanbv/VisionMart.git
#                       (override with SSH, e.g. git@github.com:you/VisionMart.git,
#                       for private forks -- your deploy key must already be
#                       authorized on the remote).
#   --branch NAME      Branch to check out. Default: main.
#   --app-dir PATH     Where to clone/update the repo. Default: /opt/visionmart
#                       (also settable via VISIONMART_APP_DIR).
#   --skip-os-setup    Skip apt package installation and Docker install
#                       (use when these are already provisioned, e.g. a
#                       pre-baked image, or a non-Ubuntu host with Docker
#                       already installed by other means).
#   --seed-admin       Also create the initial organization/roles/admin
#                       user after migrations (safe to re-run; skipped by
#                       default so re-running setup never re-seeds
#                       unexpectedly).
#   --yes              Assume "yes" to all confirmation prompts.
#   -h, --help         Show this help and exit.
set -uo pipefail

REPO_URL="${REPO_URL:-https://github.com/huanbv/VisionMart.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${VISIONMART_APP_DIR:-/opt/visionmart}"
SKIP_OS_SETUP=0
SEED_ADMIN=0
BOOT_ASSUME_YES=0

usage() { sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'; }

_args=("$@")
for i in "${!_args[@]}"; do
  case "${_args[$i]}" in
    --repo-url) [ $((i + 1)) -lt ${#_args[@]} ] && REPO_URL="${_args[$((i + 1))]}" ;;
    --branch)   [ $((i + 1)) -lt ${#_args[@]} ] && BRANCH="${_args[$((i + 1))]}" ;;
    --app-dir)  [ $((i + 1)) -lt ${#_args[@]} ] && APP_DIR="${_args[$((i + 1))]}" ;;
    --skip-os-setup) SKIP_OS_SETUP=1 ;;
    --seed-admin) SEED_ADMIN=1 ;;
    --yes|-y) BOOT_ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
  esac
done

# --------------------------------------------------------------------
# Bootstrap-phase logging -- deliberately NOT sourced from common.sh:
# at this point the repo (and therefore scripts/lib/common.sh) may not
# exist on disk yet. These definitions are overridden for free once we
# `source` the real common.sh later in this same script, right after
# the clone/update step succeeds -- same names, richer implementation,
# zero special-casing needed in the rest of this file.
# --------------------------------------------------------------------
if [ -t 1 ]; then C_CYAN='\033[1;36m'; C_GREEN='\033[1;32m'; C_YELLOW='\033[1;33m'; C_RED='\033[1;31m'; C_RESET='\033[0m'; else C_CYAN=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_RESET=''; fi
log()   { printf "\n${C_CYAN}==> %s${C_RESET}\n" "$*"; }
info()  { printf "  i %s\n" "$*"; }
ok()    { printf "${C_GREEN}  OK %s${C_RESET}\n" "$*"; }
warn()  { printf "${C_YELLOW}  ! %s${C_RESET}\n" "$*" >&2; }
error() { printf "${C_RED}  X %s${C_RESET}\n" "$*" >&2; }
die()   { error "$*"; exit "${2:-1}"; }

log "VisionMart Production Setup"
info "App directory : ${APP_DIR}"
info "Repository    : ${REPO_URL} (branch: ${BRANCH})"

# --------------------------------------------------------------------
# Part 2: Ubuntu VPS prep
# --------------------------------------------------------------------
if [ "${SKIP_OS_SETUP}" -eq 0 ]; then
  log "Checking prerequisites"

  if [ "$(id -u)" -ne 0 ]; then
    die "This step installs OS packages and must run as root (sudo). Re-run with sudo, or pass --skip-os-setup if prerequisites are already installed."
  fi

  if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    info "OS: ${PRETTY_NAME:-unknown} (arch: $(uname -m))"
    if [ "${ID:-}" != "ubuntu" ]; then
      warn "This script is written for Ubuntu -- detected '${ID:-unknown}'. Continuing, but apt-based steps may fail."
    fi
  else
    warn "/etc/os-release not found -- cannot confirm this is Ubuntu. Continuing."
  fi

  TOTAL_RAM_MB="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo unknown)"
  DISK_FREE_GB="$(df -Pk / 2>/dev/null | awk 'NR==2 {print int($4/1024/1024)}')"
  info "RAM: ${TOTAL_RAM_MB} MB, free disk on /: ${DISK_FREE_GB:-unknown} GB"
  if [ "${TOTAL_RAM_MB}" != "unknown" ] && [ "${TOTAL_RAM_MB}" -lt 4096 ]; then
    warn "Less than 4 GB RAM detected -- docs/DEPLOY_VPS.md recommends at least 8 GB for CPU-only YOLO inference."
  fi

  if curl -fsS --max-time 5 https://deb.debian.org >/dev/null 2>&1 || curl -fsS --max-time 5 https://github.com >/dev/null 2>&1; then
    ok "Internet connectivity OK"
  else
    die "No outbound internet connectivity detected -- required to install packages and pull images."
  fi

  log "Installing base packages (git curl wget jq zip unzip openssl ca-certificates)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git curl wget jq zip unzip openssl ca-certificates gnupg lsb-release >/dev/null
  ok "Base packages installed"

  log "Installing Docker Engine + Compose plugin"
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker + Compose plugin already installed ($(docker --version))"
  else
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    ARCH="$(dpkg --print-architecture)"
    CODENAME="$( . /etc/os-release && echo "${VERSION_CODENAME:-jammy}")"
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
      | tee /etc/apt/sources.list.d/docker.list >/dev/null
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
    ok "Docker Engine + Compose plugin installed"
  fi

  systemctl enable --now docker >/dev/null 2>&1 || true
  if docker info >/dev/null 2>&1; then
    ok "Docker daemon is running ($(docker compose version | head -1))"
  else
    die "Docker daemon is not responding after install/start -- check: systemctl status docker"
  fi
else
  info "Skipping OS/Docker setup (--skip-os-setup)"
fi

# --------------------------------------------------------------------
# Part 2: clone-or-update repository (HTTPS or SSH remote)
# --------------------------------------------------------------------
log "Fetching application code"
mkdir -p "$(dirname "${APP_DIR}")" 2>/dev/null || true

if [ -d "${APP_DIR}/.git" ]; then
  info "Existing checkout found at ${APP_DIR} -- updating"
  git -C "${APP_DIR}" fetch --quiet origin
  git -C "${APP_DIR}" checkout --quiet "${BRANCH}"
  git -C "${APP_DIR}" pull --ff-only --quiet origin "${BRANCH}"
  ok "Repository updated to $(git -C "${APP_DIR}" rev-parse --short HEAD)"
elif [ -d "${APP_DIR}" ] && [ -n "$(ls -A "${APP_DIR}" 2>/dev/null)" ]; then
  die "Target directory ${APP_DIR} exists, is non-empty, and is not a git checkout -- refusing to overwrite. Remove it or pass a different --app-dir."
else
  mkdir -p "${APP_DIR}"
  git clone --quiet --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
  ok "Cloned $(git -C "${APP_DIR}" rev-parse --short HEAD) into ${APP_DIR}"
fi

# --------------------------------------------------------------------
# From here on, reuse the shared library instead of duplicating logic --
# it is now guaranteed to exist because the clone/update above succeeded.
# --------------------------------------------------------------------
SCRIPT_DIR="${APP_DIR}/scripts"
if [ ! -f "${SCRIPT_DIR}/lib/common.sh" ]; then
  die "scripts/lib/common.sh not found in ${APP_DIR} after checkout -- is ${REPO_URL} the correct repository/branch?"
fi
export VISIONMART_APP_DIR="${APP_DIR}"
export ASSUME_YES="${BOOT_ASSUME_YES}"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/deploy_engine.sh"
init_logging "$0"

# --------------------------------------------------------------------
# Part 3: environment / secrets
# --------------------------------------------------------------------
log "Generating environment configuration and secrets"
bash "${SCRIPT_DIR}/generate-secrets.sh" ${BOOT_ASSUME_YES:+--yes}

# --------------------------------------------------------------------
# Part 4: deployment engine
# --------------------------------------------------------------------
deploy_pull_build
deploy_up
wait_for_stack_healthy 240 || warn "Continuing despite unhealthy container(s) -- review before considering this deployment production-ready."

# --------------------------------------------------------------------
# Part 5: database initialization
# --------------------------------------------------------------------
run_db_migrations || die "Aborting -- fix the migration error above before continuing." "${EXIT_GENERAL_ERROR}"

if [ "${SEED_ADMIN}" -eq 1 ]; then
  SEED_ADMIN_ON_SETUP=1 run_seed_initial
else
  info "Skipping admin seed (pass --seed-admin to create the initial organization/roles/admin user)"
fi

# --------------------------------------------------------------------
# Part 6: health verification
# --------------------------------------------------------------------
run_health_verification
doctor_status=$?

log "Setup finished"
print_version_banner
dc ps
if [ "${doctor_status}" -ne 0 ]; then
  error "visionmart doctor reported FAIL -- review the recommendations above before serving production traffic."
  exit "${EXIT_UNHEALTHY}"
fi
ok "VisionMart is up. Next steps: configure DNS/TLS (docs/DEPLOY_VPS.md §6-9), then scripts/status.sh to confirm."
