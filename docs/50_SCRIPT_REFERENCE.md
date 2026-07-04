# Script Reference (DevOps Toolkit)

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 50_SCRIPT_REFERENCE.md
> **Status:** Implemented (Final DevOps & Deployment Toolkit)

---

## Purpose

Tham chiếu đầy đủ cho từng script trong `scripts/` thuộc "Final DevOps
& Deployment Toolkit": usage, options, mã thoát, và ghi chú. Mọi script
đều có `-h`/`--help` in ra thông tin tương đương phần này trực tiếp
trên terminal — tài liệu này để tra cứu nhanh không cần chạy lệnh.

## Revision History

| Version | Date       | Author         | Description                          |
| ------- | ---------- | -------------- | ------------------------------------- |
| 1.0.0   | 2026-07-04 | VisionMart Eng | DevOps & Deployment Toolkit shipped.  |

## Conventions shared by every script

- Tất cả nằm trong `scripts/`, đều `source scripts/lib/common.sh` đầu
  tiên (thư viện dùng chung: màu sắc, logging ra `logs/devops/`, mã
  thoát chuẩn, `confirm()`, `dc()` cho `docker compose`, `env_get()`).
- An toàn chạy lại nhiều lần (idempotent) trừ `restore-backup.sh` (luôn
  hỏi xác nhận rõ ràng vì có tính phá huỷ).
- `--yes`/`-y` bỏ qua xác nhận không mang tính phá huỷ; **không** có
  script nào cho phép `--yes` bỏ qua xác nhận khôi phục database.
- Mã thoát dùng chung — xem
  [docs/48_OPERATIONS_GUIDE.md#exit-code-contract](48_OPERATIONS_GUIDE.md#exit-code-contract).

---

## `lib/common.sh`

Thư viện dùng chung, không tự chạy. Cung cấp: màu ANSI, `log/info/ok/warn/error/die`,
`init_logging`, `confirm`, `require_cmd/require_root/require_file/require_env_file`,
`dc()` (shim `docker compose`/`docker-compose`), `env_get()`, `wait_for_http()`,
`container_health()`, `print_version_banner()`. `VISIONMART_APP_DIR` tự
suy ra từ vị trí file này (`<repo>/scripts/lib/common.sh` → gốc repo).

## `lib/deploy_engine.sh`

Thư viện dùng chung cho `setup-production.sh` và `update-production.sh`
(Part 4/5/6): `deploy_pull_build()`, `deploy_up()`,
`wait_for_stack_healthy(timeout)`, `run_db_migrations()`,
`run_seed_initial()` (chỉ chạy khi `SEED_ADMIN_ON_SETUP=1`),
`run_health_verification()` (gọi `visionmart doctor`).

---

## `setup-production.sh`

```
sudo bash scripts/setup-production.sh [options]
```

| Option | Default | Ý nghĩa |
| ------ | ------- | ------- |
| `--repo-url URL` | `https://github.com/huanbv/VisionMart.git` | Remote Git. |
| `--branch NAME` | `main` | Branch checkout. |
| `--app-dir PATH` | `/opt/visionmart` | Thư mục cài đặt. |
| `--skip-os-setup` | tắt | Bỏ qua cài OS/Docker. |
| `--seed-admin` | tắt | Tạo admin/tổ chức ban đầu. |
| `--yes` | tắt | Không hỏi xác nhận. |

Chi tiết: [docs/47_PRODUCTION_SETUP.md](47_PRODUCTION_SETUP.md).

## `update-production.sh`

```
scripts/update-production.sh [--branch NAME] [--with-frontend] [--yes]
```

Fetch → hiện commit thay đổi → xác nhận → pull → build/up → chờ healthy
→ migrate → `visionmart doctor`. In hướng dẫn rollback nếu bất kỳ bước
nào thất bại.

## `generate-secrets.sh`

```
scripts/generate-secrets.sh [--only KEY1,KEY2] [--all] [--check] [--yes]
```

Tạo `.env` từ `.env.example` nếu chưa có; sinh
`BACKEND_SECRET_KEY`/`AI_ENGINE_API_KEY`/`MONITORING_API_TOKEN`/
`MINIO_ROOT_PASSWORD`/`POSTGRES_PASSWORD` (+`DATABASE_URL`)/
`SEED_ADMIN_PASSWORD`/cặp khoá JWT RS256. `--check` chỉ báo cáo, không
đổi gì. Không bao giờ ghi đè giá trị đã có mà không hỏi (trừ giá trị
mặc định trong `.env` vừa được tạo mới). Xem `--help` để biết các biến
được yêu cầu nhưng không áp dụng cho codebase này
(`JWT_SECRET_KEY`/`REDIS_PASSWORD`/`SESSION_SECRET`/`CSRF_SECRET`) và lý
do.

## `backup-now.sh`

```
scripts/backup-now.sh [--skip-retention]
```

Bọc `python -m backup.cli run` + `cleanup`, in tóm tắt (backup_id, kích
thước, sha256, verified, overall_ok).

## `restore-backup.sh`

```
scripts/restore-backup.sh --list
scripts/restore-backup.sh --file <name> [--with-uploads]
```

**Thao tác phá huỷ** — luôn `list` → `verify` checksum → yêu cầu gõ
đúng tên database để xác nhận (không thể bỏ qua bằng `--yes`) → dừng
backend/celery/ai-engine (không dừng postgres) → restore → khởi động
lại. `monitoring.db` không được khôi phục tự động (in hướng dẫn thủ
công). Chi tiết: [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md).

## `logs.sh`

```
scripts/logs.sh <target> [-f|--follow] [--tail N] [--search PATTERN]
scripts/logs.sh --list
```

Target: `backend frontend ai-engine monitoring backup backup-once
celery-worker celery-beat celery postgres redis minio nginx evaluation
all`. Mọi target dùng `docker compose logs` trừ `evaluation` (đọc trực
tiếp `evaluation_results/logs/evaluation.log` vì đây là CLI, không phải
container).

## `maintenance-mode.sh` / `exit-maintenance.sh`

```
scripts/maintenance-mode.sh
scripts/exit-maintenance.sh
```

Đổi vhost nginx đang active (`docker/nginx/conf.d/default.conf`) sang
trang bảo trì tĩnh (`maintenance.conf.disabled` → `maintenance.conf`),
`nginx -t` trước khi `nginx -s reload`. Không dừng bất kỳ service nội
bộ nào. Tự rollback nếu `nginx -t` thất bại.

## `cleanup.sh`

```
scripts/cleanup.sh [--images] [--build-cache] [--old-backups] [--old-logs]
                    [--restore-scratch] [--volumes] [--all] [--days N]
                    [--dry-run] [--yes]
```

Không có flag = chạy như `--all` (mọi thứ trừ `--volumes`). `--volumes`
liệt kê volume Docker "dangling" **loại trừ hẳn** mọi volume dữ liệu đã
biết của dự án (`postgres_data`, `redis_data`, `minio_data`,
`monitoring_data`, `backups_data`, `ai_engine_weights`,
`ai_engine_training`) — không bao giờ đề xuất xoá chúng dù Docker báo
dangling (điều này xảy ra bình thường mỗi khi `docker compose down`).

## `status.sh`

```
scripts/status.sh [--json]
```

Snapshot một màn hình: version, git, uptime, container, Health Score,
CPU/RAM/Disk/GPU, Redis/PostgreSQL/Celery, camera, evaluation, active
alerts. Dữ liệu lấy từ `monitoring`'s `/api/overview` (không thu thập
lại) + `git`/`docker compose`/`uptime` cho phần còn lại.

## `version.sh`

```
scripts/version.sh [--json]
```

App version (từ file `VERSION`), release candidate label, build time
(từ `release_info.json` nếu có), git SHA/branch/dirty, phiên bản
Python/Node/Docker/Compose, OS, kernel.

## `health-check.sh`

```
scripts/health-check.sh [--quiet]
```

Kiểm tra nhanh (vài giây): `/health` của backend/ai-engine/monitoring +
trạng thái healthcheck Docker của postgres/redis/minio. Thoát 0 nếu
khoẻ, `EXIT_UNHEALTHY` (5) nếu không — phù hợp cho cron/uptime monitor.
Khác `doctor.sh` ở chỗ nông và nhanh hơn nhiều.

## `doctor.sh`

```
scripts/doctor.sh
```

Bọc `python -m visionmart doctor` (28 kiểm tra, 14 category) bên trong
container `monitoring`. Chi tiết từng mục:
[docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md).

## `restart-services.sh`

```
scripts/restart-services.sh [service...] [--wait] [--timeout N]
```

Không có service = restart tất cả. `docker compose restart` (không
build lại image — dùng `update-production.sh` nếu cần đổi code).

## `rotate-logs.sh`

```
scripts/rotate-logs.sh [--compact]
```

Báo cáo dung lượng log hiện tại của mọi nguồn (toolkit riêng,
evaluation, monitoring/backup service, container). `--compact` chỉ nén
(`gzip`) log của chính toolkit này cũ hơn 1 ngày — rotation của Docker
`local` driver và `RotatingFileHandler` của các service Python là tự
động, không cần (và không thể) "force" thủ công; xem
[docs/18_LOGGING.md](18_LOGGING.md).

## `renew-certificates.sh`

```
scripts/renew-certificates.sh [--domain DOMAIN] [--check-only] [--yes]
```

Không có `--domain` sẽ tự suy ra từ `PUBLIC_APP_BASE_URL` trong `.env`.
Kiểm tra số ngày còn lại, hỗ trợ `certbot renew` hoặc lấy chứng chỉ mới
lần đầu (`certonly --standalone`, tạm dừng nginx). **Không tự sửa cấu
hình nginx** — nếu nginx chưa mount `/etc/letsencrypt`, script chỉ in
hướng dẫn thủ công (xem [docs/DEPLOY_VPS.md](DEPLOY_VPS.md) §9).

---

## References

- [docs/47_PRODUCTION_SETUP.md](47_PRODUCTION_SETUP.md)
- [docs/48_OPERATIONS_GUIDE.md](48_OPERATIONS_GUIDE.md)
- [docs/49_DISASTER_RECOVERY.md](49_DISASTER_RECOVERY.md)
- [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md),
  [docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md),
  [docs/18_LOGGING.md](18_LOGGING.md), [docs/44_VERSIONING.md](44_VERSIONING.md)

---

*Tài liệu này là tham chiếu đầy đủ cho toàn bộ script của Final DevOps &
Deployment Toolkit — additive, không thay đổi
Cart/Checkout/Payment/Computer Vision/Event Bus/Database Schema.*
