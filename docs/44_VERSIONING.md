# Versioning

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Domain:** https://visionmart.thehuan.com
> **Document:** 44_VERSIONING.md
> **Status:** Implemented (Release Information, Release Candidate)

---

## Purpose

Mô tả cơ chế **Release Information** của VisionMart: cách hệ thống biết
và hiển thị "bản build này là gì" — phiên bản ứng dụng, git commit, thời
điểm build, Docker image tag, môi trường, phiên bản Python/Node/Database,
hệ điều hành/kernel — phục vụ vận hành (biết chính xác đang chạy bản nào
trên VPS) và cho báo cáo đồ án (bằng chứng minh bạch về phiên bản đã
kiểm thử).

## Scope

**Trong phạm vi:** `scripts/generate_release_info.py` (sinh manifest tĩnh
lúc build/deploy), `monitoring/collectors/release_info.py` (gộp manifest
tĩnh với dữ liệu runtime), endpoint `GET /api/release-info` và
`GET /api/v1/ops-monitoring/release-info`, hiển thị trên trang
"Giám sát hệ thống".

**Ngoài phạm vi:** không phải hệ thống quản lý phiên bản package
(semver cho thư viện nội bộ), không phải CI/CD pipeline đầy đủ — chỉ là
lớp "khai báo phiên bản hiện tại đang chạy", đọc read-only.

## Revision History

| Version | Date       | Author         | Description                                    |
| ------- | ---------- | -------------- | ------------------------------------------------ |
| 0.1.0   | -          | -              | Initial template created.                          |
| 1.0.0   | 2026-07-04 | VisionMart Eng | Release Information implemented & documented.       |

## Table of Contents

1. [Purpose](#purpose)
2. [Scope](#scope)
3. [Overview](#overview)
4. [Build-Time vs Runtime Separation](#build-time-vs-runtime-separation)
5. [`release_info.json` Schema](#release_infojson-schema)
6. [Generating Release Information](#generating-release-information)
7. [Viewing Release Information](#viewing-release-information)
8. [CI/CD Integration](#cicd-integration)
9. [Troubleshooting](#troubleshooting)
10. [Known Limitations](#known-limitations)
11. [References](#references)

---

## Overview

Release Information trả lời câu hỏi "phiên bản này build lúc nào, từ
commit nào, bằng Python/Node bản gì, đang chạy trên hệ điều hành nào" mà
**không cần SSH vào từng container để kiểm tra thủ công**. Thiết kế tách
rõ hai loại thông tin:

- **Build-time / static** — không đổi cho tới lần build kế tiếp (git
  commit, application version, Docker base image đã pin). Sinh một lần
  bởi `scripts/generate_release_info.py`, ghi ra `release_info.json` ở
  repo root.
- **Runtime / live** — chỉ biết được khi container đang chạy (Python
  version thực tế của container monitoring, hệ điều hành/kernel, phiên
  bản PostgreSQL đang kết nối). Đọc trực tiếp mỗi lần gọi API, không cache
  vào file.

## Build-Time vs Runtime Separation

```text
┌─────────────────────────────────┐        ┌──────────────────────────────────┐
│ scripts/generate_release_info.py │        │ monitoring/collectors/release_info.py│
│  (chạy 1 lần lúc build/deploy)   │        │  (chạy mỗi lần gọi API)              │
│                                   │        │                                       │
│  git rev-parse HEAD               │        │  sys.version (Python của container   │
│  git rev-parse --abbrev-ref HEAD  │        │              monitoring đang chạy)    │
│  git status --porcelain (dirty?)  │  đọc   │  platform.system()/release()/version()│
│  __version__ trong app/__init__.py│ ──────▶│  postgres_version (tái sử dụng từ     │
│  FROM python:.. trong Dockerfile  │  (ro)  │              system_resources.py,     │
│                                   │        │              KHÔNG mở kết nối DB mới)  │
│  → release_info.json              │        │                                       │
└─────────────────────────────────┘        └──────────────────────────────────┘
```

Tách riêng vì hai lý do:

1. Git/Docker-image facts **không cần và không nên** đọc lại mỗi request
   (git command chạy subprocess, không đáng để làm mỗi lần gọi API).
2. Container's OS/kernel/Python version **không thể** biết trước lúc
   build (phụ thuộc image nền thực tế lúc container khởi động) — bắt buộc
   phải đọc runtime.

## `release_info.json` Schema

```json
{
  "application_version": "0.1.0",
  "component_versions": {
    "backend": "0.1.0",
    "ai_engine": "0.1.0"
  },
  "git": {
    "commit": "a1b2c3d4e5f6...",
    "commit_short": "a1b2c3d",
    "branch": "main",
    "dirty": false
  },
  "build_time_utc": "2026-07-04T09:00:00+00:00",
  "docker_image_tag": "2026.07.04",
  "environment": "production",
  "pinned_runtimes": {
    "backend_python_image": "python:3.12-slim",
    "ai_engine_python_image": "python:3.12-slim",
    "frontend_node_image": "node:20-alpine"
  },
  "generator": "scripts/generate_release_info.py"
}
```

API trả về (`GET /api/release-info`) gộp thêm phần `runtime`:

```json
{
  "...": "toàn bộ field ở trên",
  "runtime": {
    "monitoring_python_version": "3.11.9",
    "os": "Linux",
    "os_release": "5.15.0-91-generic",
    "os_version": "#101-Ubuntu SMP ...",
    "machine": "x86_64",
    "database_version": "PostgreSQL 16.3 ..."
  },
  "honesty_note": "OS/kernel above are the monitoring container's own — on Linux this is the shared host kernel, but it is not a substitute for checking each service container individually if they ever run on different base images."
}
```

Nếu `release_info.json` chưa từng được sinh ra (mount `/app/repo:ro`
thiếu, hoặc chưa chạy script lần nào), mọi field tĩnh trả về `"unknown"`
thay vì lỗi 500 — collector không bao giờ raise vì thiếu file này.

## Generating Release Information

```bash
# Cách đơn giản nhất — dùng git/Dockerfile hiện có để suy luận version
python3 scripts/generate_release_info.py

# Ghi đè version/environment/image tag tường minh (khuyến nghị cho CI/CD)
DOCKER_IMAGE_TAG=2026.07.04 \
RELEASE_ENVIRONMENT_LABEL=production \
RELEASE_VERSION=1.2.0 \
python3 scripts/generate_release_info.py
```

`release_info.json` bị `.gitignore` (mục "Production Hardening") — đây
là artifact sinh ra mỗi build, không phải nguồn chân lý để commit vào git.
Chạy script này là bước bắt buộc thêm vào quy trình build/deploy (xem
[docs/DEPLOY_VPS.md §18.3](DEPLOY_VPS.md#183-health-score--release-information)).

## Viewing Release Information

- **Trang "Giám sát hệ thống"** (`/system-health`, sau khi đăng nhập
  admin) — panel "Thông tin phiên bản (Release Information)" ở cuối
  trang, hiển thị đầy đủ application version, git commit (rút gọn + tooltip
  đầy đủ, kèm badge "dirty" nếu build từ working tree có thay đổi chưa
  commit), branch, build time, Docker image tag, environment, phiên bản
  backend/ai-engine, Python/Node, database version, OS/kernel.
- **API trực tiếp**: `GET /api/v1/ops-monitoring/release-info` (JWT admin)
  hoặc `docker compose exec backend curl http://monitoring:8200/api/release-info -H "Authorization: Bearer $MONITORING_API_TOKEN"`.
- **CLI**: `docker compose exec monitoring python -m visionmart readiness`
  không bao gồm release info trực tiếp (đó là mục đích riêng của endpoint
  này) — dùng `curl`/trang web để xem.

## CI/CD Integration

Ví dụ bước thêm vào pipeline CI trước khi build image:

```yaml
# .github/workflows/ci.yml (ví dụ minh hoạ, điều chỉnh theo pipeline thật)
- name: Generate release info
  run: |
    DOCKER_IMAGE_TAG=${{ github.sha }} \
    RELEASE_ENVIRONMENT_LABEL=production \
    python3 scripts/generate_release_info.py
- name: Build images
  run: docker compose build
```

Vì `monitoring` mount `.:/app/repo:ro` (đọc toàn bộ repo, bao gồm file
vừa sinh ở bước build), không cần COPY riêng `release_info.json` vào
image monitoring — chỉ cần file tồn tại ở repo root lúc container khởi
động.

## Troubleshooting

| Triệu chứng | Nguyên nhân khả dĩ | Cách xử lý |
| ----------- | ------------------- | ---------- |
| Release Information hiển thị toàn "unknown" | Chưa chạy `scripts/generate_release_info.py` lần nào, hoặc mount `MONITORING_REPO_ROOT`/`.:/app/repo:ro` thiếu | Chạy script; kiểm tra `docker-compose.yml` service `monitoring` có volume `.:/app/repo:ro` |
| `git.dirty: null` thay vì `true`/`false` | `git status` thất bại (không phải git repo trong context chạy script, hoặc thiếu quyền) | Đảm bảo script chạy trong thư mục có `.git` (repo root); nếu chạy trong container không có `.git`, chạy script trên host trước khi build |
| `database_version` là "unknown (PostgreSQL unreachable or not yet polled)" | Poll đầu tiên của monitoring chưa hoàn tất, hoặc PostgreSQL không kết nối được | Đợi một chu kỳ poll (`MONITORING_POLL_INTERVAL_SECONDS`), hoặc kiểm tra `system.postgres.reachable` |
| `docker_image_tag` luôn là "dev" | Chưa set `DOCKER_IMAGE_TAG` khi chạy script trong CI/CD | Set biến môi trường này tường minh trong pipeline build |

## Known Limitations

- `component_versions` đọc `__version__` từ `app/__init__.py` của
  backend/ai-engine — nếu module đó chưa khai báo biến này, trả về
  "unknown" (không suy đoán từ git tag hay nơi khác).
- OS/kernel trong `runtime` là của **container monitoring**, không phải
  của từng container backend/ai-engine/frontend riêng lẻ — hợp lý vì mọi
  container Linux trên cùng VPS chia sẻ chung kernel host, nhưng nếu các
  service dùng base image khác nhau đáng kể (ví dụ một service chạy trên
  Alpine, một service khác chạy trên Debian), thông tin OS/kernel hiển
  thị không phản ánh khác biệt đó — đã ghi rõ trong `honesty_note` trả về
  từ API thay vì ẩn đi giới hạn này.
- Không có lịch sử phiên bản (version history/changelog tự động) — chỉ
  hiển thị phiên bản **hiện tại**. Xem `docs/45_RELEASE_NOTE.md` cho ghi
  chú phát hành thủ công theo từng version.

## References

- Health Score & Production Readiness (dùng chung dữ liệu system/postgres
  với Release Information): [docs/19_MONITORING.md](19_MONITORING.md)
- Deployment Validation (`doctor`, readiness report):
  [docs/46_DEPLOYMENT_VALIDATION.md](46_DEPLOYMENT_VALIDATION.md)
- Deploy VPS (bước tích hợp vào quy trình build):
  [docs/DEPLOY_VPS.md](DEPLOY_VPS.md)
- Release notes thủ công theo từng version: [docs/45_RELEASE_NOTE.md](45_RELEASE_NOTE.md)
- Code: `scripts/generate_release_info.py`, `monitoring/collectors/release_info.py`

---

*Tài liệu này mô tả cơ chế Release Information bổ sung ở giai đoạn Final
Production Readiness — additive, không thay đổi kiến trúc versioning
package/thư viện hiện có.*
