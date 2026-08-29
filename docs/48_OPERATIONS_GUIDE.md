# Operations Guide (DevOps Toolkit)

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 48_OPERATIONS_GUIDE.md
> **Status:** Implemented (Final DevOps & Deployment Toolkit)

---

## Purpose

Hướng dẫn vận hành hàng ngày/hàng tuần cho một deployment VisionMart đã
chạy production, dùng bộ 16 script trong `scripts/`. Đây là tài liệu
"mình cần làm gì mỗi ngày/mỗi tuần/mỗi khi có sự cố", khác với
[docs/47_PRODUCTION_SETUP.md](47_PRODUCTION_SETUP.md) (triển khai lần
đầu) và [docs/50_SCRIPT_REFERENCE.md](50_SCRIPT_REFERENCE.md) (tham
chiếu chi tiết từng flag).

## Revision History

| Version | Date       | Author         | Description                         |
| ------- | ---------- | -------------- | ------------------------------------ |
| 1.0.0   | 2026-07-04 | VisionMart Eng | DevOps & Deployment Toolkit shipped. |

## Table of Contents

1. [Daily checklist](#daily-checklist)
2. [Weekly checklist](#weekly-checklist)
3. [Common workflows](#common-workflows)
4. [Script quick index](#script-quick-index)
5. [Exit code contract](#exit-code-contract)
6. [References](#references)

---

## Daily checklist

```bash
cd /opt/visionmart

scripts/status.sh          # snapshot: version, containers, health score, resources, cameras
scripts/health-check.sh    # 5-second up/down check (good for a cron + alert)
```

Nếu `status.sh` báo Health Score `Warning`/`Critical`, hoặc
`health-check.sh` thoát khác 0, chạy tiếp:

```bash
scripts/doctor.sh          # kiểm tra sâu 28 mục, có khuyến nghị khắc phục cho từng mục
scripts/logs.sh backend -f # xem log trực tiếp của service nghi ngờ
```

## Weekly checklist

```bash
scripts/backup-now.sh                  # backup thủ công + xác minh (nếu không dùng scheduler trong-stack)
scripts/cleanup.sh --dry-run           # xem trước sẽ dọn gì
scripts/cleanup.sh                     # dọn image/cache/backup cũ/log cũ thật sự
scripts/renew-certificates.sh --check-only   # còn bao nhiêu ngày tới hạn TLS
```

## Common workflows

### Xem tình trạng hệ thống nhanh

```bash
scripts/status.sh            # dạng người đọc
scripts/status.sh --json     # dạng JSON (script/monitoring khác dùng lại)
scripts/version.sh           # phiên bản, git SHA, build time, versions của Python/Node/Docker
```

### Xem log của một service

```bash
scripts/logs.sh backend --tail 500          # 500 dòng gần nhất
scripts/logs.sh backend -f                  # theo dõi trực tiếp
scripts/logs.sh celery-worker --search ERROR # chỉ dòng chứa "ERROR" (không phân biệt hoa/thường)
scripts/logs.sh evaluation                  # log của evaluation/ (đọc file, không qua Docker)
scripts/logs.sh --list                      # liệt kê mọi target hợp lệ
```

### Khởi động lại một hoặc nhiều service

```bash
scripts/restart-services.sh backend                  # chỉ backend
scripts/restart-services.sh backend celery-worker     # nhiều service
scripts/restart-services.sh --wait                    # tất cả, chờ tới khi healthy
```

### Cập nhật lên phiên bản mới

```bash
scripts/update-production.sh                # hỏi xác nhận, hiện danh sách commit thay đổi
scripts/update-production.sh --yes           # không hỏi (CI/tự động hoá)
scripts/update-production.sh --with-frontend # cũng rebuild frontend image
```

Script tự chạy migration + `visionmart doctor` sau khi cập nhật; nếu
`doctor` báo `FAIL`, script in luôn hướng dẫn rollback
(`git checkout <sha-cũ> && scripts/update-production.sh --yes`).

### Backup / Restore

```bash
scripts/backup-now.sh                        # backup ngay + áp dụng retention
scripts/backup-now.sh --skip-retention       # chỉ backup, không xoá bản cũ
scripts/restore-backup.sh --list             # xem các bản backup hiện có
scripts/restore-backup.sh --file visionmart-backup-2026-07-04-020000.zip
scripts/restore-backup.sh --file <name> --with-uploads  # cũng khôi phục ảnh/video MinIO
```

Xem quy trình đầy đủ + giới hạn đã biết (monitoring.db không tự động
khôi phục) tại [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md) và
[docs/49_DISASTER_RECOVERY.md](49_DISASTER_RECOVERY.md).

### Bảo trì có kế hoạch (maintenance window)

```bash
scripts/maintenance-mode.sh    # bật trang "đang bảo trì" cho khách truy cập ngoài
# ... thực hiện công việc bảo trì (backup, update, kiểm tra dữ liệu) ...
scripts/exit-maintenance.sh    # tắt, trả lại routing bình thường
```

Các service nội bộ (backend, celery, postgres, ai-engine...) **không**
bị dừng trong lúc bảo trì — chỉ nginx đổi trang hiển thị ra bên ngoài.

### Xoay vòng secret khi nghi ngờ bị lộ

```bash
scripts/generate-secrets.sh --check                       # xem secret nào đang ở giá trị mặc định
scripts/generate-secrets.sh --only MONITORING_API_TOKEN --yes
scripts/restart-services.sh backend monitoring --wait      # áp dụng giá trị mới
```

### Gia hạn chứng chỉ TLS

```bash
scripts/renew-certificates.sh --check-only   # chỉ xem còn bao nhiêu ngày
scripts/renew-certificates.sh                # gia hạn (certbot renew, hoặc lấy mới nếu chưa có)
```

## Script quick index

| Script | Dùng khi nào |
| ------ | ------------- |
| `setup-production.sh` | Triển khai lần đầu trên VPS mới. |
| `update-production.sh` | Đưa code mới lên production. |
| `status.sh` | Xem nhanh tình trạng tổng thể. |
| `version.sh` | Cần biết đang chạy phiên bản/build nào. |
| `health-check.sh` | Kiểm tra nhanh up/down (cron, uptime monitor). |
| `doctor.sh` | Kiểm tra sâu trước/sau deploy, hoặc khi nghi ngờ có vấn đề. |
| `logs.sh` | Xem log bất kỳ service nào. |
| `restart-services.sh` | Khởi động lại một/nhiều/tất cả service. |
| `backup-now.sh` | Backup thủ công ngay lập tức. |
| `restore-backup.sh` | Khôi phục từ một bản backup (thao tác phá huỷ, luôn hỏi xác nhận). |
| `maintenance-mode.sh` / `exit-maintenance.sh` | Bật/tắt trang bảo trì cho khách bên ngoài. |
| `cleanup.sh` | Dọn image/cache/backup cũ/log cũ để giải phóng đĩa. |
| `rotate-logs.sh` | Xem dung lượng log, nén log cũ của toolkit. |
| `generate-secrets.sh` | Sinh/xoay vòng secret trong `.env`. |
| `renew-certificates.sh` | Kiểm tra/gia hạn chứng chỉ Let's Encrypt. |

## Exit code contract

Mọi script trong toolkit dùng chung một quy ước mã thoát (định nghĩa ở
`scripts/lib/common.sh`), hữu ích khi gọi từ cron hoặc CI:

| Code | Hằng số | Ý nghĩa |
| ---- | ------- | ------- |
| 0 | `EXIT_OK` | Thành công. |
| 1 | `EXIT_GENERAL_ERROR` | Lỗi chung không thuộc các loại dưới. |
| 2 | `EXIT_MISSING_PREREQ` | Thiếu lệnh/file/quyền cần thiết. |
| 3 | `EXIT_USER_ABORT` | Người dùng huỷ ở bước xác nhận. |
| 4 | `EXIT_VALIDATION_FAILED` | Tham số/đầu vào không hợp lệ. |
| 5 | `EXIT_UNHEALTHY` | Kiểm tra sức khoẻ/doctor báo FAIL. |

## References

- [docs/47_PRODUCTION_SETUP.md](47_PRODUCTION_SETUP.md) — triển khai
  lần đầu.
- [docs/49_DISASTER_RECOVERY.md](49_DISASTER_RECOVERY.md) — kịch bản
  khôi phục sự cố.
- [docs/50_SCRIPT_REFERENCE.md](50_SCRIPT_REFERENCE.md) — tham chiếu
  đầy đủ từng script/flag.
- [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md),
  [docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md),
  [docs/18_LOGGING.md](18_LOGGING.md), [docs/19_MONITORING.md](19_MONITORING.md)

---

*Tài liệu này mô tả cách vận hành hàng ngày bộ DevOps & Deployment
Toolkit — additive, không thay đổi Cart/Checkout/Payment/Computer
Vision/Event Bus/Database Schema.*
