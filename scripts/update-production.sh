#!/usr/bin/env bash
# VisionMart -- Update Production (DevOps Toolkit Part 7).
#
# Re-deploys an already-provisioned VisionMart instance: pulls new code,
# shows what changed, rebuilds/restarts, migrates, and validates -- via
# the same shared deployment engine setup-production.sh uses (Part 4/5/6
# logic lives in exactly one place: scripts/lib/deploy_engine.sh).
#
# Unlike setup-production.sh this script never installs OS packages,
# never touches Docker itself, and never seeds the admin user -- it only
# updates an existing, already-initialized deployment.
#
# Usage:
#   scripts/update-production.sh [options]
#
# Options:
#   --branch NAME   Branch to update to. Default: current branch.
#   --with-frontend Also rebuild the frontend image (matches the
#                    existing scripts/deploy.sh convention -- frontend is
#                    normally picked up automatically by its own image).
#   --yes           Assume "yes" to the update confirmation prompt.
#   -h, --help      Show this help and exit.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/deploy_engine.sh"

BRANCH=""
WITH_FRONTEND=0

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

_args=("$@")
for i in "${!_args[@]}"; do
  case "${_args[$i]}" in
    --branch) [ $((i + 1)) -lt ${#_args[@]} ] && BRANCH="${_args[$((i + 1))]}" ;;
    --with-frontend) WITH_FRONTEND=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) usage; exit "${EXIT_OK}" ;;
  esac
done

init_logging "$0"
cd "${VISIONMART_APP_DIR}"

[ -d "${VISIONMART_APP_DIR}/.git" ] || die "No git checkout found at ${VISIONMART_APP_DIR} -- run setup-production.sh first." "${EXIT_MISSING_PREREQ}"
require_cmd git

BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"

log "Checking for updates (branch: ${BRANCH})"
BEFORE_SHA="$(git rev-parse HEAD)"
git fetch --quiet origin "${BRANCH}"
AFTER_SHA="$(git rev-parse "origin/${BRANCH}")"

if [ "${BEFORE_SHA}" = "${AFTER_SHA}" ]; then
  ok "Already up to date (${BEFORE_SHA:0:12})"
  info "Continuing anyway -- this also re-runs migrations/health checks, useful after a manual .env or config change."
else
  echo
  info "Current version : ${BEFORE_SHA:0:12}"
  info "New version     : ${AFTER_SHA:0:12}"
  info "Commits:"
  git --no-pager log --oneline "${BEFORE_SHA}..${AFTER_SHA}" | sed 's/^/    /'
  echo
  if ! confirm "Pull and deploy ${AFTER_SHA:0:12}?"; then
    die "Update cancelled by user." "${EXIT_USER_ABORT}"
  fi
  git checkout --quiet "${BRANCH}"
  git pull --ff-only --quiet origin "${BRANCH}"
  ok "Updated $(git rev-parse --short HEAD)"
fi

SERVICES=""
if [ "${WITH_FRONTEND}" -eq 1 ]; then
  SERVICES="frontend"
fi

deploy_pull_build ${SERVICES}
deploy_up
if ! wait_for_stack_healthy 180; then
  error "One or more containers failed to become healthy after the update."
  error "Rollback guidance: git checkout ${BEFORE_SHA} && scripts/update-production.sh --yes"
  exit "${EXIT_UNHEALTHY}"
fi

if ! run_db_migrations; then
  error "Migration failed after update."
  error "Rollback guidance: review the Alembic error above -- migrations are forward-only, so rolling back code without also rolling back the schema may not be safe. See docs/49_DISASTER_RECOVERY.md."
  exit "${EXIT_GENERAL_ERROR}"
fi

run_health_verification
doctor_status=$?

log "Update summary"
print_version_banner
dc ps
info "Changed files: git diff --name-only ${BEFORE_SHA} ${AFTER_SHA}"

if [ "${doctor_status}" -ne 0 ]; then
  error "visionmart doctor reported FAIL after update -- review recommendations above."
  error "Rollback guidance: git checkout ${BEFORE_SHA} && scripts/update-production.sh --yes"
  exit "${EXIT_UNHEALTHY}"
fi

ok "Update complete"
