# Triển khai v3 lên VPS

Nhánh: `v3` · Commit: `19f87ad` · Chi tiết kỹ thuật: [AI_PIPELINE_UPGRADE.md](AI_PIPELINE_UPGRADE.md)

---

## Đọc trước 1 phút

v3 **không tự cải thiện độ chính xác khi vừa deploy**. Nó dựng đường ray:
mọi tính năng AI mới đều **tắt mặc định**, và tầng phân loại còn cần dữ liệu
huấn luyện chưa thu thập. Deploy v3 hôm nay = hệ thống chạy **y hệt v2**,
cộng thêm khả năng quan sát và các công tắc để bật dần.

Đây là điều tốt: có thể lên production an toàn rồi bật từng thứ có kiểm chứng.

---

## A. VPS chưa từng cài (lần đầu)

```bash
sudo mkdir -p /var/www && cd /var/www
sudo git clone -b v3 https://github.com/huanbv/VisionMart.git visionmart
cd visionmart
sudo bash scripts/setup-vps.sh
```

`setup-vps.sh` tự làm: Docker → firewall → sinh secrets → SSL Let's Encrypt →
build → up → migrate → seed admin. Chạy lại an toàn (không ghi đè secret/cert).

Đổi domain nếu cần:

```bash
sudo DOMAIN=visionmart.thehuan.com LE_EMAIL=huanbv9x@gmail.com bash scripts/setup-vps.sh
```

Chạy HTTP không SSL (test):

```bash
sudo SKIP_SSL=1 bash scripts/setup-vps.sh
```

---

## B. VPS đã chạy v2 → nâng lên v3

### B1. Sao lưu trước (bắt buộc)

v3 thêm 9 bảng. Migration chỉ thêm, không sửa bảng cũ, nhưng vẫn phải backup.

```bash
cd /var/www/visionmart
sudo bash scripts/backup-now.sh
```

### B2. Chuyển nhánh

```bash
cd /var/www/visionmart
sudo git fetch origin
sudo git checkout v3
```

### B3. Deploy

```bash
sudo bash scripts/deploy.sh
```

Script tự nhận ra `ai-engine/` có thay đổi và **rebuild cả ai-engine** — trước
đây nó chỉ build backend, sẽ để engine chạy code cũ.

> Build ai-engine mất vài phút (torch + ultralytics). Ép build:
> `sudo bash scripts/deploy.sh --with-ai-engine --with-frontend`

### B4. Kiểm tra

```bash
sudo bash scripts/health-check.sh
docker compose exec backend alembic current   # phải là 6d8e0a2b4c57
```

---

## C. Bật tính năng — theo thứ tự này

Mỗi bước bật **một** thứ và quan sát vài ngày. Tất cả chỉnh trong
**Admin → Cấu hình xử lý ảnh**, không cần sửa `.env`, không cần restart.

### Bước 1 — Telemetry (an toàn, làm ngay)

```
ENABLE_TELEMETRY = true
```

⚠️ **Cái này cần restart ai-engine** (task nền phải khởi tạo lúc startup):

```bash
docker compose restart ai-engine
```

Sau đó **Admin → Bảng điều khiển AI** bắt đầu có dữ liệu.

### Bước 2 — DEBUG_AI (xem ảnh từng bước)

```
DEBUG_AI = true
DEBUG_AI_SAMPLE_RATE = 0.05     ← QUAN TRỌNG
```

Cũng cần `docker compose restart ai-engine`.

> **Đừng để 1.0 trên camera thật.** Đó là ghi 9 file cho *mọi* khung hình:
> camera 30fps sẽ sinh ~23 triệu file/ngày. 0.05 = 5%, đủ để chẩn đoán.
> Theo dõi mục `dropped` ở `GET /ai/trace/debug/stats` — tăng đều nghĩa là
> MinIO không theo kịp, hãy **giảm sample rate**, đừng tăng queue.

### Bước 3 — Tiền xử lý ảnh (⚠️ phải đo A/B)

Đây là bước **duy nhất có thể làm hệ thống TỆ ĐI**.

Model hiện được train trên ảnh **chưa** tiền xử lý. Bật CLAHE/gamma chỉ ở lúc
nhận diện tạo ra lệch phân phối — ảnh "đẹp hơn với mắt người" nhưng *khác* với
thứ model đã học.

```bash
# Đo trước khi bật
docker compose run --rm evaluation
```

Bật từng cái một, đo lại, giữ cái nào cải thiện. Nếu quyết định dùng, phải áp
dụng **y hệt lúc train lại**.

### Bước 4 — Thu thập dữ liệu (2–4 tuần)

```
ENABLE_REVIEW_CAPTURE = true
```

Vào **Admin → Duyệt dữ liệu AI** duyệt nhãn đều đặn. Không có nút "duyệt hàng
loạt" — cố ý: train trên phán đoán của chính model sẽ khuếch đại lỗi của nó.

### Bước 5 — Train classifier

```bash
docker compose exec ai-engine python scripts/build_classifier_dataset.py \
  --database-url "$DATABASE_URL" --dry-run
```

Cần **≥100 ảnh/SKU** (tối thiểu 20, dưới mức đó script từ chối). Chưa đủ thì
quay lại bước 4.

Đủ rồi thì bỏ `--dry-run`, train, xuất ONNX vào `/models/sku_classifier.onnx`
kèm `sku_labels.json`, rồi:

```
ENABLE_SKU_CLASSIFIER = true
```

**Đo A/B trước khi tin.**

### Bước 6 — OCR (chỉ khi cần)

Chỉ bật nếu bước 5 vẫn nhầm sản phẩm cùng thương hiệu khác dung tích.

Engine **không có sẵn trong image**:

```bash
docker compose exec ai-engine pip install easyocr
```

```
ENABLE_OCR_FALLBACK = true
OCR_MAX_PER_FRAME = 3
```

Cần file catalog `/app/config/product_catalog.json`:

```json
{"<organization_id>": [
  {"sku": "AQUA-500",  "brand": "Aquafina", "volume_ml": 500},
  {"sku": "AQUA-1500", "brand": "Aquafina", "volume_ml": 1500}
]}
```

Không có file này thì OCR đọc được chữ nhưng **không tra ra SKU nào**.

### Bước 7 — Embedding (cuối cùng)

```
ENABLE_EMBEDDINGS = true
```

⚠️ `EMBEDDING_MIN_SIMILARITY=0.75` là **phỏng đoán, chưa đo**. Phải hiệu chỉnh
trên embedding thật của cửa hàng anh trước khi tin kết quả.

---

## D. Quay lui khi có sự cố

### Quay code về v2

```bash
cd /var/www/visionmart
sudo git checkout main
sudo bash scripts/deploy.sh --with-ai-engine
```

**Không cần hạ migration.** 9 bảng mới không bảng cũ nào tham chiếu tới; để
nguyên là an toàn nhất.

### Nếu thật sự cần bỏ bảng

```bash
docker compose exec backend alembic downgrade 5c7d9e1f3a46
```

Mất lịch sử dashboard, không mất dữ liệu nghiệp vụ.

### Tắt nhanh một tính năng gây sự cố

Vào Admin → Cấu hình xử lý ảnh → tắt cờ. **Có hiệu lực trong 1 giây**, không
cần restart (trừ `ENABLE_TELEMETRY` và `DEBUG_AI`).

---

## E. Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Dashboard AI rỗng | `ENABLE_TELEMETRY` tắt, hoặc chưa restart engine | Bật + `docker compose restart ai-engine` |
| Có khung hình, không có ảnh bước | `DEBUG_AI` tắt lúc chụp khung đó | Bình thường — bật rồi chờ khung mới |
| `dropped` tăng đều | MinIO chậm hơn tốc độ chụp | **Giảm** `DEBUG_AI_SAMPLE_RATE` |
| Bật classifier mà không đổi gì | Không có file model → tự rơi về class_map | Kiểm tra log engine, xem `/models/` |
| OCR bật mà không tác dụng | Chưa cài engine, hoặc thiếu catalog | `pip install easyocr` + tạo catalog |
| RAM cao khi nhiều camera | `SHARE_YOLO_WEIGHTS=false` | Đặt `true` (mặc định) |
| Đĩa đầy nhanh | `DEBUG_AI_SAMPLE_RATE` quá cao | Giảm + dọn prefix `ai-debug/` |

---

## F. Việc chưa làm — cần theo dõi thủ công

**Chưa có job dọn dẹp tự động.** Bảng telemetry và ảnh debug sẽ **tăng vô hạn**.
Cho tới khi có job theo lịch (đề xuất ở mục 9 báo cáo), phải theo dõi:

```bash
docker compose exec postgres psql -U visionmart -c \
  "SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
   FROM pg_catalog.pg_statio_user_tables
   WHERE relname LIKE 'ai_%' ORDER BY pg_total_relation_size(relid) DESC;"
```

Mức lưu giữ đề xuất: `ai_frames`/`ai_logs` 7 ngày, `ai_detections` 30 ngày,
`ai_events` giữ vĩnh viễn (dữ liệu nghiệp vụ).
