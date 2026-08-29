# HƯỚNG DẪN KHỞI CHẠY HỆ THỐNG VISIONMART

Tài liệu này hướng dẫn bạn cách tự chạy hệ thống Web (qua Docker), cách cấu hình để Docker không tự động tắt, và cách chạy ứng dụng quét sản phẩm (Python Checker) độc lập.

---

## 1. TẠI SAO DOCKER CỨ TỰ TẮT? (CÁCH KHẮC PHỤC)

Mặc định, Docker Desktop trên Windows bật tính năng tiết kiệm điện năng hoặc tự động tạm dừng (Auto-pause/Idle timeout) khi không phát hiện yêu cầu API nào trong 5 phút. Để tắt tính năng này:

1. Mở giao diện **Docker Desktop** trên màn hình.
2. Nhấp vào biểu tượng **Răng cưa (Settings)** ở góc trên bên phải.
3. Chọn tab **General** (Chung).
4. Tìm dòng: **"Save power by pausing the Docker engine when idle"** (hoặc **Auto-pause**) và **BỎ CHỌN** (Uncheck).
5. Nhấp vào nút **Apply & restart** ở góc dưới bên phải để lưu lại.

---

## 2. CÁCH CHẠY HỆ THỐNG WEB (DOCKER COMPOSE)

Mỗi khi muốn chạy hoặc khởi động lại hệ thống Web, bạn làm như sau:

### Bước 1: Khởi động Docker Desktop
* Mở **Docker Desktop** từ Start Menu của Windows và đợi cho đến khi biểu tượng góc dưới bên trái chuyển sang màu xanh lá cây (Engine Running).

### Bước 2: Chạy lệnh khởi động
* Mở **PowerShell** hoặc **Command Prompt** (CMD).
* Di chuyển vào thư mục dự án (hoặc mở terminal trực tiếp tại thư mục dự án):
  ```powershell
  cd "c:\Users\banhtieu\Downloads\VisionMart-3\VisionMart-3"
  ```
* Chạy lệnh sau để khởi động toàn bộ các dịch vụ dưới nền:
  ```bash
  docker compose up -d
  ```

### Bước 3: Truy cập Web
* Mở trình duyệt (Chrome/Edge) và truy cập: **`http://localhost:3000`**
* **Thông tin đăng nhập mặc định:**
  * **Tài khoản (Email):** `admin@visionmart.local`
  * **Mật khẩu (Password):** `ChangeMe!2026`

### Bước 4: Tắt hệ thống (Khi không dùng nữa)
* Tại thư mục dự án trên terminal, chạy lệnh:
  ```bash
  docker compose down
  ```

---

## 3. CÁCH CHẠY TOOL CHECKER PYTHON GUI RIÊNG

Nếu bạn muốn chạy tool kiểm tra sản phẩm offline bằng Python mà không cần mở Web:

1. Truy cập vào thư mục: [checker](file:///c:/Users/banhtieu/Downloads/VisionMart-3/VisionMart-3/checker)
2. Nhấp đúp chuột vào file **`run.bat`** (hoặc chạy lệnh `run.bat` từ terminal trong thư mục `checker`).
3. File này sẽ tự động kiểm tra, cài đặt các thư viện cần thiết (OpenCV, Pillow, Ultralytics, ONNX Runtime) và khởi chạy giao diện GUI Tkinter.
4. **Cách dùng trên GUI:**
   * Chọn `[1] Camera` hoặc `[3] Video` để nạp nguồn hình ảnh.
   * Dùng chuột nhấn và kéo trực tiếp trên khung video để vẽ vùng quét (hộp màu đỏ nét đứt).
   * Khi thả chuột, vùng quét sẽ khóa lại (nét liền màu đỏ). Chỉ những sản phẩm nằm trong vùng đỏ này mới được nhận diện và hiển thị trong danh sách quét.
   * Nhấn nút **"Xóa vùng quét"** để vẽ lại vùng mới.
