# VisionMart — Hướng dẫn Deploy lên VPS

> Tài liệu hướng dẫn triển khai mã nguồn **VisionMart** lên một VPS đơn (Tier 1)
> theo mô hình **Docker Compose** đã được mô tả trong
> [docs/07_DEPLOYMENT_PLAN.md](docs/07_DEPLOYMENT_PLAN.md).

| Hạng mục       | Giá trị                                           |
| -------------- | ------------------------------------------------- |
| Domain         | `visionmart.thehuan.com`                          |
| VPS IP         | `160.22.122.88`                                   |
| OS             | Ubuntu 22.04 LTS                                  |
| SSH user       | `root`                                            |
| Deploy mode    | Docker Compose (single-host, Tier 1)              |
| GPU            | Không — chạy **CPU-only** (ONNX Runtime CPU)      |
| TLS            | Let's Encrypt qua Certbot (HTTP-01 challenge)     |
| Repository     | https://github.com/huanbv/VisionMart              |
| Branch deploy  | `main`                                            |
| App path       | `/opt/visionmart`                                 |
| Data path      | `/var/lib/visionmart`                             |

---

## 0. Yêu cầu trước khi bắt đầu

- Đã trỏ DNS record **A** `visionmart.thehuan.com → 160.22.122.88` (TTL ≤ 300s).
- Đã có quyền SSH root vào VPS bằng key (khuyến nghị) hoặc password.
- VPS tối thiểu: **4 vCPU / 8 GB RAM / 80 GB SSD** cho demo CPU-only.
  Khuyến nghị **8 vCPU / 16 GB RAM / 200 GB SSD** nếu chạy 2–4 camera.
- Cổng cần mở trên firewall public: **22, 80, 443**.

---

## 1. SSH vào VPS

```bash
ssh root@160.22.122.88
```

> Nếu chưa thiết lập key, sau khi vào lần đầu nên copy public key lên VPS:
>
> ```bash
> # chạy ở máy local
> ssh-copy-id root@160.22.122.88
> ```

---

## 2. Cập nhật hệ thống & cài gói cơ bản

```bash
apt update && apt upgrade -y
apt install -y \
    ca-certificates curl gnupg lsb-release \
    git ufw fail2ban htop unzip jq \
    software-properties-common
timedatectl set-timezone Asia/Ho_Chi_Minh
```

---

## 3. Tạo user deploy không phải root (khuyến nghị)

```bash
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

Sau đó tắt SSH password & root login:

```bash
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl restart sshd
```

> Từ bước này trở đi, login bằng `ssh deploy@160.22.122.88` và dùng `sudo`.

---

## 4. Cấu hình firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp        # SSH
ufw allow 80/tcp        # HTTP (Let's Encrypt + redirect)
ufw allow 443/tcp       # HTTPS
ufw --force enable
ufw status verbose
```

Khởi động `fail2ban` để chống brute-force SSH:

```bash
systemctl enable --now fail2ban
```

---

## 5. Cài Docker Engine + Compose plugin

```bash
# Gỡ bản cũ nếu có
apt remove -y docker docker-engine docker.io containerd runc || true

# Kho Docker chính chủ
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install -y docker-ce docker-ce-cli containerd.io \
               docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker
usermod -aG docker deploy   # logout/login lại để áp dụng
docker version
docker compose version
```

---

## 6. Cài Nginx + Certbot (TLS termination ngoài Docker)

> VisionMart đặt **Nginx 1.27-alpine** trong Compose, nhưng cấp chứng chỉ
> Let's Encrypt qua **HTTP-01** đòi hỏi cổng 80 sẵn sàng trước khi container
> chạy. Cách đơn giản nhất là dùng **Certbot standalone** trên host để xin cert,
> rồi mount vào container Nginx.

```bash
apt install -y certbot
```

Xin chứng chỉ ban đầu (Nginx container CHƯA chạy):

```bash
certbot certonly --standalone \
    -d visionmart.thehuan.com \
    --agree-tos -m admin@thehuan.com \
    --no-eff-email --non-interactive
```

Chứng chỉ sẽ nằm tại:

```
/etc/letsencrypt/live/visionmart.thehuan.com/fullchain.pem
/etc/letsencrypt/live/visionmart.thehuan.com/privkey.pem
```

Tự động gia hạn:

```bash
systemctl list-timers | grep certbot   # đảm bảo certbot.timer đang active
```

Thêm hook reload Nginx container sau khi renew:

```bash
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/bin/bash
cd /opt/visionmart && docker compose exec -T nginx nginx -s reload || true
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

---

## 7. Clone mã nguồn

```bash
sudo mkdir -p /opt/visionmart /var/lib/visionmart
sudo chown -R deploy:deploy /opt/visionmart /var/lib/visionmart

cd /opt
git clone https://github.com/huanbv/VisionMart.git visionmart
cd /opt/visionmart
git checkout main
```

> Nếu repository là private, dùng deploy key SSH thay vì HTTPS.

---

## 8. Cấu hình biến môi trường

```bash
cd /opt/visionmart
cp .env.example .env
nano .env
```

Các biến **bắt buộc** rà soát kỹ:

| Biến                          | Giá trị gợi ý cho VPS này                                |
| ----------------------------- | -------------------------------------------------------- |
| `APP_ENV`                     | `production`                                             |
| `APP_DOMAIN`                  | `visionmart.thehuan.com`                                 |
| `APP_BASE_URL`                | `https://visionmart.thehuan.com`                         |
| `API_BASE_URL`                | `https://visionmart.thehuan.com/api/v1`                  |
| `WS_BASE_URL`                 | `wss://visionmart.thehuan.com/ws`                        |
| `POSTGRES_USER`               | `visionmart`                                             |
| `POSTGRES_PASSWORD`           | **sinh mật khẩu mạnh** (`openssl rand -base64 32`)       |
| `POSTGRES_DB`                 | `visionmart`                                             |
| `REDIS_PASSWORD`              | **sinh mật khẩu mạnh**                                   |
| `JWT_PRIVATE_KEY` / `_PUBLIC` | Sinh cặp khoá RS256 (xem mục 8.1)                        |
| `MINIO_ROOT_USER`             | `visionmart`                                             |
| `MINIO_ROOT_PASSWORD`         | **sinh mật khẩu mạnh**                                   |
| `AI_RUNTIME`                  | `cpu`                                                    |
| `AI_MODEL_VARIANT`            | `yolov8s` (CPU-only, demo 3–5 fps)                       |
| `CORS_ALLOWED_ORIGINS`        | `https://visionmart.thehuan.com`                         |
| `SECURE_COOKIES`              | `true`                                                   |
| `LOG_LEVEL`                   | `INFO`                                                   |

> Không commit `.env` lên git. File này phải có `chmod 600`.

```bash
chmod 600 .env
```

### 8.1 Sinh cặp khoá JWT RS256

```bash
mkdir -p /opt/visionmart/secrets
openssl genpkey -algorithm RSA -out /opt/visionmart/secrets/jwt_private.pem \
    -pkeyopt rsa_keygen_bits:2048
openssl rsa -in  /opt/visionmart/secrets/jwt_private.pem \
            -pubout -out /opt/visionmart/secrets/jwt_public.pem
chmod 600 /opt/visionmart/secrets/jwt_*.pem
```

Trỏ trong `.env`:

```
JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private.pem
JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public.pem
```

---

## 9. Chuẩn bị Nginx config (mount cert host vào container)

`deploy/nginx/visionmart.conf` (đã có sẵn trong repo) cần đảm bảo:

```nginx
server {
    listen 80;
    server_name visionmart.thehuan.com;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name visionmart.thehuan.com;

    ssl_certificate     /etc/letsencrypt/live/visionmart.thehuan.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/visionmart.thehuan.com/privkey.pem;

    # security headers, gzip, proxy timeouts… (xem 08_SECURITY_GUIDELINE)

    location /api/   { proxy_pass http://backend:8000; ... }
    location /ws/    { proxy_pass http://backend:8000; ... }  # WebSocket upgrade
    location /minio/ { proxy_pass http://minio:9000;   ... }
    location /      { proxy_pass http://frontend:80;   ... }
}
```

Trong `docker-compose.yml`, service `nginx` cần mount:

```yaml
volumes:
  - /etc/letsencrypt:/etc/letsencrypt:ro
  - /var/www/certbot:/var/www/certbot:ro
  - ./deploy/nginx/visionmart.conf:/etc/nginx/conf.d/default.conf:ro
```

---

## 10. Khởi động stack

```bash
cd /opt/visionmart

# Pull / build image
docker compose pull
docker compose build

# Khởi tạo DB schema (Alembic)
docker compose run --rm backend alembic upgrade head

# Seed dữ liệu hệ thống (roles, super_admin, demo org)
docker compose run --rm backend python -m app.scripts.seed_initial

# Start toàn bộ stack ở chế độ daemon
docker compose up -d

# Kiểm tra
docker compose ps
docker compose logs -f --tail=100
```

---

## 11. Kiểm thử nhanh sau deploy

```bash
# Healthcheck
curl -fsS https://visionmart.thehuan.com/api/v1/health | jq

# Trang web
curl -I https://visionmart.thehuan.com

# WebSocket (cần wscat: npm i -g wscat)
wscat -c wss://visionmart.thehuan.com/ws/dashboard \
      -H "Authorization: Bearer <token>"
```

Mở trình duyệt `https://visionmart.thehuan.com` → đăng nhập bằng tài khoản
`super_admin` đã seed.

---

## 12. Quy trình cập nhật (re-deploy)

```bash
cd /opt/visionmart
git fetch --all
git checkout main
git pull --ff-only

docker compose pull
docker compose build

# Áp migration mới (luôn forward-only, xem 07_DEPLOYMENT_PLAN.md §Alembic)
docker compose run --rm backend alembic upgrade head

# Rolling restart
docker compose up -d
docker compose ps
```

Kiểm tra logs sau khi update:

```bash
docker compose logs -f backend ai-worker celery-worker nginx
```

Rollback (nếu cần):

```bash
git checkout <previous_commit_sha>
docker compose up -d --build
# Nếu phải lùi migration: chỉ thực hiện khi đã review kỹ
```

---

## 13. Backup & Restore (tối thiểu cho VPS đơn)

### 13.1 Backup tự động hàng ngày

Tạo script `/opt/visionmart/scripts/backup.sh`:

```bash
#!/bin/bash
set -euo pipefail
TS=$(date +%Y%m%d_%H%M%S)
DEST=/var/lib/visionmart/backup/$TS
mkdir -p "$DEST"

# Postgres logical dump
docker compose -f /opt/visionmart/docker-compose.yml exec -T postgres \
    pg_dump -U visionmart -F c visionmart > "$DEST/db.dump"

# MinIO data (rclone hoặc mc mirror)
docker run --rm --network visionmart_default \
    -v "$DEST":/backup minio/mc:latest \
    sh -c "mc alias set s3 http://minio:9000 \$MINIO_ROOT_USER \$MINIO_ROOT_PASSWORD && \
           mc mirror s3/visionmart /backup/minio"

# Giữ 14 ngày
find /var/lib/visionmart/backup -maxdepth 1 -type d -mtime +14 -exec rm -rf {} \;
```

Cron daily 02:30:

```bash
chmod +x /opt/visionmart/scripts/backup.sh
( crontab -l 2>/dev/null; echo "30 2 * * * /opt/visionmart/scripts/backup.sh >> /var/log/visionmart-backup.log 2>&1" ) | crontab -
```

### 13.2 Restore

```bash
# DB
cat backup/db.dump | docker compose exec -T postgres \
    pg_restore -U visionmart -d visionmart --clean --if-exists

# MinIO
mc mirror /var/lib/visionmart/backup/<TS>/minio s3/visionmart
```

> **Đã thay thế bởi hệ thống backup tự động (`backup/`, Release Candidate).**
> Quy trình cron thủ công ở §13.1/§13.2 vẫn hoạt động nếu bạn đã dùng nó
> từ trước, nhưng **không tương thích định dạng** với hệ thống mới (khác
> tên file, khác cấu trúc bên trong: `db.dump` custom-format vs
> `postgres.sql` plain-SQL trong zip có checksum). Triển khai mới nên dùng
> `backup/` — xem [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md) và
> §18 bên dưới — **không trộn lẫn hai hệ thống** cho cùng một chuỗi backup
> (chọn một, dùng nhất quán).

---

## 14. Quan sát & vận hành

```bash
# Tài nguyên
docker stats --no-stream

# Logs theo service
docker compose logs -f backend
docker compose logs -f ai-worker
docker compose logs -f celery-worker
docker compose logs -f nginx

# Vào shell một container
docker compose exec backend bash

# Chạy migration tay
docker compose run --rm backend alembic upgrade head
```

Khuyến nghị bổ sung khi production lâu dài (xem
[docs/19_MONITORING.md](docs/19_MONITORING.md) khi sẵn sàng):

- Prometheus + Grafana qua compose profile `monitoring`.
- Loki / Promtail thu thập logs JSON.
- Uptime probe ngoài (UptimeRobot / Healthchecks.io) đánh `/api/v1/health` 1 phút/lần.

---

## 15. Bảo mật bổ sung

- Bật auto-update vá lỗi:

  ```bash
  apt install -y unattended-upgrades
  dpkg-reconfigure -plow unattended-upgrades
  ```

- Quay vòng mật khẩu Postgres / Redis / MinIO định kỳ (90 ngày).
- Quay vòng cặp khoá JWT (`kid` rotate) theo
  [docs/13_AUTHENTICATION.md](docs/13_AUTHENTICATION.md).
- Không expose cổng nội bộ (5432, 6379, 9000, 8000) ra ngoài — chỉ Nginx public.
- Đặt rate-limit ở Nginx (đã có trong template repo): `/api/v1/auth/login`
  10 req/min/IP, `/api/v1/*` 60 req/min/IP.

---

## 16. Checklist Go-Live

- [ ] DNS A record trỏ đúng IP, propagate xong (`dig visionmart.thehuan.com`).
- [ ] UFW chỉ mở 22/80/443.
- [ ] Cert Let's Encrypt cấp thành công, `certbot.timer` active.
- [ ] `.env` chmod 600, không nằm trong git.
- [ ] Cặp khoá JWT đã sinh, mount đúng đường dẫn.
- [ ] `alembic upgrade head` chạy sạch.
- [ ] Seed `super_admin` đổi mật khẩu mặc định.
- [ ] `docker compose ps` tất cả service `healthy`.
- [ ] `curl https://visionmart.thehuan.com/api/v1/health` trả `200`.
- [ ] WebSocket dashboard kết nối được.
- [ ] Backup cron đã có entry, log file ghi nhận lần đầu.
- [ ] Đã ghi lại mật khẩu DB/Redis/MinIO vào trình quản lý bí mật (không lưu plain).

---

## 17. Sự cố thường gặp

| Triệu chứng                                | Nguyên nhân                       | Cách xử lý                                                       |
| ------------------------------------------ | --------------------------------- | ---------------------------------------------------------------- |
| `502 Bad Gateway`                          | Backend chưa healthy              | `docker compose logs backend`; kiểm tra DB connectivity          |
| Certbot HTTP-01 fail                       | UFW chặn 80 hoặc Nginx giữ port   | `docker compose stop nginx`, chạy lại `certbot certonly ...`     |
| `pg_dump` lỗi `role does not exist`        | Sai `POSTGRES_USER` trong `.env`  | Đồng bộ env với volume Postgres hoặc `docker compose down -v`    |
| WebSocket bị đóng sau 60s                  | Thiếu `proxy_read_timeout`        | Set `proxy_read_timeout 3600s` cho `location /ws/` trong Nginx   |
| AI worker OOM trên CPU                     | YOLOv8m quá nặng                  | Hạ về `yolov8s`, giảm `AI_FPS_TARGET`, giảm batch size           |
| `manifest unknown` khi `docker compose pull` | Image chưa publish               | Dùng `docker compose build` thay vì `pull`                       |

---

## 18. Production Readiness (Release Candidate) — bổ sung trước khi go-live

Bốn khả năng dưới đây được thêm ở giai đoạn "Final Productio