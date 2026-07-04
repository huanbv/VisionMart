#!/usr/bin/env bash
# VisionMart -- Doctor (DevOps Toolkit Part 1/6).
#
# Thin CLI wrapper around the existing `python -m visionmart doctor`
# engine (visionmart/doctor.py, built in the Final Production Readiness
# phase, reused here rather than re-implemented -- see
# docs/46_DEPLOYMENT_VALIDATION.md). For a fast up/down check instead of
# this deep 28-check validation, use scripts/health-check.sh.
#
# Usage: scripts/doctor.sh
# Exit codes: 0 = no FAIL (WARNINGs allowed), 1 = at least one FAIL.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      echo "Usage: $(basename "$0")"
      echo "Runs 'python -m visionmart doctor' inside the monitoring container (has every dependency the checks need)."
      exit "${EXIT_OK}"
      ;;
  esac
done

require_env_file
dc exec -T monitoring python -m visionmart doctor
exit $?
