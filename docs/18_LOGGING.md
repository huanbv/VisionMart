# Logging

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 18_LOGGING.md
> **Status:** Implemented (Log Rotation & Log Management, Release Candidate)

---

## Purpose

Mô tả chiến lược logging và log rotation trên toàn hệ thống VisionMart:
service nào ghi log ở đâu, cơ chế xoay vòng/nén/giữ lại của từng nhóm
service, và giá trị mặc định khuyến nghị — đảm bảo **log không bao giờ
phình vô hạn** trên một VPS có dung lượng đĩa hữu hạn.

## Scope

**Trong phạm vi:** cấu hình logging của `backend`, `ai-engine`,
`celery-worker`/`celery-beat`, `frontend`, `nginx` (qua Docker logging
driver), và 3 service Python độc lập tự quản lý log file riêng:
`monitoring/`, `backup/`, `evaluation/`.

**Ngoài phạm vi:** không thay đổi format log nghiệp vụ hiện có của
backend/ai-engine (`LOG_FORMAT=json|text` đã tồn tại từ trước) — tài liệu
này chỉ bổ sung phần **rotation/retention/compression**, không đổi nội
dung log ghi ra.

## Revision History

| Version | Date       | Author         | Description                                    |
| ------- | ---------- | -------------- | ------------------------------------------------ |
| 0.1.0   | -          | -              | Initial template created.                          |
| 1.0.0   | 2026-07-04 | VisionMart Eng | Log Rotation & Log Management implemented & documented. |

## Table of Contents

1. [Purpose](#purpose)
2. [Scope](#scope)
3. [Overview](#overview)
4. [Two Logging Mechanisms](#two-logging-mechanisms)
5. [Docker-Driver-Covered Services](#docker-driver-covered-services)
6. [Standalone Python Services](#standalone-python-services)
7. [Recommended Defaults](#recommended-defaults)
8. [Structured JSON Logging](#structured-json-logging)
9. [Viewing Logs](#viewing-logs)
10. [Disk Usage Estimate](#disk-usage-estimate)
11. [Troubleshooting](#troubleshooting)
12. [Known Limitations](#known-limitations)
13. [References](#references)

---

## Overview

VisionMart có **hai nhóm service khác nhau về cách sinh log**, nên dùng
hai cơ chế rotation khác nhau thay vì cố ép về một chuẩn chung (tránh
over-engineering — mỗi nhóm dùng cơ chế tự nhiên nhất với runtime của nó):

1. **Service chạy trong container do Docker quản lý stdout/stderr**
   (backend, ai-engine, celery-worker, celery-beat, frontend, nginx) —
   rotation ở tầng **Docker logging driver**, không cần sửa code ứng dụng.
2. **Service Python độc lập tự ghi log ra file riêng** (monitoring,
   backup, evaluation) — dùng `logging.handlers.RotatingFileHandler` của
   Python với hook nén gzip, vì các service này log ra file thay vì chỉ
   stdout (để log còn giữ lại được ngay cả khi container bị xoá).

## Two Logging Mechanisms

| | Docker logging driver | `RotatingFileHandler` + gzip |
| - | - | - |
| Áp dụng cho | backend, ai-engine, celery-worker, celery-beat, frontend, nginx | monitoring, backup, evaluation |
| Cấu hình ở đâu | `docker-compose.yml` (`x-logging` anchor) | `<service>/logging_config.py` |
| Nén | Có (driver `local` tự nén rotated file) | Có (hook `namer`/`rotator` tự viết, gzip) |
| Giới hạn kích thước | `LOG_MAX_FILE_SIZE` (mặc định 100m) | `<PREFIX>_LOG_MAX_BYTES` (mặc định 10MB) |
| Số file giữ lại | `LOG_MAX_FILES` (mặc định 5) | `<PREFIX>_LOG_BACKUP_COUNT` (mặc định 5) |
| Xem log | `docker compose logs <service>` | `tail -f <LOG_DIR>/<service>.log`, hoặc mount volume ra ngoài |

## Docker-Driver-Covered Services

`docker-compose.yml` định nghĩa một anchor dùng chung:

```yaml
x-logging: &default-logging
  # "local" (Docker >= 20.10) thay cho "json-file" mặc định: cùng ngữ
  # nghĩa max-size/max-file, nhưng file đã xoay vòng được LƯU NÉN sẵn —
  # cho mọi service (backend, ai-engine, celery, frontend, nginx,
  # monitoring) khả năng nén log tương đương gzip mà KHÔNG cần sửa code
  # ứng dụng nào.
  driver: local
  options:
    max-size: "${LOG_MAX_FILE_SIZE:-100m}"
    max-file: "${LOG_MAX_FILES:-5}"
```

Mỗi service áp dụng `logging: *default-logging`. `docker logs <container>`
hoạt động y hệt như với driver `json-file` mặc định — không cần thay đổi
thói quen vận hành nào. Tổng dung lượng log tối đa cho một service
= `LOG_MAX_FILE_SIZE × LOG_MAX_FILES` (mặc định 100MB × 5 = 500MB mỗi
service, đã nén nên dung lượng thực tế trên đĩa thường nhỏ hơn nhiều).

Đây là lựa chọn "reuse existing components" — không thêm bất kỳ dependency
hay code logging mới nào vào backend/ai-engine/frontend, chỉ đổi một dòng
cấu hình Docker.

## Standalone Python Services

`monitoring/logging_config.py`, `backup/logging_config.py`,
`evaluation/logging_config.py` đều dùng cùng một pattern nhỏ (cố ý
**không** dùng chung một hàm import — mỗi package tự chứa bản sao của
mình để image Docker của từng service độc lập hoàn toàn, không phụ thuộc
lẫn nhau):

```python
def _gzip_namer(name: str) -> str:
    return name + ".gz"

def _gzip_rotator(source: str, dest: str) -> None:
    with open(source, "rb") as sf, gzip.open(dest, "wb") as df:
        df.writelines(sf)
    os.remove(source)

file_handler = logging.handlers.RotatingFileHandler(
    log_path, maxBytes=cfg.log_max_bytes, backupCount=cfg.log_backup_count,
)
file_handler.namer = _gzip_namer
file_handler.rotator = _gzip_rotator
```

`RotatingFileHandler` tự động xoá file rotated cũ nhất khi vượt quá
`backupCount` — không cần thêm code cleanup riêng cho phần log file.

| Service | Biến môi trường | Thư mục mặc định | File log |
| ------- | ---------------- | ------------------ | -------- |
| `monitoring` | `MONITORING_LOG_DIR`, `MONITORING_LOG_MAX_BYTES`, `MONITORING_LOG_BACKUP_COUNT` | `/data/logs` | `monitoring.log`, `monitoring.log.1.gz`, ... |
| `backup` | `BACKUP_LOG_DIR`, `BACKUP_LOG_MAX_BYTES`, `BACKUP_LOG_BACKUP_COUNT` | `/data/logs` | `backup.log`, `backup.log.1.gz`, ... |
| `evaluation` | (đặt `--output-dir`, log ghi vào `<output_dir>/logs/evaluation.log`) | `evaluation_results/logs` | `evaluation.log` (mỗi lần chạy CLI, không phải service dài hạn) |

## Recommended Defaults

Theo đúng đề bài: **30 ngày / 100MB mỗi file / nén gzip**. Áp dụng cụ thể:

| Biến | Giá trị mặc định | Ghi chú |
| ---- | ------------------ | ------- |
| `LOG_MAX_FILE_SIZE` | `100m` | Docker driver, áp dụng cho 5 service dùng chung anchor |
| `LOG_MAX_FILES` | `5` | 5 file × 100MB = 500MB tối đa mỗi service (trước khi nén) |
| `MONITORING_LOG_MAX_BYTES` / `BACKUP_LOG_MAX_BYTES` | `10485760` (10MB) | Nhỏ hơn Docker driver vì các service này log ít hơn nhiều (chỉ log vận hành nội bộ, không log request nghiệp vụ) |
| `MONITORING_LOG_BACKUP_COUNT` / `BACKUP_LOG_BACKUP_COUNT` | `5` | ~50MB mỗi service trước khi nén |
| `MONITORING_RETENTION_DAYS` | `30` | **Khác** với rotation log file — đây là số ngày giữ **dữ liệu SQLite** (snapshot/alert), xem `monitoring/storage/retention.py` |
| `BACKUP_RETENTION_DAYS` | `14` (đề xuất 7/30/90 tuỳ nhu cầu) | Số ngày giữ **file backup zip**, không phải log |

"30 ngày" cho log file thuần tuý (không phải dữ liệu SQLite/backup) không
được áp dụng trực tiếp vì `RotatingFileHandler` xoay theo **kích thước**,
không theo thời gian — lý do: một đợt tăng đột biến hoạt động (nhiều
alert, nhiều request lỗi) không được phép làm phình log vô hạn chỉ vì
chưa đủ 30 ngày. Kết hợp `LOG_MAX_BYTES × BACKUP_COUNT` đã đảm bảo trần
dung lượng tuyệt đối bất kể thời gian.

## Structured JSON Logging

Backend/ai-engine đã hỗ trợ `LOG_FORMAT=json|text` từ trước (không phải
tính năng mới của Release Candidate này). `monitoring`/`backup` dùng
format text đơn giản (`%(asctime)s %(levelname)s %(name)s: %(message)s`)
vì khối lượng log nhỏ và mục đích chính là đọc trực tiếp khi debug, không
đưa vào pipeline log-aggregation tập trung (ELK/Loki) ở quy mô VPS đơn
hiện tại của dự án.

## Viewing Logs

```bash
# Docker-driver-covered services
docker compose logs -f backend
docker compose logs -f --tail=200 ai-engine

# Standalone Python services (file trực tiếp trong volume)
docker compose exec monitoring tail -f /data/logs/monitoring.log
docker compose exec backup tail -f /data/logs/backup.log

# Xem file đã nén
docker compose exec monitoring sh -c "zcat /data/logs/monitoring.log.1.gz | tail -100"
```

## Disk Usage Estimate

Trần dung lượng log tối đa trên một VPS chạy đủ 12 service (trước khi
nén, worst-case):

- 5 service dùng Docker driver × 500MB = 2.5GB
- `monitoring` + `backup` × ~50MB = 100MB
- `evaluation` không chạy liên tục — log chỉ sinh ra khi chạy CLI thủ công

Tổng **~2.6GB worst-case, không nén**; với nén gzip thực tế (log text nén
tốt, thường 5-10x), con số thực tế trên đĩa thấp hơn đáng kể. Đây là trần
cứng — log **không bao giờ** vượt quá con số này bất kể hệ thống chạy bao
lâu, đúng yêu cầu "never allow unlimited log growth".

## Troubleshooting

| Triệu chứng | Nguyên nhân khả dĩ | Cách xử lý |
| ----------- | ------------------- | ---------- |
| `docker compose logs` không thấy log cũ (> 5 file trước) | Đúng hành vi thiết kế — driver `local` chỉ giữ `LOG_MAX_FILES` file gần nhất | Tăng `LOG_MAX_FILES`/`LOG_MAX_FILE_SIZE` trong `.env` nếu cần giữ lâu hơn (đánh đổi dung lượng đĩa) |
| `monitoring.log`/`backup.log` không xoay vòng dù đã lớn hơn `LOG_MAX_BYTES` | Biến `MONITORING_LOG_MAX_BYTES`/`BACKUP_LOG_MAX_BYTES` bị đặt sai đơn vị (phải là **byte**, không phải MB) | Kiểm tra `.env`: `10485760` = 10MB, không phải `10` |
| File `.gz` xuất hiện nhưng file gốc không bị xoá | Lỗi hiếm nếu tiến trình bị kill giữa lúc `_gzip_rotator` đang chạy | Không nguy hiểm — lần rotate kế tiếp sẽ dọn tiếp; có thể xoá tay file gốc thừa nếu chắc chắn nó đã được nén |
| `docker compose logs` báo log driver không hỗ trợ `--since`/`--follow` | Một số driver không phải `json-file`/`local` giới hạn tính năng CLI | Driver `local` **có hỗ trợ** đầy đủ `docker logs` (khác `journald`/`syslog`); nếu gặp lỗi này kiểm tra lại đúng driver đang dùng bằng `docker inspect <container> \| grep LogConfig -A5` |

## Known Limitations

- Không có log-aggregation tập trung (ELK/Loki/Grafana Loki) — ở quy mô
  VPS đơn hiện tại, `docker compose logs`/file trực tiếp là đủ. Xem
  [Future Improvements trong docs/19_MONITORING.md](19_MONITORING.md#future-improvements)
  cho hướng mở rộng Prometheus/Grafana nếu quy mô tăng.
- Rotation của 3 service Python độc lập theo **kích thước**, không theo
  **thời gian** — một service gần như không log gì (ví dụ `backup` giữa
  các lần chạy cron) có thể giữ log rất cũ (nhiều tháng) miễn là chưa đạt
  ngưỡng dung lượng. Đây là đánh đổi có chủ đích (ưu tiên trần dung lượng
  tuyệt đối) chứ không phải thiếu sót.

## References

- Docker `local` logging driver:
  [Docker documentation](https://docs.docker.com/config/containers/logging/local/)
- Python `logging.handlers.RotatingFileHandler`:
  [Python standard library documentation](https://docs.python.org/3/library/logging.handlers.html#rotatingfilehandler)
- Monitoring service (SQLite retention, khác với log file retention):
  [docs/19_MONITORING.md](19_MONITORING.md#log-rotation--retention)
- Backup & log dir kiểm tra bởi doctor command:
  [docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md)
- Code: `docker-compose.yml` (`x-logging` anchor), `monitoring/logging_config.py`,
  `backup/logging_config.py`, `evaluation/logging_config.py`

---

*Tài liệu này mô tả chiến lược log rotation & log management bổ sung ở
giai đoạn Final Production Readiness — additive, không thay đổi nội dung
log nghiệp vụ hiện có.*
