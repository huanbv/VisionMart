"""
╔══════════════════════════════════════════════════════════════════╗
║          VISIONMART – Standalone Desktop GUI Application         ║
║     Giao diện cửa sổ Windows (Tkinter) – Không dùng Web/HTML    ║
╚══════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
YOLO_MODEL = MODELS_DIR / "yolov8n.pt"
ONNX_MODEL = MODELS_DIR / "sku_classifier.onnx"
LABELS_FILE = MODELS_DIR / "sku_labels.json"

# ─── SKU Info mapping ─────────────────────────────────────────────────────────
SKU_INFO: dict[str, dict] = {
    "DRK-001": {"name": "Sting Dau Do",    "price": 12000, "color": (255, 0, 0)},     # Red in RGB
    "DRK-002": {"name": "7Up Chanh",       "price": 11500, "color": (0, 200, 0)},     # Green in RGB
    "DRK-003": {"name": "Hao Hao Chua Cay", "price": 6000,  "color": (255, 165, 0)},   # Orange in RGB
    "SNK-001": {"name": "Snack Oishi",      "price": 5000,  "color": (255, 0, 255)},   # Magenta in RGB
}
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

def resize_aspect(pil_img, max_w, max_h):
    w, h = pil_img.size
    ratio = min(max_w / w, max_h / h)
    new_w = max(1, int(w * ratio))
    new_h = max(1, int(h * ratio))
    return pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

class VisionMartCheckerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("VisionMart - Standalone Desktop AI Checker")
        self.root.geometry("1200x750")
        self.root.configure(bg="#f0f2f5")

        # Session states
        self.cart = {} # sku -> {"name": str, "price": int, "quantity": int}
        self.cap = None
        self.running_cam = False

        # ROI selector state
        self.roi_start = None
        self.roi_drag_end = None
        self.roi_rect = None  # (x1_pct, y1_pct, x2_pct, y2_pct)

        # Load models
        self.status_bar_text = tk.StringVar(value="Đang nạp AI Models...")
        self.yolo = None
        self.ort_session = None
        self.sku_labels = []

        self.setup_ui()
        self.root.after(100, self.load_models)

    def load_models(self):
        # Load YOLO
        if not YOLO_MODEL.exists():
            self.status_bar_text.set("LỖI: Không tìm thấy models/yolov8n.pt")
            messagebox.showerror("Lỗi Model", f"Không tìm thấy YOLO model tại: {YOLO_MODEL}")
            return
        
        try:
            from ultralytics import YOLO
            self.yolo = YOLO(str(YOLO_MODEL))
        except Exception as e:
            self.status_bar_text.set(f"LỖI: Không nạp được YOLO: {e}")
            return

        # Load ONNX Classifier
        if ONNX_MODEL.exists() and LABELS_FILE.exists():
            try:
                import onnxruntime as ort
                self.ort_session = ort.InferenceSession(str(ONNX_MODEL), providers=["CPUExecutionProvider"])
                with open(LABELS_FILE, encoding="utf-8") as f:
                    self.sku_labels = json.load(f)
                if isinstance(self.sku_labels, dict):
                    self.sku_labels = self.sku_labels.get("labels", [])
                self.status_bar_text.set("AI Models đã sẵn sàng! Chào mừng bạn đến với VisionMart.")
            except Exception as e:
                self.status_bar_text.set(f"Cảnh báo: Lỗi nạp SKU Classifier ({e}) – Fallback YOLO.")
        else:
            self.status_bar_text.set("Chỉ nạp YOLO (Thiếu ONNX/Labels).")

    def setup_ui(self):
        # Style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f0f2f5")
        style.configure("TLabel", background="#f0f2f5", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), background="#f0f2f5")
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=6)
        style.configure("Danger.TButton", font=("Segoe UI", 10, "bold"), background="#ff4d4f", foreground="white")
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background="#1890ff", foreground="white")

        # Top Title Bar
        title_frame = tk.Frame(self.root, bg="#1f4068", height=60)
        title_frame.pack(fill=tk.X)
        title_label = tk.Label(title_frame, text="VISIONMART – STANDALONE DESKTOP AI CHECKER", 
                               font=("Segoe UI", 16, "bold"), fg="white", bg="#1f4068")
        title_label.pack(pady=15)

        # Main Split Frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # Left Column: Camera / Image view (fixed size to prevent expansion)
        left_col = ttk.Frame(main_frame)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))

        self.video_container = ttk.Frame(left_col, width=640, height=480)
        self.video_container.pack_propagate(False) # Lock size!
        self.video_container.pack(fill=tk.BOTH, expand=False)

        self.view_canvas = tk.Canvas(self.video_container, bg="black", highlightthickness=0)
        self.view_canvas.pack(fill=tk.BOTH, expand=True)
        self.view_canvas.bind("<Button-1>", self.on_roi_start)
        self.view_canvas.bind("<B1-Motion>", self.on_roi_drag)
        self.view_canvas.bind("<ButtonRelease-1>", self.on_roi_end)

        # Control Row under video
        control_row = ttk.Frame(left_col)
        control_row.pack(fill=tk.X, pady=(10, 0))

        ttk.Label(control_row, text="Chế độ:").pack(side=tk.LEFT, padx=5)
        self.mode_var = tk.StringVar(value="Camera Live")
        self.mode_combo = ttk.Combobox(control_row, textvariable=self.mode_var, values=["Camera Live", "File Ảnh", "File Video"], state="readonly", width=12)
        self.mode_combo.pack(side=tk.LEFT, padx=5)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_mode_change)

        self.btn_action = ttk.Button(control_row, text="Bật Camera", command=self.toggle_camera, style="Primary.TButton")
        self.btn_action.pack(side=tk.LEFT, padx=5)

        self.btn_select_file = ttk.Button(control_row, text="Chọn File", command=self.select_file)
        self.btn_select_file.pack(side=tk.LEFT, padx=5)

        self.btn_clear_roi = ttk.Button(control_row, text="Xóa vùng quét", command=self.clear_roi)
        self.btn_clear_roi.pack(side=tk.LEFT, padx=5)

        ttk.Label(control_row, text="Ngưỡng AI:").pack(side=tk.LEFT, padx=15)
        self.conf_slider = ttk.Scale(control_row, from_=0.3, to=1.0, value=0.55, orient=tk.HORIZONTAL, length=120)
        self.conf_slider.pack(side=tk.LEFT, padx=5)

        # Right Column: Cart Table & Event Logs
        right_col = ttk.Frame(main_frame, width=450)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        right_col.pack_propagate(False)

        # Cart Table
        cart_frame = ttk.LabelFrame(right_col, text=" Giỏ hàng AI (Nhận diện tự động) ")
        cart_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Treeview Scrollbar
        scroll = ttk.Scrollbar(cart_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree = ttk.Treeview(cart_frame, columns=("name", "qty", "price", "total"), show="headings", yscrollcommand=scroll.set)
        self.tree.heading("name", text="Sản phẩm")
        self.tree.heading("qty", text="SL")
        self.tree.heading("price", text="Đơn giá")
        self.tree.heading("total", text="Thành tiền")

        self.tree.column("name", width=180, anchor=tk.W)
        self.tree.column("qty", width=40, anchor=tk.CENTER)
        self.tree.column("price", width=80, anchor=tk.E)
        self.tree.column("total", width=90, anchor=tk.E)
        self.tree.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=self.tree.yview)

        # Total Amount Box
        self.total_label_var = tk.StringVar(value="TỔNG: 0 VND")
        total_lbl = tk.Label(right_col, textvariable=self.total_label_var, font=("Segoe UI", 16, "bold"), fg="#1f4068", anchor=tk.E)
        total_lbl.pack(fill=tk.X, pady=5)

        # Action button row
        btn_row = ttk.Frame(right_col)
        btn_row.pack(fill=tk.X, pady=5)
        ttk.Button(btn_row, text="Xóa/Reset Giỏ Hàng", command=self.reset_cart).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(btn_row, text="Chụp & Quét AI", command=self.manual_scan).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(5, 0))

        # Event Log Window
        log_frame = ttk.LabelFrame(right_col, text=" Nhật ký sự kiện AI ")
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        self.log_text = tk.Text(log_frame, wrap=tk.WORD, state=tk.DISABLED, font=("Consolas", 9), bg="#fafafa")
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Status Bar
        status_bar = tk.Label(self.root, textvariable=self.status_bar_text, bd=1, relief=tk.SUNKEN, anchor=tk.W, font=("Segoe UI", 9))
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def log(self, msg: str):
        t_str = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{t_str}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def on_roi_start(self, event):
        # Start ROI selection drag
        self.roi_start = (event.x, event.y)
        self.roi_drag_end = None

    def on_roi_drag(self, event):
        if not self.roi_start:
            return
        self.roi_drag_end = (event.x, event.y)

    def on_roi_end(self, event):
        if not self.roi_start or not self.roi_drag_end:
            return
        x1, y1 = self.roi_start
        x2, y2 = self.roi_drag_end
        
        # Calculate percentage boundary of the container (640x480)
        vw, vh = self.video_container.winfo_width(), self.video_container.winfo_height()
        if vw <= 10 or vh <= 10:
            vw, vh = 640, 480
        
        px1 = min(x1, x2) / vw
        py1 = min(y1, y2) / vh
        px2 = max(x1, x2) / vw
        py2 = max(y1, y2) / vh
        
        self.roi_rect = (px1, py1, px2, py2)
        self.log(f"Đã thiết lập vùng quét (ROI): {px1*100:.0f}%-{py1*100:.0f}% đến {px2*100:.0f}%-{py2*100:.0f}%")
        self.roi_start = None
        self.roi_drag_end = None

    def clear_roi(self):
        self.roi_rect = None
        self.log("Đã xóa vùng quét (ROI) — Quét toàn bộ khung hình")

    def on_mode_change(self, event=None):
        self.stop_camera()
        mode = self.mode_var.get()
        if mode == "Camera Live":
            self.btn_action.config(text="Bật Camera", state=tk.NORMAL)
            self.btn_select_file.config(state=tk.DISABLED)
        else:
            self.btn_action.config(text="Chạy File", state=tk.DISABLED)
            self.btn_select_file.config(state=tk.NORMAL)

    def select_file(self):
        mode = self.mode_var.get()
        if mode == "File Ảnh":
            path = filedialog.askopenfilename(filetypes=[("Image Files", "*.jpg *.jpeg *.png *.bmp")])
            if path:
                self.process_static_image(path)
        elif mode == "File Video":
            path = filedialog.askopenfilename(filetypes=[("Video Files", "*.mp4 *.avi *.mov *.mkv")])
            if path:
                self.process_video_file(path)

    # ─── Inference Logic ─────────────────────────────────────────────────────────
    def _softmax(self, x):
        e = np.exp(x - np.max(x))
        return e / e.sum()

    def preprocess_crop(self, crop, size=224):
        h, w = crop.shape[:2]
        interp = cv2.INTER_AREA if (h > size or w > size) else cv2.INTER_LINEAR
        resized = cv2.resize(crop, (size, size), interpolation=interp)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        normalised = (rgb - IMAGENET_MEAN) / IMAGENET_STD
        return np.transpose(normalised, (2, 0, 1))[np.newaxis, ...].astype(np.float32)

    def classify_crop(self, crop):
        if self.ort_session is None:
            return None, 0.0
        try:
            batch = self.preprocess_crop(crop)
            inp_name = self.ort_session.get_inputs()[0].name
            logits = self.ort_session.run(None, {inp_name: batch})[0][0]
            probs = self._softmax(logits.astype(np.float32))
            top = int(np.argmax(probs))
            return self.sku_labels[top], float(probs[top])
        except:
            return None, 0.0

    def run_detection(self, frame):
        if self.yolo is None:
            return []
        h, w = frame.shape[:2]
        out = []
        min_conf = self.conf_slider.get()

        res = self.yolo(frame, verbose=False, conf=0.3)[0]
        for box in res.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue

            # ROI filter check (center point of product must be inside drawn ROI rect)
            if self.roi_rect:
                cx_pct = ((x1 + x2) / 2) / w
                cy_pct = ((y1 + y2) / 2) / h
                rx1, ry1, rx2, ry2 = self.roi_rect
                if not (rx1 <= cx_pct <= rx2 and ry1 <= cy_pct <= ry2):
                    continue

            crop = frame[y1:y2, x1:x2]
            yolo_conf = float(box.conf[0])
            yolo_name = res.names.get(int(box.cls[0]), "object")

            sku, conf = self.classify_crop(crop)
            if sku is None:
                sku = yolo_name.upper().replace(" ", "-")
                conf = yolo_conf

            if conf < min_conf:
                continue

            info = SKU_INFO.get(sku, {"name": sku, "price": 0, "color": (180, 180, 180)})
            out.append({
                "sku": sku,
                "name": info["name"],
                "price": info["price"],
                "confidence": conf,
                "bbox": (x1, y1, x2, y2),
                "color": info["color"]
            })
        return out

    def update_cart(self, detections):
        for d in detections:
            sku = d["sku"]
            if sku not in self.cart:
                self.cart[sku] = {
                    "name": d["name"],
                    "price": d["price"],
                    "quantity": 1
                }
                self.log(f"AI Scanned: {d['name']} ({sku})")
        self.render_cart()

    def render_cart(self):
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        total_amount = 0
        for sku, item in self.cart.items():
            subtotal = item["price"] * item["quantity"]
            total_amount += subtotal
            self.tree.insert("", tk.END, values=(item["name"], item["quantity"], f"{item['price']:,}d", f"{subtotal:,}d"))

        self.total_label_var.set(f"TỔNG: {total_amount:,} VND")

    def reset_cart(self):
        self.cart = {}
        self.render_cart()
        self.log("Reset / Clear giỏ hàng")

    def manual_scan(self):
        self.log("Yêu cầu chụp quét AI thủ công")
        # Snapshot current frames in the background
        if self.running_cam and self.cap:
            ret, frame = self.cap.read()
            if ret:
                dets = self.run_detection(frame)
                self.update_cart(dets)
                self.log(f"Phân tích thủ công: Phát hiện {len(dets)} sản phẩm")

    # ─── Camera / Stream Controllers ──────────────────────────────────────────────
    def toggle_camera(self):
        if self.running_cam:
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            self.log("LỖI: Không mở được camera")
            return
        self.running_cam = True
        self.btn_action.config(text="Tắt Camera")
        self.log("Bật Live Camera Stream")
        self.update_camera_loop()

    def stop_camera(self):
        self.running_cam = False
        if self.cap:
            self.cap.release()
            self.cap = None
        self.btn_action.config(text="Bật Camera")
        self.view_canvas.delete("all")
        self.view_canvas.create_text(320, 240, text="CAMERA VIEW", fill="white", font=("Segoe UI", 14))
        self.log("Tắt Live Camera Stream")

    def update_camera_loop(self):
        if not self.running_cam or not self.cap:
            return

        ret, frame = self.cap.read()
        if ret:
            # Detect
            dets = self.run_detection(frame)
            self.update_cart(dets)

            # Draw overlays (with active ROI rect)
            annotated = draw_overlays(frame, dets, self.roi_rect)

            # Convert to PhotoImage for Tkinter
            cv_img = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(cv_img)
            # Resize fit video_container keeping aspect ratio
            vw, vh = self.video_container.winfo_width(), self.video_container.winfo_height()
            if vw <= 10 or vh <= 10:
                vw, vh = 640, 480
            pil_img = resize_aspect(pil_img, vw, vh)
            
            photo = ImageTk.PhotoImage(image=pil_img)
            
            # Render to Canvas
            self.view_canvas.delete("all")
            self.view_canvas.create_image(vw // 2, vh // 2, image=photo, anchor=tk.CENTER)
            self.view_canvas.image = photo  # Keep reference
            
            # If dragging, draw temporary dash box
            if self.roi_start and self.roi_drag_end:
                self.view_canvas.create_rectangle(self.roi_start[0], self.roi_start[1],
                                                  self.roi_drag_end[0], self.roi_drag_end[1],
                                                  outline="red", width=2, dash=(4, 4))

        self.root.after(30, self.update_camera_loop)

    # ─── File Processors ──────────────────────────────────────────────────────────
    def process_static_image(self, path):
        frame = cv2.imread(path)
        if frame is None:
            self.log(f"LỖI: Không đọc được ảnh từ {path}")
            return
        
        self.log(f"Đang phân tích file ảnh: {os.path.basename(path)}")
        t0 = time.perf_counter()
        dets = self.run_detection(frame)
        self.update_cart(dets)
        ms = (time.perf_counter() - t0) * 1000
        self.log(f"Đã xử lý xong ảnh ({ms:.0f}ms). Phát hiện {len(dets)} sản phẩm")

        # Draw & display image
        annotated = draw_overlays(frame, dets, self.roi_rect)
        cv_img = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(cv_img)
        vw, vh = self.video_container.winfo_width(), self.video_container.winfo_height()
        if vw <= 10 or vh <= 10:
            vw, vh = 640, 480
        pil_img = resize_aspect(pil_img, vw, vh)
        
        photo = ImageTk.PhotoImage(image=pil_img)
        
        self.view_canvas.delete("all")
        self.view_canvas.create_image(vw // 2, vh // 2, image=photo, anchor=tk.CENTER)
        self.view_canvas.image = photo

    def process_video_file(self, path):
        self.log(f"Đang phân tích file video: {os.path.basename(path)}")
        cap = cv2.VideoCapture(path)
        
        frame_idx = 0
        last_dets = []
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1
            if frame_idx % 8 == 0:
                last_dets = self.run_detection(frame)
                self.update_cart(last_dets)

            # Draw & Display
            annotated = draw_overlays(frame, last_dets, self.roi_rect)
            cv_img = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(cv_img)
            vw, vh = self.video_container.winfo_width(), self.video_container.winfo_height()
            if vw <= 10 or vh <= 10:
                vw, vh = 640, 480
            pil_img = resize_aspect(pil_img, vw, vh)
            
            photo = ImageTk.PhotoImage(image=pil_img)
            
            self.view_canvas.delete("all")
            self.view_canvas.create_image(vw // 2, vh // 2, image=photo, anchor=tk.CENTER)
            self.view_canvas.image = photo
            self.root.update()
            time.sleep(0.01)
        
        cap.release()
        self.log("Hoàn thành phân tích file video.")

def draw_overlays(frame, detections, roi_rect=None):
    vis = frame.copy()
    h, w = frame.shape[:2]
    for d in detections:
        x1, y1, x2, y2 = d["bbox"]
        color = d["color"]
        # Convert RGB to BGR for OpenCV drawing
        color_bgr = (color[2], color[1], color[0])
        cv2.rectangle(vis, (x1, y1), (x2, y2), color_bgr, 2)
        lbl = f"{d['sku']} {d['confidence']*100:.0f}%"
        (tw, th), _ = cv2.getTextSize(lbl, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(vis, (x1, y1 - th - 8), (x1 + tw + 4, y1), color_bgr, -1)
        cv2.putText(vis, lbl, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        cv2.putText(vis, d["name"], (x1 + 2, y2 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color_bgr, 1)
    
    # Draw ROI rectangle in red if active
    if roi_rect:
        rx1 = int(roi_rect[0] * w)
        ry1 = int(roi_rect[1] * h)
        rx2 = int(roi_rect[2] * w)
        ry2 = int(roi_rect[3] * h)
        cv2.rectangle(vis, (rx1, ry1), (rx2, ry2), (0, 0, 255), 2) # Red bounding box
        cv2.putText(vis, "VUNG QUET ROI", (rx1 + 6, ry1 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    return vis

def main():
    root = tk.Tk()
    app = VisionMartCheckerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
