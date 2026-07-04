#!/usr/bin/env bash
# VisionMart -- Cleanup (DevOps Toolkit Part 11).
#
# Safely reclaims disk space. Every action here is scoped to things that
# are provably safe to remove (dangling images, unused build cache,
# backups past their own configured retention, this toolkit's own old
# execution logs, stale restore scratch directories) -- this script
# NEVER removes a running/stopped container that belongs to this
# project, and NEVER touches a named data volume
# (postgres_data/redis_data/minio_data/monitoring_data/backups_data/
# ai_engine_weights/ai_engine_training), even if Docker reports it as
# "dangling" (which happens for every volume whenever `docker compose
# down` is used -- dangling does not mean disposable).
#
# Usage:
#   scripts/cleanup.sh [--images] [--build-cache] [--old-backups]
#                       [--old-logs] [--restore-scratch] [--volumes]
#                       [--all] [--days N] [--dry-run] [--yes]
#
# With no flags, runs the same set as --all (images, build-cache,
# old-backups, old-logs, restore-scratch) -- everything except
# --volumes, which must be requested explicitly because it is the only
# action here that touches anything Docker-volume-shaped.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib/common.sh"

# Never removed by --volumes, no matter what Docker reports for them.
declare -a PROTECTED_VOLUME_PATTERNS=(
  "postgres_data" "redis_data" "minio_data" "monitoring_data"
  "backups_data" "ai_engine_weights" "ai_engine_training"
)

DO_IMAGES=0
DO_BUILD_CACHE=0
DO_OLD_BACKUPS=0
DO_OLD_LOGS=0
DO_RESTORE_SCRATCH=0
DO_VOLUMES=0
DRY_RUN=0
DAYS=30
ANY_EXPLICIT=0

usage() {
  cat <<'EOF'
VisionMart Cleanup

Usage:
  scripts/cleanup.sh [options]

Options:
  --images            Remove dangling (untagged) Docker images.
  --build-cache       Remove unused Docker build cache.
  --old-backups       Apply backup retention (delegates to backup.cli cleanup).
  --old-logs          Remove this toolkit's own logs/devops/*.log older than --days.
  --restore-scratch   Remove restore-backup.sh scratch dirs (_restore_*) older than 1 day.
  --volumes           List dangling volumes NOT part of this project's known
                       data volumes, and offer to remove each individually.
                       Never touches postgres_data/redis_data/minio_data/
                       monitoring_data/backups_data/ai_engine_weights/
                       ai_engine_training under any circumstance.
  --all               Run every action above except --volumes (this is also
                       the default when no flags are given).
  --days N            Age threshold for --old-logs. Default: 30.
  --dry-run           Show what would be removed without removing anything.
  --yes               Assume "yes" for confirmations (--volumes still lists
                       candidates for review; --yes only skips the per-item
                       prompt, it never expands what is eligible).
  -h, --help          Show this help.
EOF
}

_args=("$@")
i=0
while [ "$i" -lt "${#_args[@]}" ]; do
  arg="${_args[$i]}"
  case "$arg" in
    --images) DO_IMAGES=1; ANY_EXPLICIT=1 ;;
    --build-cache) DO_BUILD_CACHE=1; ANY_EXPLICIT=1 ;;
    --old-backups) DO_OLD_BACKUPS=1; ANY_EXPLICIT=1 ;;
    --old-logs) DO_OLD_LOGS=1; ANY_EXPLICIT=1 ;;
    --restore-scratch) DO_RESTORE_SCRATCH=1; ANY_EXPLICIT=1 ;;
    --volumes) DO_VOLUMES=1; ANY_EXPLICIT=1 ;;
    --all) DO_IMAGES=1; DO_BUILD_CACHE=1; DO_OLD_BACKUPS=1; DO_OLD_LOGS=1; DO_RESTORE_SCRATCH=1; ANY_EXPLICIT=1 ;;
    --days) i=$((i + 1)); DAYS="${_args[$i]:-30}" ;;
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help) usage; exit "${EXIT_OK}" ;;
    *) error "Unknown option: $arg"; usage; exit "${EXIT_VALIDATION_FAILED}" ;;
  esac
  i=$((i + 1))
done

if [ "${ANY_EXPLICIT}" -eq 0 ]; then
  DO_IMAGES=1; DO_BUILD_CACHE=1; DO_OLD_BACKUPS=1; DO_OLD_LOGS=1; DO_RESTORE_SCRATCH=1
fi

init_logging "$0"
[ "${DRY_RUN}" -eq 1 ] && warn "--dry-run: no changes will be made"

if [ "${DO_IMAGES}" -eq 1 ]; then
  log "Dangling Docker images"
  if [ "${DRY_RUN}" -eq 1 ]; then
    docker images -f dangling=true
  else
    docker image prune -f
  fi
fi

if [ "${DO_BUILD_CACHE}" -eq 1 ]; then
  log "Unused Docker build cache"
  if [ "${DRY_RUN}" -eq 1 ]; then
    docker builder du 2>/dev/null || info "docker builder du not available on this Docker version"
  else
    docker builder prune -f
  fi
fi

if [ "${DO_OLD_BACKUPS}" -eq 1 ]; then
  log "Backup retention (delegates to backup.cli, respects BACKUP_RETENTION_DAYS)"
  if [ "${DRY_RUN}" -eq 1 ]; then
    dc run --rm backup-once python -m backup.cli list
    info "(dry-run: not running 'backup.cli cleanup')"
  else
    dc run --rm backup-once python -m backup.cli cleanup
  fi
fi

if [ "${DO_OLD_LOGS}" -eq 1 ]; then
  log "This toolkit's own execution logs older than ${DAYS} days (${DEVOPS_LOG_DIR})"
  if [ -d "${DEVOPS_LOG_DIR}" ]; then
    if [ "${DRY_RUN}" -eq 1 ]; then
      find "${DEVOPS_LOG_DIR}" -maxdepth 1 -type f -name '*.log' -mtime "+${DAYS}" -print
    else
      removed_count="$(find "${DEVOPS_LOG_DIR}" -maxdepth 1 -type f -name '*.log' -mtime "+${DAYS}" -print -delete | wc -l)"
      ok "Removed ${removed_count} old devops log file(s)"
    fi
  else
    info "No ${DEVOPS_LOG_DIR} yet -- nothing to clean"
  fi
fi

if [ "${DO_RESTORE_SCRATCH}" -eq 1 ]; then
  log "Stale restore-backup.sh scratch directories (older than 1 day, inside backups_data)"
  if [ "${DRY_RUN}" -eq 1 ]; then
    dc run --rm --entrypoint sh backup-once -c "find /backups -maxdepth 1 -name '_restore_*' -mtime +1" 2>/dev/null || true
  else
    dc run --rm --entrypoint sh backup-once -c "find /backups -maxdepth 1 -name '_restore_*' -mtime +1 -print -exec rm -rf {} +" 2>/dev/null || true
  fi
fi

if [ "${DO_VOLUMES}" -eq 1 ]; then
  log "Dangling Docker volumes (excluding this project's known data volumes)"
  mapfile -t candidates < <(docker volume ls -f dangling=true --format '{{.Name}}' 2>/dev/null || true)
  safe_candidates=()
  for v in "${candidates[@]}"; do
    protected=0
    for pattern in "${PROTECTED_VOLUME_PATTERNS[@]}"; do
      case "$v" in
        *"${pattern}"*) protected=1; break ;;
      esac
    done
    if [ "${protected}" -eq 1 ]; then
      info "Skipping ${v} (matches a protected VisionMart data volume pattern)"
    else
      safe_candidates+=("$v")
    fi
  done

  if [ "${#safe_candidates[@]}" -eq 0 ]; then
    ok "No removable dangling volumes found"
  else
    for v in "${safe_candidates[@]}"; do
      if [ "${DRY_RUN}" -eq 1 ]; then
        info "Would remove volume: ${v}"
        continue
      fi
      if confirm "Remove dangling volume '${v}'?"; then
        docker volume rm "${v}" && ok "Removed ${v}" || warn "Could not remove ${v} (still in use?)"
      else
        info "Kept ${v}"
      fi
    done
  fi
fi

ok "Cleanup finished"
