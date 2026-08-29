# Deployment Validation & Production Safety

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 46_DEPLOYMENT_VALIDATION.md
> **Status:** Implemented (Production Readiness Report, `visionmart doctor`, Production Safety Audit — Release Candidate)

---

## Purpose

Mô tả package `visionmart/` — engine kiểm tra dùng chung cho hai mục
đích: **Production Readiness Report** (Part 5, xem qua API/dashboard) và
lệnh **`visionmart doctor`** (Part 6, chạy tay/từ script deploy). Tài
liệu này cũng ghi lại **audit an toàn sản xuất** (Part 7) — xác nhận mọi
thành phần mới thêm ở giai đoạn Final Production Readiness (backup, log
rotation, health score, release info, readiness report, doctor) đều
read-only đối với production, theo đúng yêu cầu của đề bài.

## Scope

**Trong phạm vi:** `visionmart/` (package mới), endpoint
`GET /api/readiness` (monitoring) và `GET /api/v1/ops-monitoring/readiness`
(backend proxy), lệnh `python -m visionmart doctor`, và audit an toàn cho
toàn bộ 6 phần đã triển khai ở giai đoạn này (Backup, Logging, Health
Score, Release Info, Readiness, Doctor).

**Ngoài phạm vi:** không sửa Shopping Cart, Checkout, Payment, Computer
Vision, Event Bus, Database Schema — đúng theo ràng buộc "Do NOT" của đề
bài. `visionmart/` không viết bất kỳ dữ liệu nghiệp vụ nào.

## Revision History

| Version | Date       | Author         | Description                                                   |
| ------- | ---------- | -------------- | ---------------------------------------------------------------- |
| 1.0.0   | 2026-07-04 | VisionMart Eng | Production Readiness Report, doctor command, safety audit implemented. |

## Table of Contents

1. [Purpose](#purpose)
2. [Scope](#scope)
3. [Overview](#overview)
4. [Why One Shared Engine](#why-one-shared-engine)
5. [Check Categories](#check-categories)
6. [Production Readiness Report (API)](#production-readiness-report-api)
7. [`visionmart doctor` (CLI)](#visionmart-doctor-cli)
8. [Where to Run It](#where-to-run-it)
9. [Production Safety Audit](#production-safety-audit)
10. [Troubleshooting](#troubleshooting)
11. [Known Limitations](#known-limitations)
12. [References](#references)

---

## Overview

`visionmart/` là package Python độc lập thứ tư trong dự án theo cùng
nguyên tắc kiến trúc với `monitoring/`, `backup/`, `evaluation/`: không
import `backend.app.*`/`ai_engine.app.*`. Khác với 3 package kia,
`visionmart/` **được phép** import `monitoring.collectors.*` — vì
`monitoring` là một package độc lập khác (không phải `app` package của
backend/ai-engine), và vì đây chính là cách hiện thực hoá yêu cầu "reuse
existing components... avoid duplicate functionality" của đề bài: logic
kiểm tra PostgreSQL/Redis/Celery/Docker/host-resources/camera/evaluation
**đã tồn tại** trong `monitoring/collectors/`, nên `visionmart/checks.py`
gọi lại các hàm đó thay vì viết lại.

```text
┌─────────────────────────────────────────────────────────┐
│                    visionmart/checks.py                  │
│                                                            │
│  Tái sử dụng (import từ monitoring/collectors/*):         │
│    check_database()   → collect_postgres_status()          │
│    check_redis()      → collect_redis_status()              │
│    check_celery()     → collect_celery_status()              │
│    check_docker()     → collect_docker_status()                │
│    check_camera()     → collect_camera_health()                  │
│    check_evaluation() → check_evaluation_reports()                  │
│    check_disk_space() → collect_host_resources()                      │
│                                                                          │
│  Mới (chưa có collector nào tương ứng):                                  │
│    check_configuration()  — biến môi trường bắt buộc có set chưa           │
│    check_security()       — secret có còn là giá trị mặc định không          │
│    check_storage()        — MinIO reachable                                    │
│    check_backup()         — thư mục backup ghi được + có backup gần đây không     │
│    check_logging()        — thư mục log của 3 service Python ghi được không         │
│    check_monitoring_service() — GET /health của monitoring service                     │
│    check_python_dependencies() — package Python quan trọng có import được không            │
└─────────────────┬─────────────────────────────────┬───────────────────┘
                   ▼                                 ▼
     visionmart/readiness.py                 visionmart/doctor.py
     (Part 5 — API, JSON, theo category)      (Part 6 — CLI, bảng text, exit code)
                   │                                 │
                   ▼                                 ▼
     monitoring/server.py GET /api/readiness   `python -m visionmart doctor`
     → backend proxy /ops-monitoring/readiness
```

## Why One Shared Engine

Đề bài yêu cầu rõ: *"Avoid duplicate functionality"*. Nếu xây riêng biệt
"readiness report" và "doctor command" — hai bộ code gần như trùng lặp
100% logic kiểm tra (cả hai đều cần biết Postgres/Redis/Celery/Docker/
Camera/... có OK không) — sẽ vi phạm trực tiếp yêu cầu này, và mọi thay
đổi ngưỡng/logic sau này phải sửa hai nơi, dễ lệch nhau. Thay vào đó:

- `visionmart/checks.py` chứa **toàn bộ logic kiểm tra** (một hàm cho mỗi
  loại kiểm tra, trả về `CheckResult` chuẩn hoá).
- `visionmart/readiness.py` chỉ **gộp** kết quả theo category → JSON,
  phục vụ Part 5.
- `visionmart/doctor.py` chỉ **định dạng** kết quả thành bảng text +
  quyết định exit code, phục vụ Part 6.

Không có logic kiểm tra nào bị viết hai lần.

## Check Categories

`run_all_checks()` chạy 28 check, nhóm theo 14 category (13 category đề
bài yêu cầu cho Part 5 + 1 category bổ sung "Python Dependencies" riêng
cho Part 6):

| Category | Check(s) | Nguồn |
| -------- | -------- | ----- |
| Configuration | 13 biến môi trường bắt buộc (DATABASE_URL, REDIS_URL, CELERY_BROKER_URL, BACKEND_SECRET_KEY, MINIO_*, BACKUP_DIR, MONITORING_*) | Mới |
| Security | Secret không còn giá trị mặc định (`.env.example` placeholder); `APP_DEBUG=false` khi `APP_ENV=production` | Mới |
| Database | PostgreSQL kết nối được + phiên bản server | `monitoring.collectors.system_resources` |
| Redis | Redis `PING` thành công | `monitoring.collectors.system_resources` |
| Celery | Có ít nhất 1 worker phản hồi `ping` | `monitoring.collectors.system_resources` |
| Docker | Container có tiền tố `visionmart-` đều `running`/healthy | `monitoring.collectors.system_resources` |
| Camera | Đọc được bảng `cameras`, có camera đăng ký, camera online | `monitoring.collectors.camera_health` |
| Evaluation | Có báo cáo evaluation gần đây (optional, không bao giờ FAIL) | `monitoring.collectors.evaluation_health` |
| Storage | MinIO reachable, bucket tồn tại | Mới |
| Backup | Thư mục `BACKUP_DIR` ghi được, có backup trong ngưỡng retention | Mới |
| Logging | Thư mục log của `monitoring`/`backup`/`evaluation` ghi được | Mới |
| Monitoring | `GET /health` của monitoring service trả 200 | Mới |
| Health | Dung lượng đĩa còn trống đủ (ngưỡng theo `MONITORING_ALERT_DISK_PERCENT`) | `monitoring.collectors.system_resources` |
| Python Dependencies | Package quan trọng (`sqlalchemy`, `asyncpg`, `redis`, `celery`, `docker`, `psutil`) import được | Mới |

Mỗi check trả về đúng một trong ba trạng thái: `PASS`, `WARNING`, `FAIL`
— không có trạng thái mơ hồ nào khác, và mỗi `WARNING`/`FAIL` luôn kèm
`recommendation` (bước cụ thể để khắc phục), không chỉ báo lỗi suông.

## Production Readiness Report (API)

```bash
# Qua backend proxy (JWT admin)
curl -fsS https://visionmart.thehuan.com/api/v1/ops-monitoring/readiness \
     -H "Authorization: Bearer <jwt-token>" | jq

# Trực tiếp trong container monitoring (không cần JWT, dùng token riêng)
docker compose exec monitoring python -m visionmart readiness
```

Response JSON có cấu trúc:

```json
{
  "generated_at": 1783159287.82,
  "overall_status": "PASS" | "WARNING" | "FAIL",
  "counts": {"PASS": 24, "WARNING": 3, "FAIL": 1},
  "categories": {"Database": [...], "Redis": [...], "...": [...]},
  "checks": [{"category": "...", "name": "...", "status": "...", "detail": "...", "recommendation": "..." }]
}
```

`overall_status` là `FAIL` nếu có bất kỳ check nào `FAIL`, `WARNING` nếu
không có `FAIL` nhưng có `WARNING`, ngược lại `PASS`.

## `visionmart doctor` (CLI)

```bash
docker compose exec monitoring python -m visionmart doctor
```

In ra báo cáo dạng bảng, nhóm theo category, sắp xếp FAIL trước WARNING
trước PASS trong mỗi nhóm, có khuyến nghị khắc phục cho từng mục không
PASS, và một dòng tổng kết:

```
Summary: 24 PASS, 3 WARNING, 1 FAIL (of 28 checks)
Result: FAIL -- one or more critical checks failed. Review the items above before deploying.
```

**Exit code**: `0` nếu không có `FAIL` nào (kể cả khi có `WARNING`), `1`
nếu có ít nhất một `FAIL` — dùng được trực tiếp trong script deploy để
chặn deploy khi có lỗi nghiêm trọng:

```bash
docker compose exec monitoring python -m visionmart doctor || {
    echo "Doctor check failed — aborting deploy." >&2
    exit 1
}
```

## Where to Run It

`visionmart/` tái sử dụng `monitoring.collectors.*`, nên cần đúng tập
dependency mà `monitoring/requirements.txt` đã cài (`sqlalchemy`,
`asyncpg`, `redis`, `celery`, `docker`, `psutil`, `minio`, `httpx`) —
package này **không có `requirements.txt` riêng** (cố ý, để không có gì
mới phải pin/duy trì). Cách chạy được khuyến nghị:

```bash
# Khuyến nghị: bên trong container monitoring (đã có sẵn mọi dependency)
docker compose exec monitoring python -m visionmart doctor

# Thay thế: máy host/CI đã cài `pip install -r monitoring/requirements.txt`
python3 -m visionmart doctor
```

Nếu chạy từ một môi trường thiếu một số package tuỳ chọn (ví dụ container
`backend` không có `docker`/`psutil`), các check tương ứng tự báo
`WARNING` (không phải `FAIL`) và gợi ý chạy trong container monitoring để
có kết quả đầy đủ — không bao giờ crash vì thiếu import.

## Production Safety Audit

Theo yêu cầu Part 7 của đề bài, dưới đây là audit tường minh, function
theo function, xác nhận mọi thứ mới thêm ở giai đoạn Release Candidate
này là read-only đối với production:

| Yêu cầu | Xác nhận |
| ------- | -------- |
| Mọi thứ chỉ đọc trừ khi có chủ đích rõ ràng | `visionmart/checks.py`: mọi hàm chỉ `SELECT`/`PING`/`GET`/`stat()`. **Ngoại lệ duy nhất, có chủ đích**: `check_backup()`/`check_logging()` tạo một file rỗng tạm thời (`.visionmart_doctor_write_test_<timestamp>`) trong thư mục backup/log để xác minh quyền ghi, rồi xoá ngay lập tức (`_dir_writable()`) — đây là cách duy nhất để thực sự biết một thư mục có ghi được hay không mà không dựa vào `os.access()` (không đáng tin cậy với một số filesystem network-mounted); không đụng tới bất kỳ file dữ liệu thật nào. |
| Backup không bao giờ làm gián đoạn production | Đã audit ở [docs/43_BACKUP_RECOVERY.md §Production Safety](43_BACKUP_RECOVERY.md#production-safety) — `pg_dump` không khoá bảng, SQLite Online Backup API an toàn với ghi đồng thời, MinIO chỉ đọc object. |
| Monitoring không bao giờ sửa production | Đã audit ở [docs/19_MONITORING.md](19_MONITORING.md) từ giai đoạn trước — không đổi trong Release Candidate này; `health_score.py`/`release_info.py` mới thêm cũng chỉ đọc snapshot đã có sẵn trong SQLite của monitoring, không mở kết nối ghi nào tới production. |
| Evaluation phải cô lập | Không đổi ở giai đoạn này — `check_evaluation()` trong `visionmart/checks.py` chỉ gọi `check_evaluation_reports()` (đọc thư mục filesystem), không chạy evaluation, không import `evaluation.*`. |
| Doctor command không bao giờ sửa dữ liệu | Xác nhận bằng cách đọc toàn bộ `visionmart/checks.py`: không có `INSERT`/`UPDATE`/`DELETE`/`fput_object`/`docker.*.start()`/`docker.*.stop()` ở bất kỳ đâu — chỉ `SELECT`, `GET`, `PING`, `stat()`, và thao tác file tạm nêu trên. |
| Health Score chỉ tổng hợp số liệu đã có | Không đổi từ Part 3 — `compute_health_score()` không thu thập dữ liệu mới, chỉ tính toán trên `snapshots` đã tồn tại. |

**Xác minh bằng thực thi thật**: đã chạy `run_all_checks()` với biến môi
trường trỏ tới các service không tồn tại (DNS resolution failure có chủ
đích) để xác nhận mọi lỗi được bắt gọn gàng (`FAIL` với lý do rõ ràng),
không có ngoại lệ nào rò rỉ ra ngoài, và không có bất kỳ side-effect nào
ngoài 2 file tạm bị tạo-rồi-xoá-ngay đã nêu ở trên.

## Troubleshooting

| Triệu chứng | Nguyên nhân khả dĩ | Cách xử lý |
| ----------- | ------------------- | ---------- |
| `python -m visionmart doctor` báo FAIL toàn bộ Configuration | Chạy ngoài Docker network, thiếu file `.env` được load vào môi trường | Chạy `docker compose exec monitoring python -m visionmart doctor` thay vì chạy trần trên host |
| Check "Docker containers healthy" luôn WARNING | Không mount `/var/run/docker.sock` (mặc định tắt, xem `docs/19_MONITORING.md`) | Bình thường nếu cố ý không bật — đây là check tuỳ chọn, không bao giờ chặn deploy (chỉ WARNING, không FAIL) |
| `GET /api/readiness` trả 502 | Monitoring service chưa chạy | `docker compose ps monitoring`; `docker compose logs monitoring` |
| Doctor chạy rất chậm (>10s) | `check_celery`/`check_docker` timeout do broker/Docker socket không phản hồi | Bình thường trong trường hợp service thật sự down — mỗi check đã có timeout riêng (Celery 3s, HTTP 5-10s) nên tổng thời gian có trần, không treo vô hạn |

## Known Limitations

- `check_python_dependencies()` chỉ kiểm tra package import được trong
  **tiến trình đang chạy doctor**, không kiểm tra package đã cài trong
  các container khác (backend/ai-engine) — không có cách chung để kiểm
  tra dependency của một container khác mà không SSH/exec vào nó, nằm
  ngoài phạm vi một check nhẹ.
- Production Readiness Report **không có giao diện dashboard riêng** ở
  Release Candidate này (chỉ có API + CLI) — Health Score (Part 3) đã có
  giao diện nổi bật theo đúng yêu cầu đề bài, nhưng đề bài không yêu cầu
  readiness report cụ thể phải hiển thị trên dashboard, nên phần này được
  giữ ở mức "expose via API" như đề bài ghi rõ, tránh over-engineering.
  Xem [Future Improvements](#future-improvements-note) — có thể thêm
  trang riêng nếu cần.
- Doctor/readiness không tự động chạy định kỳ — là công cụ chạy tay/từ
  script deploy, không phải một alert liên tục (Health Score/Alert Engine
  đã đảm nhiệm vai trò giám sát liên tục).

## Future Improvements Note

- Trang dashboard riêng cho Production Readiness Report (bảng
  category × PASS/WARNING/FAIL, có thể lọc), nếu nhu cầu vận hành thực tế
  cho thấy cần xem thường xuyên hơn là API/CLI.
- Test-restore tự động tích hợp vào `check_backup()` (hiện chỉ kiểm tra
  tuổi/tồn tại của file backup, chưa xác minh khôi phục được — xem thêm
  [docs/43_BACKUP_RECOVERY.md §Known Limitations](43_BACKUP_RECOVERY.md#known-limitations)).

## References

- Automatic Backup System: [docs/43_BACKUP_RECOVERY.md](43_BACKUP_RECOVERY.md)
- Log Rotation & Log Management: [docs/18_LOGGING.md](18_LOGGING.md)
- Health Score & Release Information: [docs/19_MONITORING.md](19_MONITORING.md), [docs/44_VERSIONING.md](44_VERSIONING.md)
- Deploy VPS checklist (tích hợp doctor vào quy trình deploy):
  [docs/DEPLOY_VPS.md](DEPLOY_VPS.md)
- Code: `visionmart/` (toàn bộ package), `monitoring/server.py` (`/api/readiness`),
  `backend/app/modules/ops_monitoring/api/router.py` (`/readiness` proxy)

---

*Tài liệu này mô tả Production Readiness Report, lệnh `visionmart doctor`,
và audit an toàn sản xuất bổ sung ở giai đoạn Final Production Readiness —
additive, không thay đổi Cart/Checkout/Payment/Computer Vision/Event
Bus/Database Schema.*
