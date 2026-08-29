# Huấn luyện YOLOv8 nhận diện sản phẩm cho VisionMart

Tài liệu này hướng dẫn tạo model nhận diện **chính xác từng SKU** (thay vì class chung của COCO như `bottle`, `book`). Dành cho POC 2-3 sản phẩm; quy trình tương tự khi scale lên 50-500 SKU.

## 0. Chuẩn bị

Chọn 2-3 SKU thật trong bảng `products` để train. Ví dụ:

| SKU        | Tên                 | Class YOLO (tên nội bộ) |
| ---------- | ------------------- | ----------------------- |
| DRK-001    | Coca-Cola 330ml     | `drk_001_coke`          |
| DRK-002    | Pepsi 330ml         | `drk_002_pepsi`         |
| SNK-001    | Bánh Oreo 137g      | `snk_001_oreo`          |

**Quy tắc đặt tên class YOLO:** viết thường, chữ số + gạch dưới, không dấu. Đặt sao cho dễ map ngược về SKU trong `class_to_sku.json`.

## 1. Chụp ảnh dataset

Với mỗi SKU, chụp **40-60 ảnh** bằng điện thoại:

- 10 ảnh chụp thẳng, 4 góc bàn khác nhau
- 10 ảnh nghiêng 30-60°
- 10 ảnh khoảng cách xa (giả lập camera trần)
- 5 ảnh cầm tay (có bàn tay che một phần)
- 5 ảnh dưới ánh sáng khác (đèn vàng, đèn trắng, ánh sáng tự nhiên)
- 5 ảnh có nhiều SKU trong cùng khung hình (rất quan trọng)

**Tổng:** 120-180 ảnh cho 3 SKU. Nhiều hơn thì tốt hơn nhưng đây là mức tối thiểu.

Copy tất cả ảnh vào 1 folder trên máy bạn (chưa cần chia).

## 2. Gán nhãn — dùng Roboflow (nhanh nhất, free)

1. Đăng ký [https://app.roboflow.com](https://app.roboflow.com) (miễn phí đến 10k ảnh).
2. Tạo Workspace → **Create New Project**:
   - Project type: **Object Detection**
   - License: CC BY 4.0 (hoặc private nếu muốn)
   - Annotation Group: `visionmart-products`
3. **Upload** tất cả ảnh vào project.
4. **Annotate**: vẽ bounding box quanh mỗi sản phẩm trong ảnh, gán class tên đúng như bảng ở mục 0 (`drk_001_coke`, `drk_002_pepsi`, `snk_001_oreo`).
   - Roboflow có tính năng **Smart Polygon** và **Auto Label** giúp nhanh gấp 3-5 lần.
5. Sau khi gán xong 100%, vào tab **Generate**:
   - Preprocessing: **Auto-Orient** ✓, **Resize 640×640** ✓
   - Augmentation: bật **Flip Horizontal**, **Brightness ±25%**, **Blur** — không nên bật quá 3 loại.
   - Split: 80% train / 15% valid / 5% test.
6. **Export dataset** → định dạng **YOLOv8** → chọn **Download zip to computer**.
7. Giải nén, bạn có cấu trúc:
   ```
   vm_v1/
     data.yaml
     train/images/*.jpg
     train/labels/*.txt
     valid/images/*.jpg
     valid/labels/*.txt
     test/images/*.jpg
     test/labels/*.txt
   ```

## 3. Copy dataset vào server / máy train

```bash
# Trên máy có GPU (khuyên) hoặc VPS (chậm hơn):
mkdir -p /var/www/visionmart/ai-engine/training/datasets
scp -r vm_v1 root@VPS_IP:/var/www/visionmart/ai-engine/training/datasets/
```

Kiểm tra `data.yaml` bên trong có nội dung giống:
```yaml
train: ../train/images
val: ../valid/images
test: ../test/images
nc: 3
names: ['drk_001_coke', 'drk_002_pepsi', 'snk_001_oreo']
```

Nếu path bị Roboflow ghi tương đối lạ, sửa lại thành đường dẫn tuyệt đối trong container:
```yaml
path: /app/training/datasets/vm_v1
train: train/images
val: valid/images
test: test/images
```

## 4. Train

### Cách A — trên VPS trong container ai-engine (CPU, chậm nhưng khỏi setup)

```bash
cd /var/www/visionmart
docker compose exec ai-engine python training/train.py \
  --data /app/training/datasets/vm_v1/data.yaml \
  --epochs 100 --imgsz 640 --batch 8 --device cpu \
  --name vm_v1 \
  --publish-to /models
```

Thời gian ước tính (VPS CPU, 3 class, 120 ảnh, 100 epochs): **3-5 giờ**. Có thể chạy overnight.

Để chạy nền không lo mất session:
```bash
docker compose exec -d ai-engine python training/train.py --data ...
# hoặc dùng screen/tmux
```

### Cách B — trên máy local có GPU (khuyên, nhanh)

```bash
python -m venv .venv-yolo
source .venv-yolo/bin/activate   # Linux/macOS
# .venv-yolo\Scripts\activate    # Windows

pip install ultralytics==8.3.30 lapx==0.9.4

python ai-engine/training/train.py \
  --data ai-engine/training/datasets/vm_v1/data.yaml \
  --epochs 100 --imgsz 640 --batch 16 --device 0 \
  --name vm_v1 \
  --publish-to ./ai-engine/models_out
```

GPU RTX 3060: **~15-25 phút**. Weight ra `ai-engine/models_out/vm_v1.pt`.

## 5. Kiểm tra chất lượng model

```bash
# Trong container:
docker compose exec ai-engine python training/validate.py \
  --model /models/vm_v1.pt \
  --source /app/training/datasets/vm_v1/test/images \
  --conf 0.3
```

Xem mAP50-95 trong output — POC nên đạt **> 0.6**. Nếu < 0.4 → chụp thêm ảnh (đặc biệt ảnh khó: nghiêng, che khuất, ánh sáng yếu) và train lại.

## 6. Deploy weight vào ai-engine

```bash
# Đảm bảo /models đã mount vào container (docker-compose.yml đã có sẵn).
ls -la /var/lib/visionmart/models/       # hoặc đường dẫn host mount vào /models
# Kỳ vọng thấy vm_v1.pt

# Set env
echo "YOLO_MODEL=/models/vm_v1.pt" >> /var/www/visionmart/.env

# Cập nhật class_to_sku.json — bây giờ class name = tên nội bộ, map thẳng về SKU
cat > /var/www/visionmart/ai-engine/config/class_to_sku.json <<'EOF'
{
  "a85786d1-da00-4809-81d4-111f2ebeb3ec": {
    "7d702b7a-0544-48e4-849f-7aefcdfbc98f": {
      "drk_001_coke":  "DRK-001",
      "drk_002_pepsi": "DRK-002",
      "snk_001_oreo":  "SNK-001"
    }
  }
}
EOF

docker compose up -d ai-engine
```

## 7. Test end-to-end

Vào `/cameras` → camera có `is_checkout_zone=true` → Phân tích → upload ảnh có sản phẩm thật của bạn.

Panel Cart pipeline phải hiển thị:
- `class_name` của detection giờ là `drk_001_coke`, `snk_001_oreo`... (không còn là `bottle`, `book`)
- `Products (mapped SKU): 1+`
- `emitted_events`: `product_picked_up` với `product_sku: "DRK-001"` (giá trị thật) và `checkout_initiated` với `order_id`
- `/live-cart` và `/orders` có đơn mới

## 8. Thêm SKU mới sau này

Không cần train lại từ đầu:
1. Chụp 40-60 ảnh SKU mới, gán class mới vào cùng Roboflow project.
2. Regenerate dataset (Roboflow → Generate → new version).
3. Chạy `train.py` với `--model /models/vm_v1.pt` (kế thừa weight cũ), `--name vm_v2`, `--epochs 50`.
4. Copy `vm_v2.pt` → set `YOLO_MODEL=/models/vm_v2.pt` → cập nhật mapping → restart ai-engine.

## Ghi chú

- Nếu VPS CPU quá chậm, cân nhắc train local rồi `scp` weight lên. Model YOLOv8n chỉ ~6MB.
- Không được commit dataset (ảnh + label) vào git — dung lượng lớn. Đã có sẵn ở `ai-engine/training/datasets/` trong `.gitignore` chưa? Kiểm tra và bổ sung nếu chưa.
- Nhớ giữ backup của `runs/` folder — chứa metrics và curve để phân tích khi model tụt chất lượng.
