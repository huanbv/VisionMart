/**
 * Catalogue of algorithms + source snippets for the thesis lab page.
 * Keys match OpenCV trace `stage` and DEBUG_AI `step` names.
 */
export interface AlgorithmDef {
  key: string;
  algorithm: string;
  algorithmEn: string;
  citation: string;
  file: string;
  code: string;
}

export const ALGORITHMS: Record<string, AlgorithmDef> = {
  decode: {
    key: "decode",
    algorithm: "Giải mã ảnh (JPEG Huffman / PNG inflate)",
    algorithmEn: "cv2.imdecode — raster decode to BGR uint8",
    citation: "OpenCV imgcodecs; ISO/IEC 10918 (JPEG)",
    file: "ai-engine/app/vision/preprocessing/decode.py",
    code: `def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    buf = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Cannot decode image")
    return frame  # BGR, cùng convention YOLO/Ultralytics`,
  },
  roi: {
    key: "roi",
    algorithm: "Vùng quan tâm (ROI) — mặt nạ đa giác",
    algorithmEn: "Region of Interest — polygon mask (fillPoly + bitwise AND)",
    citation: "Gonzalez & Woods, Digital Image Processing, Ch.2 (spatial operations)",
    file: "ai-engine/app/vision/roi/zones.py",
    code: `def apply_roi(frame_bgr, zones):
    mask = np.zeros(frame_bgr.shape[:2], dtype=np.uint8)
    for zone in zones:
        polygon = zone.to_pixel_polygon(width, height)
        cv2.fillPoly(mask, [polygon], 255)
    return cv2.bitwise_and(frame_bgr, frame_bgr, mask=mask)`,
  },
  auto_gamma: {
    key: "auto_gamma",
    algorithm: "Hiệu chỉnh gamma tự động (biến đổi luỹ thừa)",
    algorithmEn: "Auto gamma — power-law transform s = c · r^γ, γ từ độ sáng trung bình",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Power-law (gamma) transformations",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def compute_auto_gamma(frame_bgr, target, min_g, max_g) -> float:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    # (mean/255)^(1/γ) = target/255  →  γ = log(mean/255) / log(target/255)
    gamma = np.log(mean / 255.0) / np.log(target / 255.0)
    return float(np.clip(gamma, min_g, max_g))

table = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in range(256)], np.uint8)
out = cv2.LUT(frame_bgr, table)`,
  },
  gamma: {
    key: "gamma",
    algorithm: "Hiệu chỉnh gamma cố định (power-law)",
    algorithmEn: "Gamma correction — s = c · r^γ",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Intensity transformations",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_gamma(frame_bgr, gamma: float):
    inv = 1.0 / max(0.01, gamma)
    table = np.array([((i / 255.0) ** inv) * 255 for i in range(256)], np.uint8)
    return cv2.LUT(frame_bgr, table)`,
  },
  brightness: {
    key: "brightness",
    algorithm: "Dịch độ sáng tuyến tính",
    algorithmEn: "Linear intensity transform g = αf + β  (α=1, β=delta)",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Linear point operations",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_brightness(frame_bgr, delta: float):
    return cv2.convertScaleAbs(frame_bgr, alpha=1.0, beta=delta)`,
  },
  contrast: {
    key: "contrast",
    algorithm: "Giãn tương phản tuyến tính",
    algorithmEn: "Contrast stretching — g = αf  (β=0)",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Contrast stretching",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_contrast(frame_bgr, alpha: float):
    return cv2.convertScaleAbs(frame_bgr, alpha=alpha, beta=0.0)`,
  },
  clahe: {
    key: "clahe",
    algorithm: "CLAHE — cân bằng histogram thích nghi có giới hạn clip",
    algorithmEn: "CLAHE (Contrast Limited Adaptive Histogram Equalization)",
    citation:
      "Pizer et al., Adaptive Histogram Equalization (1987); Gonzalez & Woods, DIP Ch.3",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_clahe(frame_bgr, clip_limit, tile_grid_size):
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_grid_size,) * 2)
    l_eq = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)`,
  },
  hist_eq: {
    key: "hist_eq",
    algorithm: "Cân bằng histogram toàn cục",
    algorithmEn: "Global Histogram Equalization on L channel (CIE Lab)",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Histogram equalization",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_hist_eq(frame_bgr):
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l_eq = cv2.equalizeHist(l)
    return cv2.cvtColor(cv2.merge((l_eq, a, b)), cv2.COLOR_LAB2BGR)`,
  },
  gaussian_blur: {
    key: "gaussian_blur",
    algorithm: "Làm mượt Gaussian",
    algorithmEn: "Gaussian low-pass filter",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Smoothing spatial filters",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_gaussian_blur(frame_bgr, kernel_size):
    k = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
    return cv2.GaussianBlur(frame_bgr, (k, k), 0)`,
  },
  median_blur: {
    key: "median_blur",
    algorithm: "Bộ lọc trung vị",
    algorithmEn: "Median filter (impulse / salt-and-pepper denoising)",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Order-statistic filters",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_median_blur(frame_bgr, kernel_size):
    k = kernel_size if kernel_size % 2 == 1 else kernel_size + 1
    return cv2.medianBlur(frame_bgr, k)`,
  },
  adaptive_median: {
    key: "adaptive_median",
    algorithm: "Bộ lọc trung vị thích nghi",
    algorithmEn: "Adaptive Median Filter — window grows only on impulse pixels",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.5 — Adaptive median filter",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_adaptive_median(frame_bgr, max_kernel_size):
    out = frame_bgr.copy()
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    unresolved = (gray <= 2) | (gray >= 253)  # nghi ngờ xung
    k = 3
    while k <= max_kernel_size and unresolved.any():
        med = cv2.medianBlur(out, k)
        usable = unresolved & (2 < cv2.cvtColor(med, cv2.COLOR_BGR2GRAY)) & (...)
        out[usable] = med[usable]
        k += 2
    return out`,
  },
  bilateral: {
    key: "bilateral",
    algorithm: "Bộ lọc bilateral (giữ biên)",
    algorithmEn: "Bilateral filter — edge-preserving smoothing",
    citation: "Tomasi & Manduchi, Bilateral Filtering for Gray and Color Images, ICCV 1998",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_bilateral(frame_bgr, diameter, sigma_color, sigma_space):
    return cv2.bilateralFilter(
        frame_bgr, d=diameter, sigmaColor=sigma_color, sigmaSpace=sigma_space
    )`,
  },
  unsharp_mask: {
    key: "unsharp_mask",
    algorithm: "Unsharp masking / high-boost",
    algorithmEn: "Unsharp masking: g = f + amount · (f − Gσ * f)",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Unsharp masking and highboost (eq. 3.6-8)",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_unsharp_mask(frame_bgr, amount, radius, threshold=0):
    blurred = cv2.GaussianBlur(frame_bgr, (0, 0), sigmaX=radius)
    return cv2.addWeighted(frame_bgr, 1.0 + amount, blurred, -amount, 0.0)`,
  },
  final: {
    key: "final",
    algorithm: "Khung cuối đưa vào YOLO",
    algorithmEn: "Preprocessed BGR tensor — input to the detector",
    citation: "Ultralytics YOLOv8 nhận ndarray BGR (không chuyển RGB)",
    file: "ai-engine/app/vision/pipeline.py",
    code: `frame = decode_image_bytes(image_bytes)
if zones:
    frame = apply_roi(frame, zones)
if cfg.any_enhancement_enabled:
    frame = enhance_frame(frame, cfg)
# YOLO thấy đúng frame BGR này — không convert RGB`,
  },
  original: {
    key: "original",
    algorithm: "Ảnh gốc (trước tiền xử lý)",
    algorithmEn: "Raw decoded frame",
    citation: "OpenCV imgcodecs",
    file: "ai-engine/app/api/frame.py",
    code: `original = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
debug.add("original", original, bytes=len(content))`,
  },
  preprocess: {
    key: "preprocess",
    algorithm: "Chuỗi tiền xử lý OpenCV trước YOLO",
    algorithmEn: "Decode → ROI → enhancement → quality (Laplacian blur score)",
    citation: "Gonzalez & Woods Ch.3; Pech-Pacheco et al. — variance of Laplacian (blur)",
    file: "ai-engine/app/vision/pipeline.py",
    code: `def preprocess_for_detection(image_bytes, camera_key, cfg, roi_zones=None):
    frame = decode_image_bytes(image_bytes)
    if zones:
        frame = apply_roi(frame, zones)
    if cfg.any_enhancement_enabled:
        frame = enhance_frame(frame, cfg)  # gamma → CLAHE → blur → unsharp
    quality = analyze_quality(frame, cfg)  # Laplacian variance = độ nét
    return frame  # đầu vào YOLO`,
  },
  detection: {
    key: "detection",
    algorithm: "YOLOv8 + NMS + ByteTrack",
    algorithmEn:
      "YOLOv8 (CSPDarknet + PANet + decoupled head) · NMS IoU=0.50 · ByteTrack MOT",
    citation:
      "Redmon et al. YOLO (2016); Jocher et al. YOLOv8 (Ultralytics); Zhang et al. ByteTrack, ECCV 2022; Neubeck & Van Gool NMS",
    file: "ai-engine/app/services/person_tracker.py",
    code: `# Người: theo vết đa khung
pose_results = model_pose.track(
    source=img, persist=True, tracker="bytetrack.yaml", classes=[0],
)
# Sản phẩm (quét 1 ảnh): predict + NMS, không ByteTrack
results = model.predict(source=crop, conf=0.20, iou=0.50, max_det=30)
# NMS: bỏ box chồng IoU > 0.50, giữ confidence cao hơn`,
  },
  crop: {
    key: "crop",
    algorithm: "Cắt vùng đối tượng (bounding-box crop + padding)",
    algorithmEn: "Axis-aligned crop with relative padding, clamp to frame",
    citation: "Standard two-stage detector → classifier pipeline (R-CNN family)",
    file: "ai-engine/app/vision/crop/cropper.py",
    code: `def crop_detection(frame_bgr, x1, y1, x2, y2, padding=0.08, min_size=24):
    bw, bh = x2 - x1, y2 - y1
    cx1 = max(0, int(round(x1 - bw * padding)))
    cy1 = max(0, int(round(y1 - bh * padding)))
    cx2 = min(w, int(round(x2 + bw * padding)))
    cy2 = min(h, int(round(y2 + bh * padding)))
    if cx2 - cx1 < min_size or cy2 - cy1 < min_size:
        return None  # crop quá nhỏ → không phân loại
    return frame_bgr[cy1:cy2, cx1:cx2]`,
  },
  enhanced: {
    key: "enhanced",
    algorithm: "Chuẩn hoá crop cho CNN (resize + ImageNet)",
    algorithmEn: "Resize 224×224 (INTER_AREA) + ImageNet mean/std, NCHW",
    citation: "Krizhevsky et al. ImageNet; Howard et al. MobileNetV3 input recipe",
    file: "ai-engine/app/vision/classify/classifier.py",
    code: `_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD  = [0.229, 0.224, 0.225]

resized = cv2.resize(crop_bgr, (224, 224), interpolation=cv2.INTER_AREA)
rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
normalised = (rgb - mean) / std
batch = np.transpose(normalised, (2, 0, 1))[np.newaxis, ...]`,
  },
  classifier: {
    key: "classifier",
    algorithm: "MobileNetV3-Small + Softmax (phân loại SKU)",
    algorithmEn: "MobileNetV3-Small CNN → softmax P(SKU | crop)",
    citation:
      "Howard et al., Searching for MobileNetV3, ICCV 2019; Bridle, Softmax (1990)",
    file: "ai-engine/app/vision/classify/classifier.py",
    code: `def _softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()

logits = model.forward(batch)           # MobileNetV3-Small, ONNX/CPU
probs = _softmax(logits)
sku = labels[int(np.argmax(probs))]
confidence = float(probs.max())
margin = confidence - float(sorted(probs)[-2])  # khoảng cách top-1 vs top-2`,
  },
  ocr: {
    key: "ocr",
    algorithm: "OCR nhãn sản phẩm (EasyOCR / PaddleOCR) — fallback",
    algorithmEn: "Scene-text OCR when classifier margin is thin (look-alike SKUs)",
    citation: "Baek et al. CRAFT/EasyOCR; Shi et al. CRNN; Du et al. PP-OCR",
    file: "ai-engine/app/vision/ocr/reader.py",
    code: `# Chỉ chạy khi classifier conf thấp hoặc margin top-1/top-2 mỏng
# (cùng silhouette, khác dung tích 500ml vs 1.5L).
text, ocr_conf = ocr_engine.read(crop_bgr)
sku = find_sku_by_brand_volume(text)  # map chuỗi in trên nhãn → SKU`,
  },
  result: {
    key: "result",
    algorithm: "Kết hợp tin cậy YOLO × classifier × OCR (late fusion)",
    algorithmEn: "Weighted geometric-style fusion — weak stage cannot be averaged away",
    citation: "Late fusion / product-of-experts (Hinton, 2002) — sequential pipeline",
    file: "ai-engine/app/vision/matching/matcher.py",
    code: `# Thứ tự quyết định SKU:
# 1) Classifier nếu conf ≥ ngưỡng và margin đủ lớn
# 2) Fallback class_to_sku (ánh xạ lớp YOLO → SKU)
# 3) OCR khi hai bước trên không chắc
final = combine_confidence(yolo=yolo_p, classifier=cls_p, ocr=ocr_p)
# Tích có trọng số: mắt xích yếu (YOLO thấp) vẫn kéo điểm cuối xuống`,
  },
  video_capture: {
    key: "video_capture",
    algorithm: "Lấy khung video (temporal sampling)",
    algorithmEn: "Frame grab — HTMLVideoElement → Canvas → JPEG, pause during inference",
    citation: "Video temporal sampling; pause-on-infer to keep VPS without GPU responsive",
    file: "frontend/src/pages/VideoAnalysisPage.tsx",
    code: `video.pause()
canvas.width, canvas.height = video.videoWidth, video.videoHeight
ctx.drawImage(video, 0, 0)
blob = await canvas.toBlob("image/jpeg", 0.85)
# Tự chạy: tua currentTime += interval, chờ seeked, lặp lại`,
  },
  scan_session: {
    key: "scan_session",
    algorithm: "Phiên quét video độc lập (một giỏ / một lần test)",
    algorithmEn: "Isolated scan_session — do not merge with live till ByteTrack IDs",
    citation: "Session isolation; manual_scan emits product_scanned into one cart",
    file: "ai-engine/app/api/frame.py",
    code: `if scan_session:
    camera_key = f"{camera_key}::video::{scan_session}"
    manual_scan = True  # một khung → một giỏ, không checkout-p1 live
form.append("scan_session", token)
form.append("manual_scan", "true")
form.append("roi_zones", json.dumps(zones))  # vùng vẽ trên file video`,
  },
  cart_order: {
    key: "cart_order",
    algorithm: "Tạo giỏ / đơn từ sự kiện product_scanned",
    algorithmEn: "Event-driven cart — backend accepts SKU lines, POS checkout → order",
    citation: "Vision checkout pipeline: detect → identify → cart → order",
    file: "backend/app/modules/sales/application/",
    code: `# ai-engine emit product_scanned { sku, qty, photo_key, scan_session }
# backend CartService thêm dòng nếu SKU có trong catalog
# Checkout / QR → Order — cùng luồng POS, nguồn source=ai_vision`,
  },
};

export function lookupAlgorithm(stage: string): AlgorithmDef | undefined {
  return ALGORITHMS[stage];
}

export function formatAlgorithmMarkdown(
  stageKey: string,
  opts?: {
    title?: string;
    params?: Record<string, unknown>;
    elapsedMs?: number | null;
  },
): string {
  const def = lookupAlgorithm(stageKey);
  if (!def) return "";
  const lines = [
    `### ${opts?.title ?? def.algorithm}`,
    "",
    `- **Thuật toán:** ${def.algorithm}`,
    `- **Tên tiếng Anh:** ${def.algorithmEn}`,
    `- **Tài liệu:** ${def.citation}`,
    `- **File nguồn:** \`${def.file}\``,
  ];
  if (opts?.elapsedMs != null) {
    lines.push(`- **Thời gian bước:** ${opts.elapsedMs} ms`);
  }
  if (opts?.params && Object.keys(opts.params).length) {
    lines.push(`- **Tham số lần quét:** \`${JSON.stringify(opts.params)}\``);
  }
  lines.push("", "```python", def.code.trim(), "```", "");
  return lines.join("\n");
}

export function formatAppendixMarkdown(sections: Array<{
  stage: string;
  title: string;
  params?: Record<string, unknown>;
  elapsedMs?: number | null;
}>): string {
  const body = sections
    .map((s, i) =>
      formatAlgorithmMarkdown(s.stage, {
        title: `${i + 1}. ${s.title}`,
        params: s.params,
        elapsedMs: s.elapsedMs,
      }),
    )
    .filter(Boolean)
    .join("\n");
  return [
    "# Phụ lục — Thuật toán và mã nguồn pipeline nhận diện VisionMart",
    "",
    "Mỗi mục tương ứng một giai đoạn pipeline (thư viện video / ảnh → OpenCV → YOLOv8 → crop → MobileNetV3 → giỏ hàng).",
    "",
    body,
  ].join("\n");
}
