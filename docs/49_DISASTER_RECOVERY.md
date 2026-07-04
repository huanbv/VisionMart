# Disaster Recovery (DevOps Toolkit)

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 49_DISASTER_RECOVERY.md
> **Status:** Implemented (Final DevOps & Deployment Toolkit)

---

## Purpose

Kịch bản xử lý từng loại sự cố production, dùng các script đã có thay
vì thao tác tay từng bước. Mỗi kịch bản nêu: triệu chứng, các bước xử
lý bằng script, và điều gì **không** được tự động hoá (để người vận
hành biết chính xác ranh giới).

## Revision History

| Version | Date       | Author         | Description                          |
| ------- | ---------- | -------------- | ------------------------------------- |
| 1.0.0   | 2026-07-04 | VisionMart Eng | DevOps & Deployment Toolkit shipped.  |

## Table of Contents

1. [Scenario 1: A service is crash-looping](#scenario-1-a-service-is-crash-looping)
2. [Scenario 2: Database corrupted or lost](#scenario-2-database-corrupted-or-lost)
3. [Scenario 3: Entire VPS lost (full rebuild)](#scenario-3-entire-vps-lost-full-rebuild)
4. [Scenario 4: A deploy/update broke production](#scenario-4-a-deployupdate-broke-production)
5. [Scenario 5: A secret was leaked](#scenario-5-a-secret-was-leaked)
6. [Scenario 6: TLS certificate expired unexpectedly](#scenario-6-tls-certificate-expired-unexpectedly)
7. [Scenario 7: Disk full](#scenario-7-disk-full)
8. [Known limitations](#known-limitations)
9. [References](#references)

---

## Scenario 1: A service is crash-looping

**Triệu chứng:** `scripts/health-check.sh` báo FAIL, hoặc
`docker compose ps` cho thấy một service liên tục `Restarting`.

```bash
scripts/logs.sh <service> --tail 200          # xem log gần nhất
scripts/doctor.sh                              # kiểm tra sâu, có khuyến nghị
scripts/restart-services.sh <service> --wait   # thử khởi động lại, chờ healthy
```

Nếu vẫn lỗi sau restart, kiểm tra `.env` (secret sai/thiếu — chạy
`scripts/generate-secrets.sh --check`) và tài nguyên host
(`scripts/status.sh` — RAM/disk đầy là nguyên nhân phổ biến nhất trên
VPS nhỏ chạy YOLO CPU-only).

## Scenario 2: Database corrupted or lost

**Triệu chứng:** `doctor.sh` báo FAIL ở category Database, hoặc backend
liên tục lỗi kết nối Postgres.

```bash
scripts/restore-backup.sh --list                                 # xem các bản có sẵn
scripts/restore-backup.sh --file <ten-file-backup-gan-nhat.zip>   # khôi phục (luôn hỏi xác nhận, gõ đúng tên DB)
scripts/doctor.sh                                                  # xác minh sau khôi phục
```

Quy trình chi tiết + định dạng archive:
[docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md#restore-procedure).

**Nếu không có backup nào** (tình huống xấu nhất): dữ liệu nghiệp vụ
(đơn hàng, sản phẩm, tài khoản) không thể khôi phục được — đây là lý do
`scripts/backup-now.sh` nên chạy theo lịch (cron hoặc scheduler
trong-stack) chứ không chỉ chạy tay. Xem
[Known Limitations](#known-limitations).

## Scenario 3: Entire VPS lost (full rebuild)

**Triệu chứng:** VPS bị xoá/hỏng phần cứng, cần dựng lại từ đầu trên
máy mới.

```bash
# Trên VPS mới:
sudo bash scripts/setup-production.sh --yes    # KHÔNG dùng --seed-admin lần này

# Sau khi stack chạy healthy, khôi phục dữ liệu từ backup gần nhất
# (backup phải được lưu offsite/tải về máy mới trước bước này -- xem
# Known Limitations: backup mặc định chỉ lưu local trên VPS cũ):
scripts/restore-backup.sh --list
scripts/restore-backup.sh --file <ten-file-backup-gan-nhat.zip> --with-uploads
scripts/doctor.sh
```

Sau đó cấu hình lại DNS/TLS theo
[docs/DEPLOY_VPS.md](DEPLOY_VPS.md) §6-§9 (không tự động hoá).

## Scenario 4: A deploy/update broke production

**Triệu chứng:** `scripts/update-production.sh` báo container không
`healthy`, hoặc `visionmart doctor` báo `FAIL` sau update.

```bash
git log --oneline -5                       # xác định SHA trước khi update
git checkout <sha-truoc-do>
scripts/update-production.sh --yes         # "update" về lại phiên bản cũ
scripts/doctor.sh
```

**Lưu ý về migration:** Alembic migration là forward-only (xem
[docs/DEPLOY_VPS.md](DEPLOY_VPS.md) §12) — nếu bản mới đã chạy migration
thay đổi schema, quay lại code cũ có thể không tương thích với schema
mới. Luôn kiểm tra kỹ trước khi rollback nếu update đã đi qua bước
migration; trường hợp này cân nhắc roll-forward (sửa lỗi rồi update
tiếp) thay vì rollback.

## Scenario 5: A secret was leaked

**Triệu chứng:** Một secret (token, mật khẩu) trong `.env` bị lộ ra
ngoài (log, commit nhầm, chia sẻ nhầm).

```bash
scripts/generate-secrets.sh --only <TEN_BIEN> --yes    # sinh giá trị mới cho đúng biến đó
scripts/restart-services.sh --wait                     # áp dụng cho mọi service đọc .env
```

Nếu là `POSTGRES_PASSWORD` bị lộ: đọc kỹ cảnh báo trong
`generate-secrets.sh`'s output trước — đổi mật khẩu Postgres sau khi
volume đã khởi tạo cần thêm bước `ALTER USER` thủ công (script tự sinh
giá trị mới trong `.env`/`DATABASE_URL` nhưng **không** tự đổi mật khẩu
đã tồn tại trong chính PostgreSQL — chạy:
`docker compose exec postgres psql -U <user> -d postgres -c "ALTER USER <user> WITH PASSWORD '<gia-tri-moi>';"`
rồi mới restart backend/celery).

Nếu là cặp khoá JWT bị lộ:
`scripts/generate-secrets.sh --only JWT_KEYPAIR --yes` — lưu ý điều này
**vô hiệu hoá ngay lập tức mọi access/refresh token đã phát hành**, mọi
người dùng phải đăng nhập lại.

## Scenario 6: TLS certificate expired unexpectedly

```bash
scripts/renew-certificates.sh --check-only   # xác nhận đúng là đã hết hạn
scripts/renew-certificates.sh                # gia hạn qua certbot
```

Nếu nginx chưa được wiring TLS (xem
[docs/DEPLOY_VPS.md](DEPLOY_VPS.md) §9), script sẽ in rõ các bước thủ
công cần làm — nó không tự sửa cấu hình nginx.

## Scenario 7: Disk full

```bash
scripts/status.sh                    # xác nhận Disk % cao
scripts/cleanup.sh --dry-run         # xem sẽ dọn được gì
scripts/cleanup.sh                   # dọn image/cache/backup cũ/log cũ
scripts/rotate-logs.sh --compact     # nén thêm log cũ của toolkit
```

Nếu vẫn thiếu đĩa sau cleanup, cân nhắc giảm
`BACKUP_RETENTION_DAYS`/`LOG_MAX_FILE_SIZE`/`LOG_MAX_FILES` trong `.env`
rồi `scripts/restart-services.sh --wait`, hoặc tăng dung lượng đĩa VPS.

## Known limitations

- **Backup mặc định chỉ lưu local trên chính VPS** (`BACKUP_DIR`) — một
  sự cố ổ đĩa/xoá nhầm VPS vẫn có thể mất cả dữ liệu gốc lẫn backup nếu
  không có quy trình tải backup ra ngoài (offsite). Đây là giới hạn đã
  ghi nhận từ [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md#future-improvements)
  — khuyến nghị: thêm cron `scp`/`rclone` bản backup mới nhất ra một nơi
  khác sau mỗi lần `backup-now.sh` chạy.
- **`monitoring.db` không được khôi phục tự động** bởi
  `restore-backup.sh` (chỉ là dữ liệu vận hành/giám sát, không phải dữ
  liệu nghiệp vụ) — các bước thủ công được in ra cuối script nếu cần.
- **Không có test-restore tự động định kỳ** — `verify_archive()` chỉ
  xác minh tính toàn vẹn của file zip (không hỏng, checksum khớp),
  không xác minh nội dung SQL thực sự restore thành công vào một DB
  test. Nên diễn tập restore thủ công định kỳ (ví dụ hàng quý) vào một
  môi trường staging.
- **Rollback code không tự động rollback migration** — xem cảnh báo ở
  [Scenario 4](#scenario-4-a-deployupdate-broke-production).
- **Không có kịch bản multi-region/failover** — toolkit này chỉ nhắm
  tới kiến trúc VPS đơn (Tier 1) theo đúng phạm vi đề bài.

## References

- [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md) — chi tiết định
  dạng backup, quy trình restore từng thành phần.
- [docs/47_PRODUCTION_SETUP.md](47_PRODUCTION_SETUP.md) — dựng lại từ
  đầu trên VPS mới.
- [docs/48_OPERATIONS_GUIDE.md](48_OPERATIONS_GUIDE.md) — vận hành hàng
  ngày.
- [docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md) — chi
  tiết từng mục kiểm tra của `visionmart doctor`.

---

*Tài liệu này mô tả các kịch bản khôi phục sự cố bổ sung ở giai đoạn
Final DevOps & Deployment Toolkit — additive, không thay đổi
Cart/Checkout/Payment/Computer Vision/Event Bus/Database Schema.*
