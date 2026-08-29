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

# Cổng backend đọc từ .env, không cứng hoá. Trước đây script hỏi cổng
# 18000 trong khi docker-compose expose ${BACKEND_PORT:-8000} — nên bước
# chờ backend KHÔNG BAO GIỜ thành công, script `die` sau 30s, và migration
# ở ngay sau đó chưa từng được chạy. Lỗi này im lặng: deploy trông như chỉ
# "chờ hơi lâu", còn schema thì lặng lẽ tụt lại sau code.
_env_get() {
  [ -f "$REPO_DIR/.env" ] || return 0
  grep -E "^$1=" "$REPO_DIR/.env" 2>/dev/null | tail -n1 | cut -d= -f2-     | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//' || true
}
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

# Có cần build lại ai-engine không?
#
# So THỜI ĐIỂM BUILD của image đang chạy với COMMIT CUỐI chạm vào
# ai-engine/. Cách này đúng bất kể code tới bằng đường nào — pull, chuyển
# nhánh, hay sửa tay.
#
# Bản trước lấy diff của chính lệnh `git pull`, và nó SAI trong đúng
# trường hợp phổ biến nhất: người dùng `git checkout v3` trước rồi mới
# chạy deploy. Khi đó pull không có gì mới, diff rỗng, và ai-engine lặng
# lẽ tiếp tục chạy image cũ — biểu hiện ra ngoài là backend gọi
# /ai/vision-config nhận 404 vì router đó chỉ tồn tại trong code mới.
#
# Không phải lúc nào cũng build, vì image ai-engine mang torch +
# ultralytics và mất vài phút.
ai_engine_stale() {
  local img_id img_ts code_ts
  img_id="$($COMPOSE images -q ai-engine 2>/dev/null | head -n1)"
  # Chưa có image thì chắc chắn phải build.
  [ -n "$img_id" ] || return 0
  img_ts="$(docker inspect -f '{{.Created}}' "$img_id" 2>/dev/null)" || return 0
  img_ts="$(date -d "$img_ts" +%s 2>/dev/null)" || return 0
  code_ts="$(git log -1 --format=%ct -- ai-engine/ 2>/dev/null)" || return 0
  [ -n "$code_ts" ] || return 1
  [ "$code_ts" -gt "$img_ts" ]
}

if [ "$WITH_AI_ENGINE" -eq 1 ]; then
  SERVICES="$SERVICES ai-engine"
elif ai_engine_stale; then
  warn "image ai-engine cũ hơn code — build lại trong lần deploy này"
  SERVICES="$SERVICES ai-engine"
fi

log "Building images: $SERVICES"
$COMPOSE build $SERVICES

log "Restarting containers: $SERVICES"
$COMPOSE up -d $SERVICES

BACKEND_PORT="$(_env_get BACKEND_PORT)"; BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

# 120s chứ không phải 30s: sau khi build lại image, backend phải nạp toàn
# bộ ORM + router trước khi trả /health, và trên VPS nhỏ việc đó thường
# mất hơn 30 giây. Ngưỡng quá ngắn biến một lần khởi động bình thường
# thành lỗi deploy.
log "Waiting for backend to be ready (${BACKEND_URL}, tối đa 120s)"
BACKEND_READY=0
for i in $(seq 1 120); do
  if curl -sf "${BACKEND_URL}/health" >/dev/null 2>&1; then
    ok "Backend healthy sau ${i}s"
    BACKEND_READY=1
    break
  fi
  sleep 1
done

if [ "$BACKEND_READY" -eq 0 ]; then
  warn "Backend chưa trả /health sau 120s — vẫn thử migrate qua docker exec"
  warn "  (nếu migrate lỗi: docker compose logs --tail=200 backend)"
fi

log "Applying database migrations"
if $COMPOSE exec -T backend alembic upgrade head; then
  ok "Migration xong: $($COMPOSE exec -T backend alembic current 2>/dev/null | tail -n1)"
else
  die "Migration THẤT BẠI — code đã lên nhưng schema thì chưa. Sửa rồi chạy lại: docker compose exec backend alembic upgrade head"
fi

# Nginx cache IP nội bộ Docker của upstream (backend/ai-engine) trong bộ
# nhớ worker process — khi build ở trên recreate container, IP đổi nhưng
# nginx không tự biết, nên request tiếp tục bay vào IP CŨ và ăn 502 Bad
# Gateway cho tới khi có ai restart nginx thủ công. Xảy ra 2 lần liên tiếp
# trong thực tế (deploy xong -> login 502 -> phải restart nginx tay) nên
# đưa hẳn vào đây thay vì dựa vào người vận hành nhớ làm.
if $COMPOSE ps --services 2>/dev/null | grep -qx nginx; then
  log "Restarting nginx (làm mới IP upstream sau khi container backend/ai-engine đổi)"
  $COMPOSE restart nginx
fi

log "Container status"
$COMPOSE ps

log "Registered API routes"
curl -sS "${BACKEND_URL}/openapi.json" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); [print(p) for p in sorted(d['paths'].keys())]"

ok "Deploy finished"
