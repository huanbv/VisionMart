# Nâng cấp pipeline AI VisionMart — Báo cáo kỹ thuật

**Ngày:** 23/07/2026 · **Phạm vi:** `ai-engine/`, `backend/`, `frontend/`

---

## 1. Kiến trúc cũ và điểm yếu

### 1.1 Pipeline trước nâng cấp

```
Camera → JPEG → YOLOv8+ByteTrack → class_to_sku.json → sự kiện giỏ hàng
```

Một tầng duy nhất. Danh tính sản phẩm đến từ **ánh xạ tĩnh tên lớp COCO → SKU**.

### 1.2 Bốn điểm yếu cốt lõi

**(a) Một lớp COCO = một SKU.** Mọi chai nước — Aquafina, Lavie, 500ml, 1.5L — đều là lớp `bottle`. Ánh xạ tĩnh gán tất cả về **cùng một SKU**. Đây là nguyên nhân gốc của tỉ lệ sai mà anh quan sát được, và **không có ngưỡng confidence nào sửa được** vì mô hình không hề sai — nó nhận đúng "đây là cái chai".

**(b) `trainer.py` dùng bounding box phủ toàn ảnh.** Điều này biến detector thành classifier trá hình: nó học "ảnh này là sản phẩm X" chứ không học *định vị*. Hệ quả là khi có nhiều sản phẩm trong khung, detector không tách được chúng. Đây là bằng chứng trực tiếp cho kiến trúc hai tầng.

**(c) Tiền xử lý đã có nhưng mọi cờ đều `false`.** Module `vision/` đã cài CLAHE, gamma, denoise, ROI — nhưng mặc định tắt hết và chỉ sửa được qua `.env` (phải restart container).

**(d) Không quan sát được.** Admin chỉ thấy **một ảnh kết quả**. Không có cách nào trả lời "vì sao khung hình này nhận sai".

### 1.3 Vấn đề tài nguyên

`_get_model(camera_key)` nạp **một model YOLO cho mỗi camera**, dù mọi camera dùng chung một file weights. RAM tăng tuyến tính theo số camera.

---

## 2. Kiến trúc mới

```
Camera
  └─→ [capture]      giải mã
  └─→ [preprocess]   ROI → gamma tự động → CLAHE → bilateral → unsharp → khử nhiễu
  └─→ [quality gate] sáng/tương phản/nét — loại khung hỏng TRƯỚC khi tốn GPU
  └─→ [detector]     YOLOv8  (weights DÙNG CHUNG mọi camera)
  └─→ [tracker]      ByteTrack (trạng thái RIÊNG từng camera)
  └─→ [cropper]      cắt vùng có padding theo tỉ lệ
  └─→ [classifier]   MobileNetV3 → SKU cụ thể  ◄── tầng 2 MỚI
  └─→ [ocr]          đọc nhãn khi tầng 2 lưỡng lự  ◄── MỚI
  └─→ [embedding]    vector đặc trưng, khớp sản phẩm chưa từng train  ◄── MỚI
  └─→ [matcher]      gộp confidence → quyết định SKU
  └─→ [logger]       telemetry → 9 bảng DB
  └─→ [storage]      8 ảnh từng bước + pipeline.json (worker nền)
  └─→ [dashboard]    xem lại toàn bộ hành trình
```

### 2.1 Thứ tự quyết định trong matcher

| Ưu tiên | Nguồn | Điều kiện |
|---|---|---|
| 1 | `classifier` | confidence ≥ ngưỡng |
| 2 | `ocr` | đọc được thương hiệu + dung tích khớp catalog |
| 3 | `class_map` | hành vi cũ, giữ nguyên |
| 4 | `none` | không kết luận, thà không biết còn hơn đoán bừa |

**OCR đứng TRÊN class_map, không phải dưới.** Class_map trả cùng một SKU cho mọi vật thể cùng lớp YOLO; chữ đọc được trên nhãn là bằng chứng riêng của *vật thể này*. Bằng chứng cụ thể phải thắng ánh xạ vốn không phân biệt được chúng.

---

## 3. Danh sách file

### 3.1 File mới — ai-engine

| File | Vai trò |
|---|---|
| `app/vision/crop/cropper.py` | Cắt vùng từ bbox, padding theo tỉ lệ |
| `app/vision/classify/classifier.py` | MobileNetV3, 2 backend ONNX/torch |
| `app/vision/matching/matcher.py` | Chuỗi confidence + quyết định SKU |
| `app/vision/ocr/reader.py` | OCR fallback + parse dung tích/thương hiệu |
| `app/vision/embedding/extractor.py` | Vector đặc trưng, cosine, quyết định mở |
| `app/vision/storage/step_writer.py` | Worker nền ghi ảnh từng bước |
| `app/vision/trace.py` | Trace đồng bộ từng stage |
| `app/services/sku_identifier.py` | Điều phối crop→classify→ocr→match |
| `app/services/telemetry_client.py` | Đẩy telemetry lên dashboard |
| `app/services/review_capture.py` | Thu thập mẫu cho active learning |
| `app/api/trace.py`, `app/api/vision_config.py` | API trace + cấu hình runtime |
| `scripts/build_classifier_dataset.py` | Dựng dataset từ nhãn người duyệt |

### 3.2 File mới — backend

| File | Vai trò |
|---|---|
| `modules/ai_pipeline/infrastructure/models.py` | 9 bảng telemetry |
| `modules/ai_pipeline/application/telemetry_service.py` | Ghi telemetry |
| `modules/ai_pipeline/application/query_service.py` | Đọc cho dashboard |
| `modules/ai_pipeline/api/router.py` | 9 endpoint |
| `modules/ai_training/application/review_service.py` | Hàng đợi duyệt |
| `modules/ai_training/application/regression_gate.py` | Chặn deploy model kém đi |
| `alembic/versions/6d8e0a2b4c57_*.py` | Migration 9 bảng |

### 3.3 File mới — frontend

`src/api/aiPipeline.ts`, `src/pages/AiPipelineDashboardPage.tsx`, `src/pages/VisionConfigPage.tsx`, `src/pages/AiReviewPage.tsx`

### 3.4 File sửa (không đổi API công khai)

`vision/enhance.py`, `vision/config.py`, `services/person_tracker.py`, `api/frame.py`, `services/product_mapper.py`, `services/object_storage.py`, `catalog/models.py` + schemas

---

## 4. Chín bảng telemetry

| Bảng | Nội dung | Lưu giữ đề xuất |
|---|---|---|
| `ai_sessions` | Một lượt chạy của một camera | 90 ngày |
| `ai_frames` | Chất lượng, thời gian, prefix ảnh | 7 ngày |
| `ai_tracks` | Vòng đời một vật thể + SKU chốt | 30 ngày |
| `ai_detections` | Từng bbox YOLO | 30 ngày |
| `ai_classifications` | SKU + hạng nhì + biên | 30 ngày |
| `ai_ocr` | Chữ đọc được + phân tích | 30 ngày |
| `ai_embeddings` | Vector đặc trưng | vô hạn |
| `ai_logs` | Log theo stage, truy vấn được | 7 ngày |
| `ai_events` | Kết luận nghiệp vụ | **vô hạn** |

**Dùng `ImmutableEntity` chứ không `Entity`** — bỏ 5 cột soft-delete/audit. `ai_frames` tăng ~2,5 triệu dòng/camera/ngày. Quan trọng hơn số byte: một detection *xoá mềm được* sẽ cho phép dashboard nói dối về việc AI đã làm gì.

---

## 5. Kết quả đo được

| Hạng mục | Đo | Kết quả |
|---|---|---|
| Cache theo track | classify lần 1 / lần 2 | **242 ms → ~0 ms** |
| Worker ảnh | `submit()` trên đường nóng | **0,009 ms** |
| Worker ảnh | nhồi 40 job / hàng đợi 4 | **0,5 ms**, 36 bỏ, không chặn |
| Telemetry | nhồi 50 report / buffer 5 | **0,23 ms**, giữ 5 mới nhất |
| RAM YOLO | 8 camera | **8 model → 1** (giảm ~88% RAM model) |
| Confidence | yolo .94 + clf .98 + ocr .91 | 0,951 |
| Confidence | yolo .20 + clf .99 | **0,424** (trung bình cộng: 0,60) |
| OCR parse | 7 định dạng nhãn tiếng Việt | **7/7 đúng** |
| Catalog | 7 tình huống brand+volume | **7/7 đúng** |
| Telemetry ingest | 3 khung tốt + 1 hỏng | **3 ghi / 1 bỏ**, batch sống |
| Tenant isolation | org khác đọc session | **0** |

### 5.1 Trường hợp OCR sửa lỗi classifier

```
classifier → AQUA-1500 (conf 0.45, biên 0.04)   ← ĐOÁN SAI
OCR        → "AQUAFINA 500ml"
kết quả    → AQUA-500, nguồn=ocr, conf=0.895     ← ĐÃ SỬA
```

---

## 6. Không phá vỡ chức năng cũ

Kiểm chứng bằng máy: **không cờ `enable_*` nào bật mặc định**.

```
Cac co enable_* dang BAT mac dinh: KHONG CAI NAO
Matcher tat het -> SKU=SKU-OLD nguon=class_map conf=0.9
=> y het hanh vi truoc nang cap
```

Ngoại lệ duy nhất: `share_yolo_weights=True`. Đây là tối ưu bộ nhớ, **không đổi kết quả** — cùng weights, cùng đầu ra, trạng thái tracker vẫn tách riêng từng camera (đã test: chuyển camera không kế thừa track id, quay lại khôi phục đúng).

**72 cài đặt đều sửa được từ Admin**, không cần `.env`, không cần restart.

---

## 7. Rủi ro còn lại

### 7.1 Classifier chưa có nhiên liệu — RỦI RO CAO NHẤT

Code xong và test kỹ, nhưng cần **~100–300 ảnh/SKU đã được người xác nhận**. Chạy `build_classifier_dataset.py --dry-run` để biết hiện có bao nhiêu. Đường thu thập là hàng đợi duyệt, cần **vài tuần vận hành thật**.

**Nghĩa là: bật classifier hôm nay chưa cải thiện độ chính xác.** Toàn bộ P1–P5 dựng sẵn đường ray.

### 7.2 Lệch phân phối train/inference

Model hiện được train trên ảnh **chưa qua tiền xử lý**. Bật tiền xử lý chỉ ở inference **có thể LÀM GIẢM độ chính xác**. Bắt buộc:
1. Đo A/B qua framework `evaluation/` sẵn có
2. Nếu dùng tiền xử lý, phải áp dụng **y hệt lúc train**

### 7.3 Ngưỡng embedding chưa hiệu chỉnh

`0.75 / 0.05` là giá trị khởi điểm, **không phải kết quả đo**. Test cho thấy trên vector 576 chiều, nhiễu nhẹ đã kéo cosine xuống 0.177. Phải hiệu chỉnh trên embedding thật trước khi tin.

### 7.4 OCR nặng và dễ vỡ

300 MB–1 GB. Cây phụ thuộc PaddleOCR xung đột với version ultralytics đủ thường xuyên để làm image ai-engine khó rebuild. Nếu bật trên nhiều camera → tách container riêng (`TODO(ocr-service)`).

### 7.5 Chưa đo được benchmark thật

**Không thể đưa PSNR/SSIM/mAP trước-sau** nếu không có hệ thống đang chạy và tập test có nhãn. Framework đo đã có (Precision/Recall/F1/IoU/confusion matrix) — cần dữ liệu.

### 7.6 Frontend chưa typecheck

Máy phát triển không có `node_modules`/`node`. Mọi `.tsx` chỉ được rà bằng mắt. Chạy `npm run build` để xác nhận.

### 7.7 Lock trên model dùng chung

Chế độ dùng chung tuần tự hóa inference qua `_MODEL_LOCK`. Trên máy nhiều GPU, lock có thể thành nút cổ chai — khi đó đặt `SHARE_YOLO_WEIGHTS=false`.

---

## 8. Thứ tự triển khai đề xuất

| Bước | Việc | Rủi ro |
|---|---|---|
| 1 | Chạy migration `6d8e0a2b4c57` | Rất thấp — chỉ thêm bảng |
| 2 | Bật `ENABLE_TELEMETRY` → dashboard có dữ liệu | Thấp |
| 3 | Bật `DEBUG_AI` + `DEBUG_AI_SAMPLE_RATE=0.05` | Thấp |
| 4 | Bật thu thập review, vận hành **2–4 tuần** | Không |
| 5 | Duyệt nhãn, `build_classifier_dataset.py` | Không |
| 6 | Train classifier, **đo A/B**, rồi mới bật | Trung bình |
| 7 | Bật OCR **chỉ khi** classifier còn nhầm hàng nhái | Cao (nặng) |
| 8 | Embedding sau khi có gallery tham chiếu | Trung bình |

---

## 9. Đề xuất phiên bản kế tiếp

1. **pgvector** cho `ai_embeddings` + index HNSW — hiện tìm kiếm là vét cạn, đủ ở vài nghìn vector, hỏng ở hàng trăm nghìn.
2. **Partition theo ngày** cho `ai_frames`/`ai_logs` — index đã sắp sẵn cho việc này; dọn dẹp thành `DROP PARTITION` thay vì `DELETE` khoá bảng.
3. **Sửa `trainer.py`**: bỏ bbox phủ toàn ảnh, gán nhãn định vị thật.
4. **Tách OCR thành service riêng** nếu dùng rộng.
5. **Job dọn dẹp theo lịch** theo bảng lưu giữ ở mục 4.
6. **Đo benchmark thật** khi có tập test có nhãn.
