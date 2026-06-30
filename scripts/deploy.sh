#!/usr/bin/env bash
# VisionMart — VPS deploy script.
#
# Usage (on VPS, from any directory):
#   sudo bash /var/www/visionmart/scripts/deploy.sh
#
# What it does:
#   1. cd into the repo
#   2. git pull --ff-only
#   3. rebuild backend + celery-worker images (code is baked in)
#   4. restart backend + celery-worker containers
#   5. apply alembic migrations
#   6. print final health + route summary
#
# Frontend is served by Vite/Nginx and picks up changes automatically;
# this script does NOT touch the frontend container by default. Pass
# --with-frontend to also rebuild the frontend image.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/var/www/visionmart}"
COMPOSE="docker compose"
WITH_FRONTEND=0

for arg in "$@"; do
  case "$arg" in
    --with-frontend) WITH_FRONTEND=1 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

log()  { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ -d "$REPO_DIR/.git" ] || die "Repo not found at $REPO_DIR"
cd "$REPO_DIR"

log "Pulling latest code"
BEFORE_SHA="$(git rev-parse HEAD)"
git fetch --quiet origin
git pull --ff-only
AFTER_SHA="$(git rev-parse HEAD)"

if [ "$BEFORE_SHA" = "$AFTER_SHA" ]; then
  ok "Already up to date ($AFTER_SHA)"
else
  ok "Updated $BEFORE_SHA -> $AFTER_SHA"
  log "Changed files"
  git --no-pager diff --name-only "$BEFORE_SHA" "$AFTER_SHA"
fi

SERVICES="backend celery-worker"
if [ "$WITH_FRONTEND" -eq 1 ]; then
  SERVICES="$SERVICES frontend"
fi

log "Building images: $SERVICES"
$COMPOSE build $SERVICES

log "Restarting containers: $SERVICES"
$COMPOSE up -d $SERVICES

log "Waiting for backend to be ready"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:18000/health >/dev/null 2>&1; then
    ok "Backend healthy"
    break
  fi
  if [ "$i" -eq 30 ]; then
    die "Backend did not become healthy in 30s — check: docker compose logs --tail=200 backend"
  fi
  sleep 1
done

log "Applying database migrations"
$COMPOSE exec -T backend alembic upgrade head

log "Container status"
$COMPOSE ps

log "Registered API routes"
curl -sS http://127.0.0.1:18000/openapi.json \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(p) for p in sorted(d['paths'].keys())]"

ok "Deploy finished"
