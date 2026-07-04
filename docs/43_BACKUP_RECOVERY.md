# Backup and Recovery

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 43_BACKUP_RECOVERY.md
> **Status:** Implemented (Automatic Backup System, `backup/`)

---

## Purpose

Mô tả hệ thống **backup tự động** của VisionMart (`backup/`, package độc
lập) — sao lưu PostgreSQL, SQLite của monitoring, báo cáo evaluation,
file upload trên MinIO, và cấu hình, đóng gói thành một file zip có
checksum, kèm quy trình restore thủ công (destructive, cần xác nhận).
Tài liệu này cũng ghi lại quan hệ với script backup/restore cũ hơn
(`scripts/backup.sh`, `scripts/restore.sh`) đã tồn tại từ trước trong dự án.

## Scope

**Trong phạm vi:** package `backup/` (service độc lập, hai docker-compose
service `backup`/`backup-once`), file zip đầu ra, quy trình restore thủ
công cho từng thành phần bên trong zip.

**Ngoài phạm vi:** không thay đổi Shopping Cart, Checkout, Payment, Event
Bus, hay Database Schema. Backup **chỉ đọc** đối với mọi nguồn dữ liệu nó
sao lưu — không bao giờ khoá bảng, dừng service, hay sửa dữ liệu production.

## Revision History

| Version | Date       | Author         | Description                                          |
| ------- | ---------- | -------------- | ----------------------------------------------------- |
| 0.1.0   | -          | -              | Initial template created.                              |
| 1.0.0   | 2026-07-04 | VisionMart Eng | Automatic Backup System implemented & documented.       |

## Table of Contents

1. [Purpose](#purpose)
2. [Scope](#scope)
3. [Overview](#overview)
4. [Architecture](#architecture)
5. [What Gets Backed Up](#what-gets-backed-up)
6. [Archive Format](#archive-format)
7. [Running a Backup](#running-a-backup)
8. [Retention & Cleanup](#retention--cleanup)
9. [Verification & Checksums](#verification--checksums)
10. [Restore Procedure](#restore-procedure)
11. [Relationship to `scripts/backup.sh` / `scripts/restore.sh`](#relationship-to-scriptsbackupsh--scriptsrestoresh)
12. [Production Safety](#production-safety)
13. [Troubleshooting](#troubleshooting)
14. [Known Limitations](#known-limitations)
15. [References](#references)

---

## Overview

`backup/` là một **package Python độc lập**, tuân theo đúng nguyên tắc
kiến trúc đã dùng cho `monitoring/` và `evaluation/`: không import
`backend.app.*` hay `ai_engine.app.*`, chỉ nói chuyện với phần còn lại
của hệ thống qua các kênh đã public sẵn (`pg_dump`, SQLite Online Backup
API, MinIO SDK, đọc file cấu hình trực tiếp trên đĩa).

Chạy được theo 2 chế độ, cả hai đều dùng chung code trong `backup/`:

- **`backup` service** (docker-compose profile `backup`): daemon nền,
  tự backup theo lịch cron (`BACKUP_CRON_SCHEDULE`, mặc định `0 2 * * *`
  — 2 giờ sáng hàng ngày), dùng `croniter` để tính lần chạy kế tiếp.
- **`backup-once` service** (docker-compose profile mặc định tắt, chạy
  thủ công hoặc từ cron của host): thực hiện đúng một lần backup rồi
  thoát — phù hợp cho ai đã có cron trên host và không muốn thêm một
  container luôn chạy nền.

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                    backup/ (package độc lập)                 │
│                                                                │
│  sources.py    ─▶ dump_postgres()          (pg_dump, subprocess)
│                ─▶ copy_monitoring_sqlite() (SQLite Online Backup API)
│                ─▶ copy_evaluation_reports()(shutil.copytree, đọc /app/repo:ro)
│                ─▶ download_minio_uploads() (minio SDK, fget_object)
│                ─▶ copy_config_files()      (shutil.copy2, đọc /app/repo:ro)
│  archive.py    ─▶ build_backup()  → zip + sha256 + verify_archive()
│  retention.py  ─▶ apply_retention() → xoá zip cũ hơn N ngày
│  scheduler.py  ─▶ croniter, vòng lặp daemon cho service "backup"
│  cli.py        ─▶ run | list | verify | cleanup | schedule
└──────────────────────┬─────────────────────────────────────┘
                        ▼
              /backups/visionmart-backup-<ts>.zip
              /backups/visionmart-backup-<ts>.zip.sha256
```

Mỗi nguồn (`SourceResult`) thất bại **độc lập** — MinIO down không làm
hỏng phần dump PostgreSQL, và ngược lại. `manifest.json` bên trong zip
ghi lại trung thực nguồn nào thành công/thất bại, không bao giờ báo "backup
hoàn tất" khi thực ra có phần bị thiếu.

## What Gets Backed Up

| Nguồn | Cơ chế | Ghi chú an toàn |
| ----- | ------ | ---------------- |
| PostgreSQL | `pg_dump -f postgres.sql` (plain SQL, `--no-owner --no-privileges`) | `pg_dump` không khoá bảng, không dừng DB — [tài liệu chính thức PostgreSQL](https://www.postgresql.org/docs/current/app-pgdump.html) xác nhận "does not block other users accessing the database". Timeout 30 phút. |
| Monitoring SQLite (`monitoring.db`) | SQLite **Online Backup API** (`sqlite3.Connection.backup()`) | An toàn ngay cả khi monitoring poller đang ghi WAL đồng thời — `shutil.copy` thường sẽ không an toàn trong trường hợp này (có thể copy file dở dang). |
| Evaluation reports | `shutil.copytree` từ thư mục đọc-only mount `/app/repo:ro` | Chỉ đọc, không có gì để "khoá" — thư mục evaluation là output tĩnh. |
| MinIO uploads (ảnh/video) | MinIO SDK `list_objects` + `fget_object` | Chỉ đọc object, không bao giờ xoá/ghi đè. Tắt được qua `BACKUP_INCLUDE_UPLOADS=false` nếu bucket quá lớn. |
| File cấu hình | `shutil.copy2`/`copytree` theo danh sách `BACKUP_CONFIG_FILES` | `.env` **bị loại trừ mặc định** (`BACKUP_INCLUDE_ENV_FILE=false`) vì chứa secret — chỉ bật khi cố ý và hiểu rủi ro lưu secret trong file backup. |

## Archive Format

```
visionmart-backup-2026-07-04-020000.zip
└── 2026-07-04/
    ├── postgres.sql
    ├── monitoring.db
    ├── evaluation/            (toàn bộ cây thư mục evaluation_results/)
    ├── uploads/                (toàn bộ object trong bucket MinIO, giữ nguyên object path)
    ├── config/                 (docker-compose.yml, .env.example, alembic.ini, docs/, ...)
    └── manifest.json           (nguồn nào OK/lỗi, cấu hình dùng lúc chạy, thời lượng)
visionmart-backup-2026-07-04-020000.zip.sha256   (checksum SHA-256 sidecar)
```

`manifest.json` ví dụ (rút gọn):

```json
{
  "backup_id": "2026-07-04-020000",
  "created_at": "2026-07-04T02:00:00+00:00",
  "sources": [
    {"name": "postgres", "ok": true, "detail": "Dumped database 'visionmart' from postgres:5432.", "bytes_written": 4821932},
    {"name": "monitoring_sqlite", "ok": true, "detail": "Copied ... via SQLite online backup API.", "bytes_written": 131072},
    {"name": "evaluation_reports", "ok": false, "detail": "Not found: ... (no evaluation run has produced reports yet)."},
    {"name": "uploads", "ok": true, "detail": "Downloaded 214 object(s) from bucket 'visionmart'.", "bytes_written": 88342011},
    {"name": "config_files", "ok": true, "detail": "Copied 7 path(s): docker-compose.yml, ..."}
  ],
  "sha256": "…",
  "verified": true,
  "overall_ok": true
}
```

`overall_ok` chỉ yêu cầu nguồn `postgres` thành công VÀ archive vượt qua
`verify_archive()` — các nguồn khác (evaluation, uploads) là "best effort",
thiếu chúng không được coi là backup thất bại toàn phần, nhưng vẫn được
ghi lại trung thực trong manifest để người vận hành biết.

## Running a Backup

```bash
# Một lần, thủ công (đọc .env hiện tại của stack)
docker compose run --rm backup-once

# Daemon nền, tự chạy theo BACKUP_CRON_SCHEDULE
docker compose --profile backup up -d backup

# Liệt kê các backup hiện có
docker compose run --rm backup-once python -m backup.cli list

# Backup thủ công không qua Docker (nếu chạy trực tiếp bằng Python, đã cài backup/requirements.txt)
python -m backup.cli run
```

Cron của host (thay vì scheduler trong-stack) — tương thích với thói quen
vận hành đã ghi trong `docs/DEPLOY_VPS.md` §13:

```bash
( crontab -l 2>/dev/null; echo "0 2 * * * cd /opt/visionmart && docker compose run --rm backup-once >> /var/log/visionmart-backup.log 2>&1" ) | crontab -
```

## Retention & Cleanup

- `BACKUP_RETENTION_DAYS` (mặc định 14, đề xuất 7/30/90 tuỳ nhu cầu) —
  sau mỗi lần `run` thành công, `retention.py` tự xoá các file
  `visionmart-backup-*.zip` (và `.sha256` đi kèm) cũ hơn ngưỡng này.
- Chạy cleanup độc lập, không tạo backup mới:
  ```bash
  docker compose run --rm backup-once python -m backup.cli cleanup
  ```
- Retention **không bao giờ** xoá backup gần nhất hiện có, kể cả khi nó
  đã cũ hơn ngưỡng — luôn giữ ít nhất 1 bản để tránh tình trạng "0 backup"
  do lỗi cấu hình retention quá ngắn.

## Verification & Checksums

Mỗi lần `run` tự động gọi `verify_archive()` ngay sau khi tạo zip:

1. `zipfile.testzip()` — phát hiện member bị hỏng (CRC sai, giải nén lỗi).
2. So khớp SHA-256 thực tế với file `.sha256` sidecar.

Kiểm tra thủ công một backup cũ bất kỳ:

```bash
docker compose run --rm backup-once python -m backup.cli verify \
    --file /backups/visionmart-backup-2026-07-04-020000.zip
```

Đã kiểm chứng bằng thực thi thật: cố ý làm hỏng byte trong một file zip
thật rồi chạy `verify` — trả về `FAIL: Archive is corrupt (decompression
error): ...` với exit code khác 0; một file zip hợp lệ trả `PASS` với exit
code 0.

## Restore Procedure

**Restore luôn là thao tác thủ công, có chủ đích, không tự động hoá** —
tránh trường hợp một script tự phục hồi đè lên dữ liệu production đang
tốt vì đọc nhầm tham số.

```bash
# 1. Dừng các service ghi vào Postgres (backend, worker) — KHÔNG dừng postgres
docker compose stop backend celery-worker celery-beat ai-engine

# 2. Giải nén archive cần khôi phục
mkdir -p /tmp/vm_restore && cd /tmp/vm_restore
unzip /backups/visionmart-backup-2026-07-04-020000.zip

# 3. Xác minh checksum trước khi restore (không restore từ archive không xác minh được)
sha256sum -c ../visionmart-backup-2026-07-04-020000.zip.sha256

# 4. Restore PostgreSQL (đè toàn bộ DB hiện tại — xác nhận đúng tên DB trước khi chạy)
docker compose exec -T postgres psql -U visionmart -d postgres \
    -c "DROP DATABASE IF EXISTS visionmart;" \
    -c "CREATE DATABASE visionmart OWNER visionmart;"
cat 2026-07-04/postgres.sql | docker compose exec -T postgres \
    psql -U visionmart -d visionmart

# 5. (Tuỳ chọn) Restore uploads MinIO — chỉ nếu bucket hiện tại bị mất/hỏng
docker run --rm --network visionmart_default \
    -v /tmp/vm_restore/2026-07-04/uploads:/restore minio/mc:latest \
    sh -c "mc alias set s3 http://minio:9000 \$MINIO_ROOT_USER \$MINIO_ROOT_PASSWORD && \
           mc mirror /restore s3/visionmart"

# 6. (Tuỳ chọn) Restore monitoring.db — dữ liệu vận hành, không phải nghiệp vụ,
#    có thể bỏ qua bước này nếu chấp nhận mất lịch sử giám sát cũ
docker compose stop monitoring
cp /tmp/vm_restore/2026-07-04/monitoring.db /path/to/monitoring_data_volume/monitoring.db
docker compose up -d monitoring

# 7. Khởi động lại các service đã dừng ở bước 1
docker compose up -d backend celery-worker celery-beat ai-engine

# 8. Xác minh
docker compose exec backend curl -fsS http://localhost:8000/health
docker compose exec monitoring python -m visionmart doctor
```

**Điểm khác biệt quan trọng so với `scripts/restore.sh` cũ**: archive mới
chứa `postgres.sql` (plain SQL, restore bằng `psql`, không phải
`pg_restore`) và không có `minio.tar.gz` (thay bằng thư mục `uploads/`
theo object path gốc, restore bằng `mc mirror`) — **không thể dùng
`scripts/restore.sh` cho archive do `backup/` tạo ra**, và ngược lại.

## Relationship to `scripts/backup.sh` / `scripts/restore.sh`

Dự án đã có sẵn một cặp script backup/restore đơn giản hơn từ giai đoạn
đầu (`scripts/backup.sh` dùng `pg_dump -F c` + `mc mirror` trực tiếp,
`scripts/restore.sh` dùng `pg_restore` + giải nén `minio.tar.gz`), và
`docs/DEPLOY_VPS.md` §13 cũng mô tả một biến thể cron thủ công tương tự.

Hệ thống `backup/` mới (Release Candidate) **không thay thế bằng cách
xoá** hai script cũ — chúng vẫn còn trong `scripts/` và vẫn chạy được độc
lập — nhưng là lựa chọn **được khuyến nghị cho triển khai mới** vì có
thêm: checksum + verify tự động, manifest trung thực theo từng nguồn,
retention tự động, hỗ trợ evaluation reports + config files, và tuân thủ
đầy đủ hơn nguyên tắc "backup không bao giờ dừng production" (dùng SQLite
Online Backup API thay vì có thể phải khoá file).

**Không trộn lẫn hai hệ thống trong cùng một chuỗi backup/restore** — định
dạng archive không tương thích với nhau (xem bảng trên).

## Production Safety

- Không có bước nào trong `backup/` dừng, khoá, hoặc ghi vào PostgreSQL,
  Redis, hay bảng nghiệp vụ — chỉ `SELECT`/dump/copy/download.
- `pg_dump` không chặn ghi/đọc khác trong lúc chạy (tài liệu chính thức
  PostgreSQL, xem [References](#references)).
- SQLite Online Backup API được thiết kế riêng cho tình huống "copy một
  DB có thể đang được ghi đồng thời" — an toàn hơn `shutil.copy` một file
  `.db` đang mở.
- Archive `.env` bị loại trừ theo mặc định — bảo vệ khỏi việc secret bị
  chép vào một file zip có thể nằm lâu dài trên đĩa hoặc bị đồng bộ ra
  ngoài offsite backup.
- Backup service chạy bằng chính user Docker container của nó — không
  cần và không được cấp quyền ghi vào volume dữ liệu Postgres/MinIO gốc.

## Troubleshooting

| Triệu chứng | Nguyên nhân khả dĩ | Cách xử lý |
| ----------- | ------------------- | ---------- |
| `postgres` source báo `ok: false`, "pg_dump binary not found" | Image `backup/Dockerfile` thiếu gói `postgresql-client` | Kiểm tra `backup/Dockerfile` đã cài `postgresql-client`; rebuild image |
| `uploads` source báo lỗi kết nối MinIO | `MINIO_ENDPOINT`/`MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` sai, hoặc backup container không cùng network | Kiểm tra `.env`; xác nhận service `backup` nằm trong network mặc định của `docker-compose.yml` |
| Archive `verify` báo checksum mismatch | File zip bị hỏng khi copy sang nơi khác (offsite), hoặc đĩa hỏng | Backup lại từ bản gần nhất còn nguyên; kiểm tra SMART/đĩa VPS |
| Backup chạy nhưng thư mục `/backups` trống | `BACKUP_DIR` trỏ sai đường dẫn giữa host và volume container | Kiểm tra mount volume `backups_data` trong `docker-compose.yml` khớp `BACKUP_DIR` |
| Scheduler (`backup` service) không chạy đúng giờ | `BACKUP_CRON_SCHEDULE` sai cú pháp cron, hoặc container đã bị `docker compose down` | `docker compose logs backup`; kiểm tra biểu thức cron bằng `croniter` |

## Known Limitations

- `pg_dump` xuất **plain SQL** (không phải custom format `-Fc`) để đơn
  giản hoá restore (`psql` thay vì `pg_restore`), đổi lại archive nén kém
  hơn một chút so với custom format — chấp nhận được ở quy mô VPS đơn của
  dự án này.
- Backup **không tự động test-restore** vào một DB tạm để xác minh dữ
  liệu khôi phục được đúng 100% — `verify_archive()` chỉ xác minh tính
  toàn vẹn của file zip (không hỏng, checksum khớp), không xác minh nội
  dung SQL restore thành công. Xem [Future Improvements](#future-improvements)
  — có thể thêm bước test-restore định kỳ vào một Postgres tạm nếu cần độ
  tin cậy cao hơn.
- MinIO backup tải từng object tuần tự (`fget_object` trong vòng lặp) —
  với bucket rất lớn (hàng trăm GB), thời gian backup có thể dài; chưa có
  cơ chế backup tăng dần (incremental).

## Future Improvements

- Test-restore tự động định kỳ vào một Postgres tạm (container riêng,
  không đụng dữ liệu production) để xác minh archive thực sự restore được,
  không chỉ toàn vẹn về mặt zip.
- Backup tăng dần (incremental) cho MinIO bằng `mc mirror --newer-than`
  hoặc tương đương, giảm thời gian backup khi bucket lớn.
- Đẩy backup ra offsite storage (S3-compatible khác vùng, hoặc rclone tới
  provider khác) — hiện tại chỉ lưu local trên VPS, một sự cố ổ đĩa VPS
  vẫn có thể mất cả dữ liệu gốc lẫn backup.

## Notes

`backup/` được kiểm thử bằng thực thi thực tế: chạy `python -m backup.cli
run` end-to-end trong sandbox phát triển (không có Postgres/MinIO thật —
xác nhận từng nguồn báo lỗi đúng, không crash toàn bộ tiến trình), cố ý
làm hỏng một file zip thật để xác nhận `verify` phát hiện đúng lỗi giải
nén (không phải chỉ `BadZipFile`), và xác nhận `cleanup`/retention xoá
đúng file cũ hơn ngưỡng mà không đụng tới bản gần nhất.

## References

- [PostgreSQL: pg_dump does not block other users](https://www.postgresql.org/docs/current/app-pgdump.html)
- [SQLite Online Backup API](https://www.sqlite.org/backup.html)
- Deploy VPS (checklist go-live tích hợp backup): [docs/DEPLOY_VPS.md](DEPLOY_VPS.md)
- Log management: [docs/18_LOGGING.md](18_LOGGING.md)
- Deployment Validation (doctor kiểm tra thư mục/backup gần nhất):
  [docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md)
- Code: `backup/` (toàn bộ package), `scripts/backup.sh`, `scripts/restore.sh` (hệ thống cũ, vẫn còn trong repo)

---

*Tài liệu này mô tả hệ thống Automatic Backup System bổ sung ở giai đoạn
Final Production Readiness — không thay thế các script backup/restore cũ
hơn đã có trong dự án, chỉ bổ sung một lựa chọn được khuyến nghị hơn.*
