# Production Setup (DevOps Toolkit)

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 47_PRODUCTION_SETUP.md
> **Status:** Implemented (Final DevOps & Deployment Toolkit)

---

## Purpose

Mô tả cách dùng `scripts/setup-production.sh` để triển khai VisionMart
lên một VPS Ubuntu mới hoàn toàn, tự động hoá phần lớn quy trình thủ
công đã mô tả trong [docs/DEPLOY_VPS.md](DEPLOY_VPS.md) (§2-§10): cài
gói hệ điều hành, cài Docker, clone mã nguồn, sinh secret, build/deploy
stack, khởi tạo database, và xác minh sức khoẻ triển khai bằng
`visionmart doctor`.

`docs/DEPLOY_VPS.md` vẫn là tài liệu tham chiếu cho các bước **không**
được tự động hoá ở đây theo đúng yêu cầu "không tự sửa nginx/TLS" của
đề bài: cấu hình DNS, Nginx/TLS/Certbot ban đầu, và tường lửa.

## Scope

**Trong phạm vi:** `scripts/setup-production.sh`, `scripts/lib/common.sh`,
`scripts/lib/deploy_engine.sh`, `scripts/generate-secrets.sh` (gọi từ
setup-production.sh).

**Ngoài phạm vi:** không sửa Cart/Checkout/Payment/Computer
Vision/Event Bus/Database Schema, không tự động cấu hình DNS hay wiring
TLS vào nginx (xem [docs/DEPLOY_VPS.md](DEPLOY_VPS.md) §6-§9 và
[scripts/renew-certificates.sh](../scripts/renew-certificates.sh)).

## Revision History

| Version | Date       | Author         | Description                          |
| ------- | ---------- | -------------- | ------------------------------------- |
| 1.0.0   | 2026-07-04 | VisionMart Eng | DevOps & Deployment Toolkit shipped.  |

## Table of Contents

1. [Purpose](#purpose)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [What the script does, step by step](#what-the-script-does-step-by-step)
5. [Options reference](#options-reference)
6. [After setup finishes](#after-setup-finishes)
7. [Troubleshooting](#troubleshooting)
8. [Known limitations](#known-limitations)
9. [References](#references)

---

## Prerequisites

- Một VPS chạy **Ubuntu 22.04 LTS** (khuyến nghị 8 vCPU / 16 GB RAM / 200
  GB SSD cho CPU-only YOLO — xem [docs/DEPLOY_VPS.md](DEPLOY_VPS.md) §0).
- Quyền `root` hoặc `sudo` trên VPS.
- DNS đã trỏ về VPS nếu cần truy cập qua domain (không bắt buộc để chạy
  script — chỉ cần cho bước TLS thủ công sau này).
- Repository Git công khai (HTTPS) hoặc riêng tư (SSH, deploy key đã
  authorize trên remote).

## Quick Start

```bash
# Trên VPS, với quyền root:
curl -fsSL https://raw.githubusercontent.com/huanbv/VisionMart/main/scripts/setup-production.sh -o setup-production.sh
sudo bash setup-production.sh --seed-admin --yes
```

Hoặc nếu đã clone sẵn repo:

```bash
cd /opt/visionmart   # hoặc bất kỳ đường dẫn nào
sudo bash scripts/setup-production.sh --app-dir "$(pwd)" --skip-os-setup --seed-admin --yes
```

`--yes` chỉ bỏ qua các câu hỏi xác nhận không mang tính phá huỷ (ví dụ
prompt của `generate-secrets.sh`) — script không bao giờ ghi đè một
secret đã có giá trị thật mà không hỏi trừ khi `--yes` được truyền, và
không bao giờ xoá dữ liệu.

## What the script does, step by step

1. **Kiểm tra prerequisite** (bỏ qua nếu `--skip-os-setup`): xác định
   OS/kiến trúc/RAM/dung lượng đĩa trống/kết nối mạng, cảnh báo nếu
   không phải Ubuntu hoặc RAM < 4 GB.
2. **Cài gói hệ thống**: `git curl wget jq zip unzip openssl
   ca-certificates gnupg lsb-release` qua `apt-get` (idempotent — bỏ
   qua gói đã cài).
3. **Cài Docker Engine + Compose plugin** theo đúng kho chính chủ Docker
   (bỏ qua nếu đã cài).
4. **Clone hoặc cập nhật mã nguồn** vào `--app-dir` (mặc định
   `/opt/visionmart`): `git clone` nếu chưa tồn tại, `git fetch` +
   `checkout` + `pull --ff-only` nếu đã là một checkout của cùng repo.
   Hỗ trợ cả HTTPS và SSH qua `--repo-url`.
5. Từ đây, script chuyển sang dùng `scripts/lib/common.sh` và
   `scripts/lib/deploy_engine.sh` **đã có trong bản checkout vừa lấy về**
   — không có logic triển khai nào bị lặp lại giữa setup và update (xem
   [docs/50_SCRIPT_REFERENCE.md](50_SCRIPT_REFERENCE.md#libdeploy_enginesh)).
6. **Sinh `.env` + secret** qua `scripts/generate-secrets.sh` (Part
   3/14) — tạo `.env` từ `.env.example` nếu chưa có, sinh
   `BACKEND_SECRET_KEY`, `AI_ENGINE_API_KEY`, `MONITORING_API_TOKEN`,
   `MINIO_ROOT_PASSWORD`, `POSTGRES_PASSWORD` (+ `DATABASE_URL`),
   `SEED_ADMIN_PASSWORD`, và cặp khoá JWT RS256 tại `./secrets/`.
7. **Deploy**: `docker compose pull` (best-effort) + `build` + `up -d`,
   sau đó chờ tối đa 240 giây để mọi container có healthcheck (Postgres,
   Redis, MinIO, backend, ai-engine, monitoring) báo `healthy`, tự thử
   `restart` một lần cho container nào `unhealthy`.
8. **Khởi tạo database**: `alembic upgrade head` (an toàn để chạy nhiều
   lần — forward-only, no-op nếu đã ở `head`).
9. **Seed dữ liệu ban đầu** (chỉ khi có `--seed-admin`): tổ chức mặc
   định + 6 role + tài khoản `super_admin` qua
   `app.scripts.seed_initial` (idempotent, không bao giờ dùng
   `seed_demo` — script demo/dev không được gọi từ đây).
10. **Xác minh**: `python -m visionmart doctor` bên trong container
    `monitoring` — `FAIL` sẽ khiến script thoát với exit code khác 0 và
    in khuyến nghị khắc phục; `WARNING` chỉ cảnh báo, script vẫn coi là
    thành công.

## Options reference

| Option              | Mặc định                                    | Ý nghĩa |
| ------------------- | -------------------------------------------- | ------- |
| `--repo-url URL`     | `https://github.com/huanbv/VisionMart.git`   | Remote Git (HTTPS hoặc SSH). |
| `--branch NAME`      | `main`                                        | Branch cần checkout. |
| `--app-dir PATH`     | `/opt/visionmart` (hoặc `$VISIONMART_APP_DIR`)| Thư mục cài đặt. |
| `--skip-os-setup`    | tắt                                           | Bỏ qua cài gói OS/Docker (dùng khi đã có sẵn). |
| `--seed-admin`       | tắt                                           | Tạo tổ chức/role/admin ban đầu sau migration. |
| `--yes`              | tắt                                           | Không hỏi xác nhận (dùng cho CI/tự động hoá). |
| `-h`, `--help`       | —                                              | In hướng dẫn. |

## After setup finishes

- Chạy `scripts/status.sh` để xem snapshot vận hành (Health Score, tài
  nguyên host, camera, container).
- Đăng nhập bằng tài khoản `super_admin` đã seed — **đổi mật khẩu ngay**
  (giá trị nằm trong `.env`'s `SEED_ADMIN_PASSWORD`, do
  `generate-secrets.sh` sinh ra).
- Tiếp tục với [docs/DEPLOY_VPS.md](DEPLOY_VPS.md) §6-§9 để cấu hình
  DNS + TLS (Let's Encrypt qua Certbot, standalone trên host) — script
  này **không** tự động làm phần đó.
- Cấu hình cron cho backup hàng ngày:
  `0 2 * * * cd /opt/visionmart && scripts/backup-now.sh --yes >> logs/devops/cron-backup.log 2>&1`
  (hoặc bật scheduler trong-stack — xem [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md)).

## Troubleshooting

| Triệu chứng | Nguyên nhân khả dĩ | Cách xử lý |
| ----------- | ------------------- | ---------- |
| `scripts/lib/common.sh not found ... after checkout` | `--repo-url`/`--branch` sai, hoặc repo chưa có toolkit này | Kiểm tra lại URL/branch; xác nhận nhánh đó đã có `scripts/` |
| Dừng ở bước Docker install | Hệ điều hành không phải Ubuntu, hoặc không có quyền root | Cài Docker thủ công rồi chạy lại với `--skip-os-setup` |
| `wait_for_stack_healthy` timeout | Máy quá yếu (RAM thấp) khiến build/khởi động chậm | Tăng RAM VPS, hoặc chạy lại `scripts/health-check.sh`/`scripts/doctor.sh` sau khi các container tự ổn định |
| `visionmart doctor` báo FAIL ở Security | Một secret vẫn còn giá trị mặc định | Chạy `scripts/generate-secrets.sh --check` để xem chính xác biến nào |
| Migration lỗi | Kết nối Postgres chưa sẵn sàng, hoặc lỗi schema thật | Xem `scripts/logs.sh postgres` và `scripts/logs.sh backend --search alembic` |

## Known limitations

- Không tự động cấu hình DNS, TLS, hay tường lửa (`ufw`) — vẫn là bước
  thủ công theo [docs/DEPLOY_VPS.md](DEPLOY_VPS.md).
- Không hỗ trợ triển khai đa node/Kubernetes (Tier 2) — chỉ Tier 1 (một
  VPS, Docker Compose) đúng phạm vi của toolkit này.
- `--repo-url` với SSH yêu cầu deploy key đã được thêm vào remote từ
  trước — script không tạo hay đăng ký SSH key.

## References

- [docs/DEPLOY_VPS.md](DEPLOY_VPS.md) — quy trình thủ công đầy đủ, bao
  gồm các phần không được tự động hoá ở đây.
- [docs/48_OPERATIONS_GUIDE.md](48_OPERATIONS_GUIDE.md) — vận hành hàng
  ngày sau khi đã setup xong.
- [docs/49_DISASTER_RECOVERY.md](49_DISASTER_RECOVERY.md) — khôi phục
  sự cố.
- [docs/50_SCRIPT_REFERENCE.md](50_SCRIPT_REFERENCE.md) — tham chiếu
  đầy đủ từng script.
- [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md),
  [docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md),
  [docs/44_VERSIONING.md](44_VERSIONING.md) — các hệ thống được tái sử
  dụng bởi toolkit này.

---

*Tài liệu này mô tả Part 2-7 của "Final DevOps & Deployment Toolkit" —
additive, không thay đổi Cart/Checkout/Payment/Computer
Vision/Event Bus/Database Schema.*
