#!/usr/bin/env bash
# VisionMart -- Run a backup now (DevOps Toolkit Part 8).
#
# Thin wrapper around the existing backup/cli.py (`python -m backup.cli`)
# -- all backup logic (pg_dump, SQLite online backup, MinIO download,
# config copy, zip + checksum + verify) already lives in backup/, this
# script only orchestrates: run, then report size/location/checksum
# clearly, then apply retention as a separate explicit step.
#
# Usage:
#   scripts/backup-now.sh [options]
#
# Options:
#   --skip-retention   Only create the backup, don't prune old ones.
#   -h, --help         Show this help and exit.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

SKIP_RETENTION=0
for arg in "$@"; do
  case "$arg" in
    --skip-retention) SKIP_RETENTION=1 ;;
    -h|--help)
      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
      exit "${EXIT_OK}"
      ;;
  esac
done

init_logging "$0"
require_env_file

log "Running backup (python -m backup.cli run)"
output="$(dc run --rm backup-once python -m backup.cli run --skip-cleanup)"
status=$?
echo "${output}"

if [ "${status}" -ne 0 ]; then
  error "Backup command exited non-zero -- see manifest above for which source(s) failed."
fi

if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found on host -- skipping the parsed summary below (the raw manifest above already has everything)."
else
  summary="$(printf '%s' "${output}" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
size_mb = d.get("zip_size_bytes", 0) / (1024 * 1024)
print(f"backup_id={d.get(\"backup_id\")}")
print(f"zip_path={d.get(\"zip_path\")}")
print(f"zip_size_mb={size_mb:.1f}")
print(f"sha256={d.get(\"sha256\")}")
print(f"verified={d.get(\"verified\")}")
print(f"overall_ok={d.get(\"overall_ok\")}")
print(f"duration_seconds={d.get(\"duration_seconds\")}")
' 2>/dev/null)"

  if [ -n "${summary}" ]; then
    log "Backup summary"
    echo "${summary}" | sed 's/^/  /'
    if echo "${summary}" | grep -q "overall_ok=True"; then
      ok "Backup succeeded and passed verification"
    else
      error "Backup did NOT pass verification (overall_ok=False) -- see sources above for the failing one."
    fi
  else
    warn "Could not parse the manifest JSON above -- check backup-once container logs."
  fi
fi

if [ "${SKIP_RETENTION}" -eq 0 ]; then
  log "Applying retention policy"
  dc run --rm backup-once python -m backup.cli cleanup
else
  info "Skipping retention (--skip-retention)"
fi

exit "${status}"
