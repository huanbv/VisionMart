#!/usr/bin/env bash
# Full backup: Postgres (pg_dump custom format) + MinIO (/data tarball).
# Intended to run from the repo root on the VPS, e.g. via cron.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

: "${POSTGRES_USER:=visionmart}"
: "${POSTGRES_DB:=visionmart}"
: "${BACKUP_DIR:=/var/backups/visionmart}"
: "${BACKUP_RETENTION_DAYS:=14}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR}/${TS}"
mkdir -p "${DEST}"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

log "Backing up to ${DEST}"

log "Dumping Postgres database ${POSTGRES_DB}"
docker compose exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc \
    > "${DEST}/postgres.dump"

log "Archiving MinIO /data"
docker compose exec -T minio tar -C /data -cf - . \
    | gzip -c > "${DEST}/minio.tar.gz"

echo "${TS}" > "${DEST}/BACKUP_ID"
{
    echo "backup_id=${TS}"
    echo "postgres_user=${POSTGRES_USER}"
    echo "postgres_db=${POSTGRES_DB}"
    echo "postgres_dump_bytes=$(stat -c%s "${DEST}/postgres.dump")"
    echo "minio_archive_bytes=$(stat -c%s "${DEST}/minio.tar.gz")"
} > "${DEST}/manifest.txt"

log "Pruning backups older than ${BACKUP_RETENTION_DAYS} days"
find "${BACKUP_DIR}" -maxdepth 1 -mindepth 1 -type d \
    -mtime "+${BACKUP_RETENTION_DAYS}" -print -exec rm -rf {} \;

log "Backup complete: ${DEST}"
