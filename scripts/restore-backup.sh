#!/usr/bin/env bash
# VisionMart -- Restore from a backup (DevOps Toolkit Part 8).
#
# Restores a `backup/`-produced archive (visionmart-backup-*.zip, NOT
# compatible with the older scripts/backup.sh/restore.sh pair -- see
# docs/43_BACKUP_RECOVERY.md). Always: list -> verify checksum -> typed
# confirmation -> restore -> restart -> doctor. Never restores from an
# archive that fails verification, and never runs unattended (no --yes
# bypass for the final confirmation -- this is the one destructive
# action in this whole toolkit that always stops for a human).
#
# PostgreSQL restore is fully automated. MinIO uploads restore is
# automated only with --with-uploads (best-effort, additive to the
# bucket). monitoring.db restore is intentionally left as a manual,
# printed step -- see "Known limitations" in --help.
#
# Usage:
#   scripts/restore-backup.sh --list
#   scripts/restore-backup.sh --file visionmart-backup-2026-07-04-020000.zip [--with-uploads]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

ACTION_LIST=0
FILE=""
WITH_UPLOADS=0

usage() {
  cat <<'EOF'
VisionMart Restore

Usage:
  scripts/restore-backup.sh --list
  scripts/restore-backup.sh --file <visionmart-backup-*.zip> [--with-uploads]

Options:
  --list          List available backups (delegates to `backup.cli list`) and exit.
  --file NAME     The backup archive to restore, by filename (as shown by --list).
  --with-uploads  Also restore MinIO uploads from the archive (best-effort,
                  additive -- existing objects with the same name are
                  overwritten, nothing already in the bucket is deleted).
  -h, --help      Show this help.

What this does NOT automate (by design):
  - monitoring.db is NOT restored automatically (operational history, not
    business data -- restoring it needs a volume this script does not have
    write access to without extra docker-compose plumbing). The exact
    manual steps are printed at the end if you want to do it anyway.

Never restores from an archive that fails checksum/zip-integrity
verification, and always requires a typed confirmation before touching
the database -- this cannot be bypassed with --yes.
EOF
}

_args=("$@")
for i in "${!_args[@]}"; do
  case "${_args[$i]}" in
    --list) ACTION_LIST=1 ;;
    --file) [ $((i + 1)) -lt ${#_args[@]} ] && FILE="${_args[$((i + 1))]}" ;;
    --with-uploads) WITH_UPLOADS=1 ;;
    -h|--help) usage; exit "${EXIT_OK}" ;;
  esac
done

init_logging "$0"
require_env_file

log "Available backups"
dc run --rm backup-once python -m backup.cli list

if [ "${ACTION_LIST}" -eq 1 ]; then
  exit "${EXIT_OK}"
fi

if [ -z "${FILE}" ]; then
  error "No --file given. Pick one of the archives listed above and re-run with --file <name>."
  usage
  exit "${EXIT_VALIDATION_FAILED}"
fi

BACKUP_ID="${FILE#visionmart-backup-}"
BACKUP_ID="${BACKUP_ID%.zip}"
REMOTE_ZIP="/backups/${FILE}"
RESTORE_DIR="/backups/_restore_${BACKUP_ID}"

log "Verifying archive integrity and checksum"
if ! dc run --rm backup-once python -m backup.cli verify "${REMOTE_ZIP}"; then
  die "Verification failed -- refusing to restore from a corrupt or tampered archive." "${EXIT_VALIDATION_FAILED}"
fi
ok "Archive verified"

PG_USER="$(env_get POSTGRES_USER)"; PG_USER="${PG_USER:-visionmart}"
PG_DB="$(env_get POSTGRES_DB)"; PG_DB="${PG_DB:-visionmart}"

echo
warn "This will DROP AND RECREATE database '${PG_DB}' from ${FILE}."
warn "Backend, celery-worker, celery-beat, and ai-engine will be stopped during the restore."
if [ "${WITH_UPLOADS}" -eq 1 ]; then
  warn "MinIO uploads will also be restored (additive -- existing objects with the same name will be overwritten)."
fi
echo
read -r -p "Type the database name (${PG_DB}) to confirm: " typed
if [ "${typed}" != "${PG_DB}" ]; then
  die "Confirmation did not match -- aborting. Nothing was changed." "${EXIT_USER_ABORT}"
fi

log "Extracting archive inside the backups volume"
dc run --rm --entrypoint python backup-once -c \
  "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
  "${REMOTE_ZIP}" "${RESTORE_DIR}" \
  || die "Extraction failed." "${EXIT_GENERAL_ERROR}"
ok "Extracted to ${RESTORE_DIR} (inside the backups_data volume)"

log "Stopping backend, celery-worker, celery-beat, ai-engine (postgres stays up)"
dc stop backend celery-worker celery-beat ai-engine

log "Recreating database ${PG_DB}"
dc exec -T postgres psql -U "${PG_USER}" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"${PG_DB}\";" \
  -c "CREATE DATABASE \"${PG_DB}\" OWNER \"${PG_USER}\";" \
  || die "Failed to recreate the database -- backend/celery are still stopped, restart manually with: docker compose up -d backend celery-worker celery-beat ai-engine" "${EXIT_GENERAL_ERROR}"

log "Restoring PostgreSQL dump (postgres.sql)"
# The archive's zip root is a single day-labelled directory (e.g.
# "2026-07-04/", see backup/archive.py) -- discover its actual name
# rather than assuming it matches backup_id's date prefix exactly.
DAY_DIR="$(dc run --rm --entrypoint sh backup-once -c "ls ${RESTORE_DIR}" 2>/dev/null | tr -d '\r' | head -1)"
if [ -z "${DAY_DIR}" ]; then
  die "Could not locate the extracted archive contents inside ${RESTORE_DIR}." "${EXIT_GENERAL_ERROR}"
fi
dc run --rm --entrypoint cat backup-once "${RESTORE_DIR}/${DAY_DIR}/postgres.sql" \
  | dc exec -T postgres psql -U "${PG_USER}" -d "${PG_DB}" -v ON_ERROR_STOP=1 \
  || die "PostgreSQL restore failed." "${EXIT_GENERAL_ERROR}"
ok "PostgreSQL restored"

if [ "${WITH_UPLOADS}" -eq 1 ]; then
  log "Restoring MinIO uploads (best-effort, additive)"
  dc run --rm --entrypoint python backup-once -c '
import os, sys
from minio import Minio
root, bucket_prefix = sys.argv[1], "uploads"
client = Minio(
    os.environ.get("MINIO_ENDPOINT", "minio:9000"),
    access_key=os.environ.get("MINIO_ROOT_USER", "visionmart"),
    secret_key=os.environ.get("MINIO_ROOT_PASSWORD", ""),
    secure=os.environ.get("MINIO_USE_SSL", "false").strip().lower() in ("1", "true", "yes"),
)
bucket = os.environ.get("MINIO_BUCKET", "visionmart")
if not client.bucket_exists(bucket):
    client.make_bucket(bucket)
uploads_root = os.path.join(root, bucket_prefix)
count = 0
for dirpath, _dirs, files in os.walk(uploads_root):
    for fname in files:
        full = os.path.join(dirpath, fname)
        object_name = os.path.relpath(full, uploads_root).replace(os.sep, "/")
        client.fput_object(bucket, object_name, full)
        count += 1
print(f"Restored {count} object(s) to bucket {bucket!r}.")
' "${RESTORE_DIR}/${DAY_DIR}" \
    || warn "Uploads restore reported an error -- PostgreSQL restore above is unaffected."
fi

log "Restarting services"
dc up -d backend celery-worker celery-beat ai-engine

log "Verifying"
wait_for_http "http://127.0.0.1:$(env_get BACKEND_PORT || echo 8000)/health" 60 "Backend" || true
dc exec -T monitoring python -m visionmart doctor || warn "Doctor reported issues after restore -- review above."

echo
info "Extracted files were left at ${RESTORE_DIR} (inside the backups_data volume) in case you also want monitoring.db --"
info "scripts/cleanup.sh removes '_restore_*' scratch directories older than a day automatically, or delete it now with:"
info "  docker compose run --rm --entrypoint rm backup-once -rf ${RESTORE_DIR}"
info ""
info "monitoring.db was NOT restored automatically. To restore it manually while the scratch dir above still exists:"
info "  docker compose stop monitoring"
info "  docker run --rm -v visionmart_backups_data:/backups:ro -v visionmart_monitoring_data:/data alpine \\"
info "    sh -c 'cp ${RESTORE_DIR}/*/monitoring.db /data/monitoring.db'"
info "  docker compose up -d monitoring"
info "(Volume names above assume the default 'visionmart' compose project name -- confirm with: docker volume ls)"

ok "Restore complete from ${FILE}"
