# Migration Recovery & Validation Report

> **Project:** VisionMart - Enterprise AI Smart Retail Platform
> **Document:** 51_MIGRATION_RECOVERY_REPORT.md
> **Status:** Migration history repaired, fully self-contained, verified by
> real execution against a brand-new empty PostgreSQL database. No external
> schema (schema.sql or otherwise) was available or used — ORM models are
> the sole source of truth, as required.

---

## 1. Sự cố ban đầu

Chạy `scripts/setup-production.sh` trên VPS (Megahost, `/var/opt/visionmart`)
để dựng stack từ đầu. Bước `alembic upgrade head` thất bại ngay khi Alembic
nạp revision map, trước khi chạy bất kỳ câu SQL nào:

```
KeyError: '6fa79a26c4de'
```

Sau đó, `schema.sql` lấy từ database/backup được cho là "đã có schema" hoá
ra **hoàn toàn trống** (`\dt` → "Did not find any relations.", không có
bảng `alembic_version`, không có bảng nghiệp vụ nào). Vì vậy: **không có
bất kỳ database hay schema tham chiếu nào tồn tại** — toàn bộ việc phục
hồi phải dựa 100% vào ORM models và bản thân chuỗi migration hiện có
trong repo, không có gì khác để đối chiếu. Báo cáo này được viết lại theo
đúng thực tế đó (phiên bản trước có đề cập một bước "đối chiếu
`schema.sql`" — bước đó nay bị loại bỏ vì không có dữ liệu để đối chiếu).

**Nguyên nhân gốc:** file
`backend/alembic/versions/7a1b3c5d9e0f_add_stock_movements.py` (migration
*cũ nhất* theo Create Date, 2026-06-30) khai báo:

```python
revision = "7a1b3c5d9e0f"
down_revision = "6fa79a26c4de"
```

nhưng revision `6fa79a26c4de` **chưa từng tồn tại** trong toàn bộ lịch sử
git của repo (xác minh bằng `git log --all -S"6fa79a26c4de"` — không có
kết quả nào, và bằng cách liệt kê `revision`/`down_revision` của cả 12
file migration hiện có — không file nào khai báo `revision =
"6fa79a26c4de"`). Đây là migration nền tảng (tạo `organizations`, `users`,
`products`, `branches`, ...) đáng lẽ phải được generate và commit đầu
tiên khi dự án khởi tạo, nhưng chưa bao giờ được tạo ra. Lỗi này có sẵn
trong codebase, không phải do DevOps toolkit gây ra, và chỉ lộ ra khi lần
đầu tiên chạy migration trên một database hoàn toàn trống.

## 2. Phạm vi và ràng buộc

- ORM models (SQLAlchemy) là nguồn sự thật **duy nhất** để dựng lại
  migration còn thiếu — không có schema tham chiếu nào khác tồn tại.
- Không được bịa schema, không được tạo migration giữ chỗ (placeholder)
  rỗng.
- Giữ nguyên toàn bộ 12 migration hiện có, chỉ thêm migration còn thiếu.
- Mọi thay đổi `revision`/`down_revision` phải được giải thích rõ.
- Không sửa business logic, Computer Vision, Checkout, Monitoring,
  Evaluation.

**Duy nhất một file được thêm mới, không file nào khác trong repo bị
sửa:**

```
backend/alembic/versions/6fa79a26c4de_initial_schema_recovered.py   (MỚI)
```

## 3. Kiểm kê toàn bộ ORM models và toàn bộ chuỗi migration

**ORM models** — `backend/app/models/__init__.py` (HEAD) import 12
module hạ tầng model: `ai_training`, `audit`, `camera`, `catalog`,
`customer`, `detection`, `employee`, `identity`, `inventory`,
`notification`, `sales`, `tenancy`. Mỗi bảng kế thừa `Entity` (UUID PK +
`created_at`/`updated_at` + `deleted_at`/`is_deleted` + `created_by`/
`updated_by`), `ImmutableEntity` (không soft-delete, dùng cho
`audit_logs`), hoặc `AssociationBase` (bảng M2M composite key).

**Chuỗi migration hiện có** (12 file, trước khi sửa) — parse
`revision`/`down_revision` của từng file cho thấy toàn bộ đều nối được
với nhau thành một chuỗi tuyến tính duy nhất, **ngoại trừ** điểm đầu:

```
7a1b3c5d9e0f (add_stock_movements)      down_revision = "6fa79a26c4de"   ← THIẾU, không tồn tại
  → 8b2c4d6e1f02 (add_detection_events)
  → 9c3d5e7f2a13 (fix_stock_movements_audit_columns)
  → a4e6f8b1c703 (stock_movements_id_default)
  → b5f7a2c9d813 (detection_events_id_default)
  → c6a8b3d0e924 (detection_events_image_key)
  → d7b9c4e1f035 (camera_auto_capture)
  → e8c1f5a3b724 (camera_alert_overrides)
  → f9d2e4b6a835 (checkout_zone_payment)
  → 0abc1d2e3f45 (ai_training)
  → 1bcd2e3f4a56 (ai_training_is_deleted)
  → 2f4a6c8e0b13 (cart_pending_checkout)               ← head
```

12 migration này đều giả định các bảng nền tảng
(`organizations`/`users`/`products`/`branches`/...) đã tồn tại từ trước —
không migration nào trong số đó tạo ra các bảng đó. Đây chính là migration
duy nhất bị thiếu: **migration nền tảng ban đầu** (initial schema),
đáng lẽ phải có `down_revision = None`.

## 4. Xác định đúng trạng thái ORM cần dùng để dựng lại migration nền tảng

Migration `7a1b3c5d9e0f` (add stock_movements) đã tồn tại và có nội dung
cố định — nó tạo bảng `stock_movements` với FK trỏ tới
`organizations`/`products`/`branches`/`users`. Vì vậy migration nền tảng
bị thiếu phải phản ánh đúng **trạng thái ORM tại thời điểm ngay trước khi
`stock_movements` được thêm vào** — không phải trạng thái ORM hiện tại
(HEAD), vì HEAD đã có thêm `StockMovement`, `DetectionEvent`,
`TrainingImage`, `TrainingJob` là những model xuất hiện **sau** đó.

Bằng khảo cổ git (`git log --diff-filter=A --all`, `git show <sha>:<path>`,
đối chiếu Create Date của từng migration), xác định: commit `67bfa7a4c`
(cha trực tiếp của commit thêm `7a1b3c5d9e0f` + model `StockMovement`) là
trạng thái ORM đúng cần dùng. Tại commit đó, `app/models/__init__.py` chỉ
import 10 module (chưa có `ai_training`, chưa có `detection`), và module
`inventory` chỉ có model `Inventory` (chưa có `StockMovement`) — khớp
chính xác với những gì `7a1b3c5d9e0f` giả định đã tồn tại.

## 5. Dựng lại migration nền tảng (từ ORM models, không viết tay DDL)

1. Trích xuất cây thư mục tại commit `67bfa7a4c` (`git archive`, không
   dùng `git checkout` để không đụng working tree).
2. Cài đúng bộ dependency đã pin trong `requirements.txt`
   (SQLAlchemy==2.0.36, alembic==1.13.3, asyncpg==0.30.0, ...).
3. Dựng một PostgreSQL 16.2 thật, trống, không cần root/docker (gói
   `pgserver` — PostgreSQL nhúng chạy trong sandbox không có quyền sudo).
4. Chạy thật:
   ```bash
   alembic revision --autogenerate -m "initial schema (recovered)"
   ```
   với `target_metadata = Base.metadata` trỏ đúng ORM tại commit
   `67bfa7a4c`. Alembic tự so sánh metadata với database trống và sinh ra
   toàn bộ `op.create_table(...)` — không dòng DDL nào do tôi viết tay hay
   suy đoán.
5. **Thay đổi thủ công duy nhất:** đổi `revision` Alembic tự sinh
   (`17595b00ff76`) thành `6fa79a26c4de`, `down_revision = None`. Lý do:
   `6fa79a26c4de` là giá trị mà `7a1b3c5d9e0f` **đã tham chiếu sẵn** —
   đặt đúng giá trị này khiến chuỗi tự nối liền, không cần sửa bất kỳ file
   nào khác trong 12 file hiện có. Không có câu DDL nào bị thay đổi trong
   bước này.
6. Copy file kết quả vào `backend/alembic/versions/`.

Migration mới tạo 20 bảng nền tảng: `organizations`, `permissions`,
`branches`, `categories`, `roles`, `system_settings`, `users`,
`audit_logs`, `cameras`, `customers`, `employees`, `notifications`,
`products`, `refresh_tokens`, `role_permissions`, `user_roles`,
`inventory`, `shopping_carts`, `orders`, `order_items` — đầy đủ FK (đúng
`ondelete` theo model), index, unique/check constraint, Postgres ENUM
(`notification_channel`, `notification_priority`, `notification_status`,
`cart_status`, `cart_source`, `order_status`), tên constraint theo đúng
naming convention của dự án (`app/database/base.py`).

## 6. Revision graph sau khi sửa (13 migration, một chuỗi tuyến tính duy nhất)

```
<base> (None)
   └─ 6fa79a26c4de   initial schema (recovered)             ★ MỚI THÊM
        └─ 7a1b3c5d9e0f   add stock_movements table
             └─ 8b2c4d6e1f02   add detection_events table
                  └─ 9c3d5e7f2a13   fix stock_movements audit columns
                       └─ a4e6f8b1c703   stock_movements id default
                            └─ b5f7a2c9d813   detection_events id default
                                 └─ c6a8b3d0e924   detection_events image_key
                                      └─ d7b9c4e1f035   camera auto_capture
                                           └─ e8c1f5a3b724   camera alert overrides
                                                └─ f9d2e4b6a835   checkout zone + payment
                                                     └─ 0abc1d2e3f45   ai training tables
                                                          └─ 1bcd2e3f4a56   ai_training is_deleted
                                                               └─ 2f4a6c8e0b13   cart pending_checkout (HEAD)
```

Không có nhánh rẽ (branch), không có nhiều head, không có tham chiếu vòng
lặp. Tổng cộng 13 revision, đúng một head (`2f4a6c8e0b13`), đúng một gốc
(`6fa79a26c4de`, `down_revision = None`).

## 7. Xác minh bằng thực thi thật trên database hoàn toàn mới, trống

Dựng một PostgreSQL 16.2 thật (không mock/SQLite), hoàn toàn tách biệt,
xác nhận trống trước khi chạy:

```
\dt  →  "Did not find any relations."
```

Chạy `alembic upgrade head` — **thứ tự thực thi** (khớp chính xác thứ tự
trong revision graph ở mục 6):

```
1.  <base>         → 6fa79a26c4de   initial schema (recovered)
2.  6fa79a26c4de    → 7a1b3c5d9e0f   add stock_movements table
3.  7a1b3c5d9e0f    → 8b2c4d6e1f02   add detection_events table
4.  8b2c4d6e1f02    → 9c3d5e7f2a13   add missing audit/soft-delete columns to stock_movements
5.  9c3d5e7f2a13    → a4e6f8b1c703   add gen_random_uuid() default to stock_movements.id
6.  a4e6f8b1c703    → b5f7a2c9d813   add gen_random_uuid() default to detection_events.id
7.  b5f7a2c9d813    → c6a8b3d0e924   add image_key to detection_events
8.  c6a8b3d0e924    → d7b9c4e1f035   add auto_capture_enabled to cameras
9.  d7b9c4e1f035    → e8c1f5a3b724   add per-camera alert overrides
10. e8c1f5a3b724    → f9d2e4b6a835   camera checkout zone + order payment fields
11. f9d2e4b6a835    → 0abc1d2e3f45   add ai training tables
12. 0abc1d2e3f45    → 1bcd2e3f4a56   add is_deleted column to ai training tables
13. 1bcd2e3f4a56    → 2f4a6c8e0b13   cart pending_checkout status + checkout token (HEAD)
```

**Kết quả: RC=0, cả 13 bước chạy thành công, không lỗi.**

Xác minh sau khi upgrade:

- `alembic heads` → đúng một head: `2f4a6c8e0b13`.
- `alembic current` → `2f4a6c8e0b13` (khớp head).
- `alembic history` → chuỗi tuyến tính đầy đủ 13 revision, không đứt
  đoạn, không vòng lặp.
- Bảng `alembic_version` được tạo tự động bởi chính Alembic, chứa đúng
  1 dòng: `version_num = 2f4a6c8e0b13`.
- Không còn `KeyError`, không revision thiếu, không phụ thuộc gãy.

### Bảng đã được tạo (25 bảng, kiểm tra trực tiếp `information_schema`)

| # | Bảng | Tạo bởi migration |
|---|---|---|
| 1 | organizations | 6fa79a26c4de |
| 2 | permissions | 6fa79a26c4de |
| 3 | branches | 6fa79a26c4de |
| 4 | categories | 6fa79a26c4de |
| 5 | roles | 6fa79a26c4de |
| 6 | system_settings | 6fa79a26c4de |
| 7 | users | 6fa79a26c4de |
| 8 | audit_logs | 6fa79a26c4de |
| 9 | cameras | 6fa79a26c4de |
| 10 | customers | 6fa79a26c4de |
| 11 | employees | 6fa79a26c4de |
| 12 | notifications | 6fa79a26c4de |
| 13 | products | 6fa79a26c4de |
| 14 | refresh_tokens | 6fa79a26c4de |
| 15 | role_permissions | 6fa79a26c4de |
| 16 | user_roles | 6fa79a26c4de |
| 17 | inventory | 6fa79a26c4de |
| 18 | shopping_carts | 6fa79a26c4de |
| 19 | orders | 6fa79a26c4de |
| 20 | order_items | 6fa79a26c4de |
| 21 | stock_movements | 7a1b3c5d9e0f (+ cột/index bổ sung ở 9c3d5e7f2a13, a4e6f8b1c703) |
| 22 | detection_events | 8b2c4d6e1f02 (+ cột/index bổ sung ở b5f7a2c9d813, c6a8b3d0e924) |
| 23 | ai_training_images | 0abc1d2e3f45 (+ cột is_deleted ở 1bcd2e3f4a56) |
| 24 | ai_training_jobs | 0abc1d2e3f45 (+ cột is_deleted ở 1bcd2e3f4a56) |
| 25 | alembic_version | tự động, do Alembic quản lý |

24 bảng nghiệp vụ + 1 bảng nội bộ của Alembic = khớp chính xác với
`Base.metadata.tables` hiện tại của toàn bộ 12 module ORM.

### Ghi chú kỹ thuật về `pgcrypto` (chỉ ảnh hưởng môi trường test, không phải lỗi migration)

Ba migration (`8b2c4d6e1f02`, `a4e6f8b1c703`, `b5f7a2c9d813`) có
`CREATE EXTENSION IF NOT EXISTS "pgcrypto"` mang tính phòng vệ, nhưng
không migration nào thực sự gọi hàm nào của `pgcrypto` — toàn bộ UUID đều
dùng `gen_random_uuid()`, hàm lõi có sẵn từ PostgreSQL 13 trở lên. Bản
PostgreSQL nhúng dùng để test (`pgserver`) không đi kèm contrib module
nào ngoài `plpgsql`/`vector`, nên câu lệnh này ban đầu lỗi trong môi
trường test. Image `postgres:16-alpine` chính thức dùng trên production
có sẵn contrib đầy đủ (đúng lý do `docker/postgres/init.sql` đã gọi
`CREATE EXTENSION pgcrypto` từ trước khi Alembic chạy). Để môi trường test
phản ánh đúng production, tôi thêm một extension "giả" no-op chỉ trong
virtualenv test tạm thời của tôi — **không đụng vào repo, không đụng vào
bất kỳ migration nào**.

## 8. Đối chiếu ORM ↔ database vừa dựng từ Alembic (phát hiện, không tự sửa)

Chạy `alembic check` (so sánh trực tiếp `Base.metadata` hiện tại với
database vừa dựng ở mục 7):

```
FAILED: New upgrade operations detected:
  add_index ix_ai_training_images_deleted_at (ai_training_images.deleted_at)
  add_index ix_ai_training_jobs_deleted_at   (ai_training_jobs.deleted_at)
```

Đây là một lỗ hổng có thật, **có từ trước, độc lập với migration nền tảng
bị thiếu** — tôi không tự sửa vì nó không thuộc phạm vi "chỉ sửa migration
nền tảng" và vì yêu cầu là báo cáo thay vì tự ý thay đổi schema. Chi tiết:

- `TrainingImage`, `TrainingJob` kế thừa `Entity` (UUID PK + `TimestampMixin`
  + `SoftDeleteMixin` + `AuditMixin`). `SoftDeleteMixin` khai báo **cả
  hai** cột `deleted_at` và `is_deleted` với `index=True`.
- Migration `0abc1d2e3f45_ai_training.py` (tạo bảng lần đầu) tự viết tay
  một hàm `_common_columns()` thay vì để Alembic autogenerate — hàm này
  **thiếu hẳn cột `is_deleted`**, và tạo `deleted_at` **không kèm index**.
- Migration kế tiếp `1bcd2e3f4a56_ai_training_is_deleted.py` bổ sung cột
  `is_deleted` và index của nó, nhưng bỏ sót index còn lại trên
  `deleted_at`.

Không có cột nào bị thiếu, không có bảng nào sai — chỉ thiếu đúng 2 index.
Nếu bạn muốn, tôi có thể thêm một migration thứ 14 (sau `2f4a6c8e0b13`)
chỉ để bổ sung 2 index này — chưa làm vì nằm ngoài phạm vi được giao lần
này.

## 9. Kết luận cuối cùng

| Hạng mục | Kết quả |
|---|---|
| Migration nền tảng bị thiếu | Đã xác định chính xác (`6fa79a26c4de`), đã dựng lại từ ORM models thật, không bịa schema, không dùng placeholder |
| Migration hiện có | Giữ nguyên toàn bộ 12 file, không sửa nội dung file nào |
| Revision graph | Một chuỗi tuyến tính 13 revision, một gốc, một head, không nhánh rẽ, không vòng lặp |
| `alembic upgrade head` từ DB trống hoàn toàn mới | **Thành công, RC=0**, xác minh bằng thực thi thật trên PostgreSQL 16.2 |
| Toàn bộ bảng được tạo | **Đúng** — 24 bảng nghiệp vụ, khớp `Base.metadata` |
| `alembic_version` | Được Alembic tự tạo đúng, chứa `2f4a6c8e0b13` |
| Revision thiếu / gãy / vòng lặp | **Không còn** |
| Khớp 100% với ORM hiện tại | Gần như hoàn toàn — chỉ thiếu 2 index không quan trọng (mục 8), lỗi có từ trước, đã báo cáo, chưa tự sửa |
| File bị thay đổi trong repo | Đúng 1 file mới: `backend/alembic/versions/6fa79a26c4de_initial_schema_recovered.py`. Không sửa business logic / Computer Vision / Checkout / Monitoring / Evaluation / bất kỳ migration nào khác |

**Xác nhận cuối cùng:** một VPS hoàn toàn mới, với database PostgreSQL
trống, có thể khởi tạo đầy đủ schema **chỉ bằng Alembic** — không cần bất
kỳ file `schema.sql`, backup, hay thao tác SQL thủ công nào. Đã xác minh
bằng thực thi thật (không mô phỏng), hai lần độc lập, trên hai database
trống khác nhau, cho cùng một kết quả.

## 10. Xác nhận thực tế trên production (Megahost VPS, 2026-07-04)

Sau khi commit chứa fix (`f8837f4 "Fix Alembic base migration and
production deployment"`) được đẩy lên `main`/tag `v1.0.0`, bạn đã chạy lại
`scripts/setup-production.sh` thật trên VPS Megahost. Log thực tế:

```
==> Applying database migrations (alembic upgrade head)
INFO  [alembic.runtime.migration] Running upgrade  -> 6fa79a26c4de, initial schema (recovered)
INFO  [alembic.runtime.migration] Running upgrade 6fa79a26c4de -> 7a1b3c5d9e0f, add stock_movements table
...
INFO  [alembic.runtime.migration] Running upgrade 1bcd2e3f4a56 -> 2f4a6c8e0b13, cart pending_checkout status + checkout token
  OK Migrations applied
```

Đúng 13 bước, đúng thứ tự, đúng như đã xác minh trong sandbox ở mục 6-7 —
**không phải mô phỏng, đây là lần chạy thật trên hạ tầng production.**

Hai điểm cần làm rõ trong log bạn gửi, để tránh hiểu nhầm là còn lỗi:

1. **Chuỗi log `ERROR: relation "cameras"/"organizations"/"shopping_carts"
   does not exist`** (từ `14:11:41` đến `14:53:19`) — đây là log **lịch sử
   còn sót lại từ lần deploy hỏng trước đó** (trước khi commit `f8837f4`
   tồn tại). `docker compose ps` cho thấy container `postgres` đã
   `Up 42 minutes` — tức là container Postgres này được giữ nguyên từ lần
   chạy `setup-production.sh` thất bại trước, khi backend liên tục poll
   những bảng chưa tồn tại. `docker compose logs -f` phát lại toàn bộ log
   cũ trước khi tail log mới. Migration thật của lần chạy này diễn ra
   *sau* toàn bộ các dòng lỗi đó, qua container tạm
   `visionmart-backend-run-...`, và thành công.
2. **`doctor` báo `FAIL: Backup directory ready` (`/var/backups/visionmart`
   không tồn tại)** — không liên quan đến Alembic/migration, đây là kiểm
   tra thư mục backup của DevOps toolkit (nằm ngoài phạm vi "chỉ sửa
   migration nền tảng" được giao). 5 mục `WARNING` còn lại (chưa có
   camera, monitoring chưa mount Docker socket, chưa có báo cáo
   evaluation, thư mục log evaluation chưa tạo, bucket MinIO chưa tạo)
   đều là trạng thái bình thường của một lần cài đặt mới, không liên quan
   migration.

**Kết luận:** đây là bằng chứng thực tế, độc lập với môi trường sandbox
của tôi, xác nhận đúng những gì mục 9 đã kết luận — VPS mới có thể khởi
tạo schema hoàn chỉnh chỉ bằng Alembic, sự cố `KeyError: '6fa79a26c4de'`
ban đầu đã được giải quyết triệt để.

## 11. Bước tiếp theo (tuỳ chọn, chưa thực hiện)

Nếu muốn schema khớp 100% với ORM (bao gồm cả 2 index bị thiếu ở mục 8),
tôi có thể thêm một migration mới, số 14, `down_revision =
"2f4a6c8e0b13"`, chỉ làm đúng một việc: `CREATE INDEX
ix_ai_training_images_deleted_at` và `CREATE INDEX
ix_ai_training_jobs_deleted_at`. Đây là thay đổi an toàn, không đụng dữ
liệu, không đụng bảng nào khác — nhưng tôi chưa làm vì nó nằm ngoài phạm
vi "chỉ sửa migration nền tảng bị thiếu" đã giao. Cho tôi biết nếu bạn
muốn tôi thực hiện.
