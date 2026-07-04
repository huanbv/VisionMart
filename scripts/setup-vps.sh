#!/usr/bin/env bash
# =====================================================================
# VisionMart -- All-in-one VPS setup (Docker + .env + SSL + stack + DB)
#
# Chạy 1 LẦN trên VPS Ubuntu, từ BÊN TRONG thư mục repo đã có code:
#
#   cd /var/opt/VisionMart        # (hoặc nơi bạn đặt code)
#   sudo bash scripts/setup-vps.sh
#
# Script tự làm toàn bộ:
#   1. Cài gói cơ bản + Docker Engine + Compose plugin (bỏ qua nếu đã có)
#   2. Mở firewall 22/80/443 (nếu có ufw)
#   3. Tạo .env production + sinh secrets (generate-secrets.sh --yes)
#   4. Cài certbot, xin chứng chỉ Let's Encrypt cho $DOMAIN
#   5. Sinh nginx config HTTPS + docker-compose.override.yml mount cert
#   6. docker compose build + up -d
#   7. Migrate DB (alembic) + seed admin
#
# Idempotent: chạy lại an toàn, không ghi đè secret/cert đã có.
# =====================================================================
set -uo pipefail

# ----------------------- Cấu hình -----------------------------------
DOMAIN="${DOMAIN:-visionmart.thehuan.com}"
LE_EMAIL="${LE_EMAIL:-huanbv9x@gmail.com}"
SKIP_SSL="${SKIP_SSL:-0}"          # SKIP_SSL=1 để bỏ qua SSL (chạy HTTP)

# APP_DIR = thư mục repo chứa script này (không cần git clone)
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

C_G='\033[1;32m'; C_C='\033[1;36m'; C_Y='\033[1;33m'; C_R='\033[1;31m'; C_0='\033[0m'
log()  { printf "\n${C_C}==> %s${C_0}\n" "$*"; }
ok()   { printf "${C_G}  OK %s${C_0}\n" "$*"; }
warn() { printf "${C_Y}  !  %s${C_0}\n" "$*" >&2; }
die()  { printf "${C_R}  X  %s${C_0}\n" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Phải chạy bằng root: sudo bash scripts/setup-vps.sh"
[ -f "${APP_DIR}/docker-compose.yml" ] || die "Không thấy docker-compose.yml trong ${APP_DIR} -- chạy script từ trong thư mục repo."
cd "${APP_DIR}"
log "VisionMart VPS Setup -- app dir: ${APP_DIR}, domain: ${DOMAIN}"

# ----------------------- 1. Gói cơ bản + Docker ----------------------
log "Cài gói cơ bản"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl wget jq unzip openssl ca-certificates gnupg lsb-release >/dev/null
ok "Gói cơ bản OK"

log "Cài Docker Engine + Compose plugin"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  ok "Đã có $(docker --version)"
else
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
  ok "Docker đã cài"
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || die "Docker daemon không chạy -- xem: systemctl status docker"

# ----------------------- 2. Firewall --------------------------------
if command -v ufw >/dev/null 2>&1; then
  log "Mở firewall 22/80/443"
  ufw allow 22/tcp >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  ufw status | grep -q "Status: active" || warn "ufw chưa bật (chạy 'ufw --force enable' nếu muốn)."
  ok "Firewall OK"
fi

# Giải phóng port 80/443 nếu nginx/apache của HOST đang chiếm
for svc in nginx apache2; do
  if systemctl is-active --quiet "$svc" 2>/dev/null; then
    warn "Host đang chạy $svc chiếm port 80 -- dừng & disable để nhường cho Docker."
    systemctl stop "$svc"; systemctl disable "$svc" >/dev/null 2>&1
  fi
done

# ----------------------- 3. .env + secrets --------------------------
log "Tạo .env + sinh secrets"
[ -f .env ] || { cp .env.example .env; ok "Đã tạo .env từ .env.example"; }
chmod 600 .env

if [ -f scripts/generate-secrets.sh ]; then
  export VISIONMART_APP_DIR="${APP_DIR}"
  bash scripts/generate-secrets.sh --yes || warn "generate-secrets.sh báo lỗi -- kiểm tra lại .env / secrets/ bằng tay."
fi

# Vá các giá trị production (chỉ sửa nếu key tồn tại trong .env)
set_env() { grep -q "^$1=" .env && sed -i "s|^$1=.*|$1=$2|" .env; }
set_env APP_ENV               "production"
set_env APP_DEBUG             "false"
set_env BACKEND_CORS_ORIGINS  "https://${DOMAIN}"
set_env PUBLIC_APP_BASE_URL   "https://${DOMAIN}"
set_env VITE_API_BASE_URL     "https://${DOMAIN}/api/v1"
set_env VITE_WS_BASE_URL      "wss://${DOMAIN}/ws"
set_env MINIO_PUBLIC_ENDPOINT "${DOMAIN}"
set_env MINIO_PUBLIC_USE_SSL  "true"
ok ".env đã cấu hình cho production (${DOMAIN})"

# JWT keypair (nếu generate-secrets.sh chưa tạo)
if [ ! -f secrets/jwt_private.pem ]; then
  mkdir -p secrets
  openssl genpkey -algorithm RSA -out secrets/jwt_private.pem -pkeyopt rsa_keygen_bits:2048 2>/dev/null
  openssl rsa -in secrets/jwt_private.pem -pubout -out secrets/jwt_public.pem 2>/dev/null
  chmod 600 secrets/jwt_*.pem
  ok "Đã sinh cặp khoá JWT RS256 vào ./secrets/"
fi

# ----------------------- 4. SSL (Let's Encrypt) ----------------------
CERT_DIR="/etc/letsencrypt/live/${DOMAIN}"
HAVE_CERT=0
if [ "${SKIP_SSL}" = "1" ]; then
  warn "SKIP_SSL=1 -- bỏ qua SSL, chạy HTTP thuần."
else
  log "Xin chứng chỉ Let's Encrypt cho ${DOMAIN}"
  apt-get install -y -qq certbot >/dev/null
  mkdir -p /var/www/certbot
  if [ -f "${CERT_DIR}/fullchain.pem" ]; then
    ok "Chứng chỉ đã tồn tại -- dùng lại."
    HAVE_CERT=1
  else
    # Kiểm tra DNS trỏ đúng IP chưa
    VPS_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
    DNS_IP="$(getent hosts "${DOMAIN}" | awk '{print $1}' | head -1)"
    if [ -n "${DNS_IP}" ] && [ "${DNS_IP}" != "${VPS_IP}" ]; then
      warn "DNS ${DOMAIN} -> ${DNS_IP} nhưng IP VPS là ${VPS_IP}. Certbot có thể fail."
    fi
    # Port 80 phải trống khi dùng standalone
    docker compose stop nginx >/dev/null 2>&1 || true
    if certbot certonly --standalone -d "${DOMAIN}" \
         --agree-tos -m "${LE_EMAIL}" --no-eff-email --non-interactive \
         --pre-hook  "cd ${APP_DIR} && docker compose stop nginx || true" \
         --post-hook "cd ${APP_DIR} && docker compose start nginx || true"; then
      ok "Đã cấp chứng chỉ (tự gia hạn qua certbot.timer)."
      HAVE_CERT=1
    else
      warn "Certbot FAIL -- tiếp tục chạy HTTP. Kiểm tra DNS rồi chạy lại script."
    fi
  fi
fi

# ----------------------- 5. Nginx HTTPS + compose override -----------
if [ "${HAVE_CERT}" = "1" ]; then
  log "Sinh nginx config HTTPS"
  cat > docker/nginx/conf.d/zz-ssl.conf <<EOF
# Sinh tự động bởi scripts/setup-vps.sh -- HTTPS cho ${DOMAIN}
server {
    listen 80;
    server_name ${DOMAIN};
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl;
    http2 on;
    server_name ${DOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 60s;
    }
    location /ws/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 3600s;
    }
    location = /health { access_log off; proxy_pass http://backend:8000/health; }
    location /visionmart/ {
        proxy_pass http://minio:9000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        client_max_body_size 100m;
        proxy_read_timeout 300s;
    }
    location / {
        proxy_pass http://frontend:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        # Vite dev server HMR websocket
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

  cat > docker-compose.override.yml <<'EOF'
# Sinh tự động bởi scripts/setup-vps.sh -- mount chứng chỉ vào nginx
services:
  nginx:
    volumes:
      - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./docker/nginx/conf.d:/etc/nginx/conf.d:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - /var/www/certbot:/var/www/certbot:ro
EOF
  ok "nginx HTTPS + docker-compose.override.yml đã sẵn sàng"
fi

# ----------------------- 6. Build + up -------------------------------
log "Build image (lần đầu có thể mất 10-20 phút)"
docker compose build || die "docker compose build FAIL -- xem log lỗi phía trên."
log "Khởi động stack"
docker compose up -d --remove-orphans || die "docker compose up FAIL."

log "Chờ postgres/backend healthy (tối đa 3 phút)"
for i in $(seq 1 36); do
  st="$(docker inspect -f '{{.State.Health.Status}}' visionmart-backend 2>/dev/null || echo starting)"
  [ "$st" = "healthy" ] && break
  sleep 5
done
[ "${st:-}" = "healthy" ] && ok "Backend healthy" || warn "Backend chưa healthy -- xem: docker compose logs --tail 50 backend"

# ----------------------- 7. Migrate + seed ---------------------------
log "Migrate database (alembic upgrade head)"
docker compose run --rm backend alembic upgrade head || die "Migration FAIL -- xem lỗi phía trên."
ok "Database schema OK"

log "Seed organization/roles/admin (idempotent)"
docker compose run --rm backend python -m app.scripts.seed_initial || warn "Seed lỗi -- có thể đã seed trước đó."

# ----------------------- Tổng kết ------------------------------------
log "HOÀN TẤT"
docker compose ps
echo
if [ "${HAVE_CERT}" = "1" ]; then
  ok "Truy cập: https://${DOMAIN}"
else
  ok "Truy cập: http://${DOMAIN} (chưa có SSL -- chạy lại script sau khi DNS trỏ đúng)"
fi
ADMIN_PW="$(grep '^SEED_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
ok "Admin: $(grep '^SEED_ADMIN_EMAIL=' .env | cut -d= -f2-) / ${ADMIN_PW:-<xem .env>}"
echo "  Lệnh hữu ích: docker compose ps | logs -f backend | restart nginx"
