#!/usr/bin/env bash
# Restore a full backup produced by scripts/backup.sh.
# Usage:
#   scripts/restore.sh <backup_dir>
# Example:
#   scripts/restore.sh /var/backups/visionmart/20260701T030000Z
#
# WARNING: destructive. Drops and recreates the target Postgres database
# and wipes the MinIO /data volume before restoring.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup_dir>" >&2
    exit 2
fi
SRC="$1"

if [ ! -f "${SRC}/postgres.dump" ] || [ ! -f "${SRC}/minio.tar.gz" ]; then
    echo "Missing postgres.dump or minio.tar.gz in ${SRC}" >&2
    exit 2
fi

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${POSTGRES_USER:=visionmart}"
: "${POSTGRES_DB:=visionmart}"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

if [ "${RESTORE_FORCE:-0}" != "1" ]; then
    echo "This will DROP database ${POSTGRES_DB} and WIPE MinIO /data."
    read -r -p "Type the database name to confirm: " confirm
    if [ "${confirm}" != "${POSTGRES_DB}" ]; then
        echo "Confirmation mismatch, aborting." >&2
        exit 1
    fi
fi

log "Stopping backend, workers, ai-engine"
docker compose stop backend celery-worker celery-beat ai-engine

log "Recreating database ${POSTGRES_DB}"
docker compose exec -T postgres \
    psql -U "${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 -c \
    "DROP DATABASE IF EXISTS \"${POSTGRES_DB}\";"
docker compose exec -T postgres \
    psql -U "${POSTGRES_USER}" -d postgres -v ON_ERROR_STOP=1 -c \
    "CREATE DATABASE \"${POSTGRES_DB}\" OWNER \"${POSTGRES_USER}\";"

log "Restoring Postgres dump"
docker compose exec -T postgres \
    pg_restore -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --clean --if-exists \
    < "${SRC}/postgres.dump"

log "Wiping MinIO /data"
docker compose exec -T minio sh -c 'rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null || true'

log "Restoring MinIO archive"
gunzip -c "${SRC}/minio.tar.gz" \
    | docker compose exec -T minio tar -C /data -xf -

log "Restarting services"
docker compose up -d backend celery-worker celery-beat ai-engine

log "Restore complete from ${SRC}"
