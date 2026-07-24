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
#
# ai-engine is rebuilt automatically when the pulled diff touches
# ai-engine/ ; pass --with-ai-engine to force it.

set -euo pipefail

# Mặc định là chính thư mục repo chứa script này, không phải một đường dẫn
# đoán trước. Trước đây script cứng hoá /var/www/visionmart, nên khi repo
# được đặt ở nơi khác (/var/opt/visionmart chẳng hạn) thì deploy chết ngay
# ở bước đầu — dù người dùng đang đứng đúng trong repo và gọi đúng script
# của repo đó. Cùng cách xác định mà setup-vps.sh đang dùng.
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE="docker compose"
WITH_FRONTEND=0
WITH_AI_ENGINE=0

for arg in "$@"; do
  case "$arg" in
    --with-frontend) WITH_FRONTEND=1 ;;
    --with-ai-engine) WITH_AI_ENGINE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
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

# Rebuild ai-engine when its code changed. Previously this script only
# ever rebuilt backend + celery-worker, so an ai-engine change silently
# kept running the OLD image — and after a release that also adds backend
# migrations (as v3 does), that leaves the two halves on different
# versions, which is worse than not deploying at all. Detected from the
# diff rather than always rebuilt, because the ai-engine image carries
# torch/ultralytics and takes minutes to build.
if [ "$WITH_AI_ENGINE" -eq 1 ]; then
  SERVICES="$SERVICES ai-engine"
elif [ "$BEFORE_SHA" != "$AFTER_SHA" ] && \
     git --no-pager diff --name-only "$BEFORE_SHA" "$AFTER_SHA" | grep -q '^ai-engine/'; then
  warn "ai-engine code changed — including it in this deploy"
  SERVICES="$SERVICES ai-engine"
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
