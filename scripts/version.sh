#!/usr/bin/env bash
# VisionMart -- Version (DevOps Toolkit Part 13).
#
# Prints exactly the version facts an operator or bug report needs.
# Reuses the same VERSION file every other surface reads (see
# docs/44_VERSIONING.md) -- never a second source of truth for the app
# version string.
#
# Usage: scripts/version.sh [--json]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

JSON_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --json) JSON_ONLY=1 ;;
    -h|--help) echo "Usage: $(basename "$0") [--json]"; exit "${EXIT_OK}" ;;
  esac
done

cd "${VISIONMART_APP_DIR}"

APP_VERSION="$(cat VERSION 2>/dev/null || echo unknown)"

RC_LABEL="stable"
case "${APP_VERSION}" in
  *-rc*) RC_LABEL="release candidate" ;;
  *-beta*) RC_LABEL="beta" ;;
  *-alpha*) RC_LABEL="alpha" ;;
esac

GIT_SHA="unknown"; GIT_BRANCH="unknown"; GIT_DIRTY="unknown"
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  if git diff --quiet 2>/dev/null && git diff --cached --quiet 2>/dev/null; then
    GIT_DIRTY="no"
  else
    GIT_DIRTY="yes"
  fi
fi

BUILD_TIME="unknown"
if [ -f release_info.json ] && command -v python3 >/dev/null 2>&1; then
  BUILD_TIME="$(python3 -c "import json; print(json.load(open('release_info.json')).get('build_time_utc','unknown'))" 2>/dev/null || echo unknown)"
fi

PYTHON_VERSION="$(python3 --version 2>&1 | awk '{print $2}' || echo unknown)"
NODE_VERSION="$(command -v node >/dev/null 2>&1 && node --version || echo "not installed")"
DOCKER_VERSION="$(command -v docker >/dev/null 2>&1 && docker --version | sed 's/Docker version //;s/,.*//' || echo "not installed")"
COMPOSE_VERSION="$(docker compose version --short 2>/dev/null || echo unknown)"
OS_PRETTY="unknown"
[ -f /etc/os-release ] && OS_PRETTY="$( . /etc/os-release && echo "${PRETTY_NAME:-unknown}")"
KERNEL_VERSION="$(uname -r 2>/dev/null || echo unknown)"

if [ "${JSON_ONLY}" -eq 1 ]; then
  python3 -c "
import json
print(json.dumps({
    'app_version': '${APP_VERSION}',
    'release_candidate': '${RC_LABEL}',
    'build_time': '${BUILD_TIME}',
    'git_sha': '${GIT_SHA}',
    'git_branch': '${GIT_BRANCH}',
    'git_dirty': '${GIT_DIRTY}',
    'python_version': '${PYTHON_VERSION}',
    'node_version': '${NODE_VERSION}',
    'docker_version': '${DOCKER_VERSION}',
    'compose_version': '${COMPOSE_VERSION}',
    'os': '${OS_PRETTY}',
    'kernel': '${KERNEL_VERSION}',
}, indent=2))
" 2>/dev/null || echo "{\"app_version\": \"${APP_VERSION}\"}"
  exit "${EXIT_OK}"
fi

echo "VisionMart ${APP_VERSION} (${RC_LABEL})"
echo
echo "  Build time      : ${BUILD_TIME}"
echo "  Git SHA         : ${GIT_SHA} (branch: ${GIT_BRANCH}, uncommitted changes: ${GIT_DIRTY})"
echo "  Python          : ${PYTHON_VERSION}"
echo "  Node.js         : ${NODE_VERSION}"
echo "  Docker          : ${DOCKER_VERSION}"
echo "  Compose plugin  : ${COMPOSE_VERSION}"
echo "  OS              : ${OS_PRETTY}"
echo "  Kernel          : ${KERNEL_VERSION}"
echo
echo "Run scripts/generate_release_info.py at build/deploy time to populate build_time from git/CI, not just this checkout's local state."
