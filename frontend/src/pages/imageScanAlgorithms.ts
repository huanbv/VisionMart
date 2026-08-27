/**
 * Catalogue of algorithms + source snippets for the thesis lab page.
 * Keys match OpenCV trace `stage` and DEBUG_AI `step` names.
 *
 * `purpose` / `formulas` / `symbols` are written so a reader (or Word paste)
 * can see *why* each equation exists in VisionMart, not only the Python.
 */
export interface FormulaNote {
  /** Unicode math — pasteable into Word without LaTeX. */
  expr: string;
  purpose: string;
}

export interface SymbolNote {
  name: string;
  meaning: string;
}

export interface AlgorithmDef {
  key: string;
  algorithm: string;
  algorithmEn: string;
  citation: string;
  file: string;
  code: string;
  /** Vai trò bước này trong pipeline nhận diện siêu thị. */
  purpose: string;
  formulas: FormulaNote[];
  symbols: SymbolNote[];
}

/** Thuộc tính / tham số xuất hiện trên ảnh giai đoạn hoặc JSON lần chạy. */
export const PARAM_GLOSSARY: Record<string, string> = {
  gamma:
    "Số mũ biến đổi luỹ thừa. γ > 1 làm sáng vùng tối (camera quầy thiếu sáng); γ < 1 nén vùng cháy sáng.",
  delta:
    "Độ dịch độ sáng β (đơn vị mức xám 0–255). Dương = sáng hơn toàn khung trước khi YOLO.",
  alpha:
    "Hệ số nhân tương phản. α > 1 giãn histogram, giúp cạnh sản phẩm nổi hơn trên kệ tối.",
  clip_limit:
    "Ngưỡng cắt histogram CLAHE. Càng lớn càng tăng tương phản cục bộ; quá lớn làm nhiễu hạt.",
  tile_grid_size:
    "Cạnh ô (tile) CLAHE, đơn vị pixel-ô. Ô nhỏ thích nghi ánh sáng từng vùng kệ; ô lớn mượt hơn.",
  kernel_size:
    "Kích thước cửa sổ lọc (phải lẻ). Cửa sổ lớn xoá nhiễu mạnh hơn nhưng làm mờ cạnh box YOLO.",
  diameter:
    "Đường kính lân cận bộ lọc bilateral (pixel). 0 = OpenCV tự chọn từ σ_space.",
  sigma_color:
    "σ_r — độ rộng trên miền cường độ. Lớn: hoà pixel khác màu (dễ mờ biên nhãn).",
  sigma_space:
    "σ_s — độ rộng trên miền toạ độ. Lớn: lấy trung bình xa hơn, ảnh mượt hơn.",
  amount:
    "Hệ số high-boost k. k = 1 là unsharp chuẩn; k > 1 làm nét mạnh (dễ quầng sáng quanh chữ).",
  radius:
    "σ của Gaussian dùng làm mặt nạ mờ trong unsharp (bán kính làm nét).",
  threshold:
    "Ngưỡng |f − blur(f)|. Dưới ngưỡng không làm nét — tránh khuếch đại nhiễu cảm biến.",
  max_kernel:
    "Cửa sổ lớn nhất bộ lọc trung vị thích nghi. Giới hạn chi phí CPU trên VPS.",
  padding:
    "Phần đệm tương đối quanh bbox (0.08 = thêm 8% chiều rộng/cao) để crop không cắt mất cạnh chai.",
  min_size:
    "Cạnh crop tối thiểu (px). Nhỏ hơn thì bỏ, vì CNN 224×224 sẽ phóng hạt thành nhiễu.",
  conf: "Ngưỡng confidence YOLO. Box thấp hơn bị loại trước NMS.",
  iou: "Ngưỡng IoU của NMS. Hai box chồng hơn ngưỡng thì giữ box tin cậy hơn.",
  brightness:
    "Độ sáng trung bình kênh xám Ī ∈ [0, 255]. Theo dõi phơi sáng sau mỗi bước OpenCV.",
  contrast:
    "Độ lệch chuẩn kênh xám σ_I. Thấp = ảnh “phẳng”, YOLO khó tách vật khỏi nền.",
  blur_score:
    "Phương sai Laplacian Var(∇² I). Cao = nét; thấp hơn ngưỡng cấu hình → gắn cờ khung mờ.",
};

export function explainRuntimeParams(
  params?: Record<string, unknown>,
): Array<{ name: string; value: string; meaning: string }> {
  if (!params) return [];
  return Object.entries(params).map(([name, value]) => ({
    name,
    value: typeof value === "object" ? JSON.stringify(value) : String(value),
    meaning:
      PARAM_GLOSSARY[name] ??
      "Tham số cấu hình của bước này; đối chiếu bảng thuộc tính / ký hiệu phía trên.",
  }));
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
    purpose:
      "Đưa file JPEG/PNG từ camera hoặc upload thành ma trận điểm ảnh BGR mà mọi bước OpenCV và YOLOv8 dùng chung. Không giải mã được thì pipeline dừng — không bịa khung giả.",
    formulas: [
      {
        expr: "I : {1..H} × {1..W} → {0,…,255}³   (kênh B, G, R)",
        purpose:
          "Mỗi pixel là bộ ba mức xám 8-bit. Ultralytics nhận BGR, nên không chuyển RGB ở bước này để tránh lệch màu so với lúc train.",
      },
    ],
    symbols: [
      { name: "image_bytes", meaning: "Luồng nén JPEG/PNG từ camera, file upload hoặc khung video." },
      { name: "H, W", meaning: "Chiều cao và rộng khung (pixel) sau khi giải mã." },
      { name: "IMREAD_COLOR", meaning: "Ép 3 kênh BGR, bỏ kênh alpha nếu có." },
    ],
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
    purpose:
      "Chỉ giữ vùng quầy / băng chuyền đã vẽ. Pixel ngoài đa giác = 0 nên YOLO không “thấy” kệ sau lưng nhân viên hay người đi ngang — giảm box ảo, một giỏ đúng vùng thanh toán.",
    formulas: [
      {
        expr: "I'(x,y) = I(x,y) · M(x,y)/255 ,   M(x,y) ∈ {0, 255}",
        purpose:
          "AND với mặt nạ: trong đa giác giữ nguyên, ngoài đa giác đen. Tương đương cửa sổ không gian (spatial window) trong Gonzalez & Woods.",
      },
    ],
    symbols: [
      { name: "zones", meaning: "Danh sách đa giác chuẩn hoá (0–1) vẽ trên camera hoặc trên file video." },
      { name: "M", meaning: "Mặt nạ nhị phân cùng kích thước khung; 255 = điểm được xét." },
      { name: "polygon", meaning: "Toạ độ đỉnh đổi sang pixel theo W×H hiện tại." },
    ],
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
    purpose:
      "Một camera quầy thay đổi sáng–tối theo giờ. Thay vì cố định γ, hệ thống đo độ sáng trung bình khung rồi chọn γ để kéo Ī về mức đích — cùng cấu hình dùng được cả ngày lẫn đêm.",
    formulas: [
      {
        expr: "s = c · r^{1/γ} ,   r = i/255 ,   s ∈ [0, 255]\nγ = ln(Ī/255) / ln(I_target/255)",
        purpose:
          "Công thức power-law (Ch.3 DIP). Giải γ sao cho sau biến đổi, độ sáng trung bình tiến tới I_target. LUT 256 phần tử để không lặp pow từng pixel.",
      },
    ],
    symbols: [
      { name: "r", meaning: "Cường độ chuẩn hoá của một mức xám (0–1) trước biến đổi." },
      { name: "s", meaning: "Cường độ sau gamma, ghi lại bảng LUT rồi áp cho cả 3 kênh BGR." },
      { name: "γ (gamma)", meaning: PARAM_GLOSSARY.gamma },
      { name: "Ī (mean)", meaning: "Trung bình kênh xám hiện tại — đầu vào để ước γ." },
      { name: "I_target", meaning: "Độ sáng đích (cấu hình auto_gamma_target_brightness)." },
      { name: "min_g, max_g", meaning: "Kẹp γ, tránh khung gần đen/trắng yêu cầu số mũ cực đoan." },
    ],
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
    purpose:
      "Khi ánh sáng quầy ổn định, admin chọn một γ cố định. Cùng họ công thức với auto-gamma nhưng không đo Ī từng khung — rẻ CPU hơn trên VPS.",
    formulas: [
      {
        expr: "s = (i/255)^{1/γ} · 255",
        purpose:
          "γ > 1 giãn vùng tối (nhãn chai dưới đèn yếu); γ < 1 nén highlight. Áp LUT nên chi phí O(1) mỗi pixel.",
      },
    ],
    symbols: [
      { name: "γ (gamma)", meaning: PARAM_GLOSSARY.gamma },
      { name: "i", meaning: "Mức xám 0–255 đưa vào LUT." },
    ],
  },
  brightness: {
    key: "brightness",
    algorithm: "Dịch độ sáng tuyến tính",
    algorithmEn: "Linear intensity transform g = αf + β  (α=1, β=delta)",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Linear point operations",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_brightness(frame_bgr, delta: float):
    return cv2.convertScaleAbs(frame_bgr, alpha=1.0, beta=delta)`,
    purpose:
      "Cộng một hằng số lên mọi pixel khi camera hơi underexpose. Không đổi tương phản tương đối, chỉ tịnh tiến histogram — bước đơn giản trước CLAHE/YOLO.",
    formulas: [
      {
        expr: "g(x,y) = clip( f(x,y) + β , 0, 255 )",
        purpose:
          "Phép cộng điểm (point operation). clip tránh tràn 8-bit. β dương làm sáng kệ; âm làm tối nếu khung cháy sáng.",
      },
    ],
    symbols: [
      { name: "β (delta)", meaning: PARAM_GLOSSARY.delta },
      { name: "α", meaning: "Giữ = 1 nên không nhân tương phản ở bước này." },
    ],
  },
  contrast: {
    key: "contrast",
    algorithm: "Giãn tương phản tuyến tính",
    algorithmEn: "Contrast stretching — g = αf  (β=0)",
    citation: "Gonzalez & Woods, DIP 4th ed., Ch.3 — Contrast stretching",
    file: "ai-engine/app/vision/enhancement/enhance.py",
    code: `def apply_contrast(frame_bgr, alpha: float):
    return cv2.convertScaleAbs(frame_bgr, alpha=alpha, beta=0.0)`,
    purpose:
      "Kéo dãn khoảng cách mức xám để cạnh sản phẩm/nền kệ tách rõ hơn khi histogram bị dồn giữa — hỗ trợ YOLO vẽ bbox.",
    formulas: [
      {
        expr: "g(x,y) = clip( α · f(x,y) , 0, 255 )",
        purpose:
          "α > 1 giãn tương phản; α < 1 nén. β = 0 nên không dịch độ sáng trung bình (khác bước brightness).",
      },
    ],
    symbols: [{ name: "α (alpha)", meaning: PARAM_GLOSSARY.alpha }],
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
    purpose:
      "Quầy có vùng đèn mạnh và góc tối. CLAHE cân bằng histogram từng ô, có cắt đỉnh để không khuếch đại nhiễu — làm nét chữ/nhãn mà không đổi màu (chỉ kênh L).",
    formulas: [
      {
        expr: "H_clip(k) = min( H(k), clip_limit ) ;  phần dư trải đều các bin\ns = (L−1) · CDF(H_clip)(r)",
        purpose:
          "AHE trên từng tile rồi nội suy bilinear. Clip hạn chế “đốm” trên nền đồng nhất. Biến đổi trên L (CIE Lab) giữ a,b — tránh lệch màu thương hiệu.",
      },
    ],
    symbols: [
      { name: "L, a, b", meaning: "Kênh sáng và hai kênh màu đối lập trong không gian Lab." },
      { name: "clip_limit", meaning: PARAM_GLOSSARY.clip_limit },
      { name: "tile_grid_size", meaning: PARAM_GLOSSARY.tile_grid_size },
      { name: "H(k)", meaning: "Histogram số đếm mức xám k trong một ô." },
      { name: "CDF", meaning: "Hàm phân phối tích luỹ — ánh xạ mức cũ sang mức mới (equalization)." },
    ],
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
    purpose:
      "Khi cả khung đều tối hoặc đều phẳng, equalization toàn cục trải đều mức xám. Mạnh hơn CLAHE nhưng dễ “nổ” nhiễu nếu đã có vùng sáng — dùng khi không bật CLAHE.",
    formulas: [
      {
        expr: "s_k = round( (L−1) · CDF(r_k) )",
        purpose:
          "Công thức equalization chuẩn: mức mới tỉ lệ với xác suất tích luỹ. Áp trên L để không nhuộm màu chai/nhãn.",
      },
    ],
    symbols: [
      { name: "L", meaning: "Số mức xám (256 với ảnh 8-bit)." },
      { name: "r_k", meaning: "Mức xám gốc thứ k." },
      { name: "CDF", meaning: "Phân phối tích luỹ histogram toàn ảnh (không chia tile)." },
    ],
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
    purpose:
      "Lọc thông thấp: giảm nhiễu cảm biến trước detector. Kernel phải lẻ. σ = 0 để OpenCV chọn σ theo kích thước kernel.",
    formulas: [
      {
        expr: "G_σ(x,y) = (1/(2πσ²)) exp( −(x²+y²)/(2σ²) )\nI' = I * G_σ",
        purpose:
          "Tích chập với kernel Gaussian. Làm mờ hạt nhiễu nhưng cũng làm mềm cạnh — kernel lớn hại YOLO, nên giữ nhỏ trên quầy.",
      },
    ],
    symbols: [
      { name: "kernel_size", meaning: PARAM_GLOSSARY.kernel_size },
      { name: "σ", meaning: "Độ lệch chuẩn Gaussian; 0 = OpenCV suy từ kernel_size." },
      { name: "*", meaning: "Tích chập rời rạc 2D." },
    ],
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
    purpose:
      "Nhiễu muối-tiêu (pixel 0/255) từ nén JPEG hoặc cảm biến rẻ. Trung vị thay pixel bằng giá trị giữa cửa sổ — xoá xung mà không làm mờ cạnh nhiều như Gaussian.",
    formulas: [
      {
        expr: "I'(x,y) = median{ I(u,v) | (u,v) ∈ cửa sổ k×k quanh (x,y) }",
        purpose:
          "Bộ lọc thống kê thứ tự (order-statistic). Xung là min/max cửa sổ nên bị loại khi lấy trung vị.",
      },
    ],
    symbols: [{ name: "kernel_size (k)", meaning: PARAM_GLOSSARY.kernel_size }],
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
    purpose:
      "Khi mật độ nhiễu xung cao, median cố định làm mất chi tiết nhãn. Adaptive chỉ phình cửa sổ tại pixel còn giống xung (gần 0 hoặc 255), pixel “sạch” giữ nguyên.",
    formulas: [
      {
        expr: "Level A: z_min < z_med < z_max ? → Level B : tăng cửa sổ (k ← k+2)\nLevel B: z_min < z_xy < z_max ? giữ z_xy : thay bằng z_med",
        purpose:
          "Hai mức kiểm tra Gonzalez & Woods Ch.5. Triển khai vector hoá bằng vài lần medianBlur thay vì vòng lặp từng pixel (phù hợp VPS).",
      },
    ],
    symbols: [
      { name: "z_xy", meaning: "Mức xám pixel đang xét." },
      { name: "z_med, z_min, z_max", meaning: "Trung vị, min, max trong cửa sổ hiện tại." },
      { name: "max_kernel", meaning: PARAM_GLOSSARY.max_kernel },
    ],
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
    purpose:
      "Làm mượt nhiễu trên mặt chai/hộp nhưng giữ cạnh chữ và viền bbox. Gaussian thuần sẽ làm mềm biên — hại cả YOLO lẫn crop classifier. Đây là bộ lọc đắt nhất chuỗi OpenCV.",
    formulas: [
      {
        expr: "I'(p) = (1/W_p) Σ_{q∈Ω} G_σs(‖p−q‖) · G_σr(|I(p)−I(q)|) · I(q)",
        purpose:
          "Trọng số vừa theo khoảng cách không gian (σ_s) vừa theo chênh lệch cường độ (σ_r). Hai pixel khác màu mạnh (cạnh) gần như không trộn — đó là lý do biên nhãn còn sắc.",
      },
    ],
    symbols: [
      { name: "p, q", meaning: "Toạ độ pixel đích và lân cận." },
      { name: "W_p", meaning: "Hệ số chuẩn hoá tổng trọng số tại p." },
      { name: "diameter", meaning: PARAM_GLOSSARY.diameter },
      { name: "sigma_color (σ_r)", meaning: PARAM_GLOSSARY.sigma_color },
      { name: "sigma_space (σ_s)", meaning: PARAM_GLOSSARY.sigma_space },
    ],
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
    purpose:
      "Làm nét cạnh sau khi đã khử nhiễu. Bản đồ cao tần (f − blur) cộng trở lại ảnh gốc để chữ in trên nhãn rõ hơn trước YOLO/OCR. amount lớn tạo quầng — mặc định giữ nhỏ.",
    formulas: [
      {
        expr: "g = f + k · (f − G_σ * f)  =  (1+k) f − k (G_σ * f)",
        purpose:
          "Eq. 3.6-8 DIP: k = 1 unsharp chuẩn; k > 1 high-boost. addWeighted chính là (1+k)f − k·blur. Nếu |f−blur| < threshold thì không làm nét (tránh nhiễu tối).",
      },
    ],
    symbols: [
      { name: "f", meaning: "Ảnh vào (sau các bước khử nhiễu)." },
      { name: "k (amount)", meaning: PARAM_GLOSSARY.amount },
      { name: "radius (σ)", meaning: PARAM_GLOSSARY.radius },
      { name: "threshold", meaning: PARAM_GLOSSARY.threshold },
    ],
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
    purpose:
      "Đầu ra chuỗi OpenCV: đây là tensor YOLO thực sự nhìn thấy. So ảnh gốc với ảnh này trên lab để giải thích trong luận văn bước nào đổi độ sáng/nét.",
    formulas: [
      {
        expr: "I_YOLO = E_n ∘ … ∘ E_1 ∘ ROI ∘ Decode (I_bytes)",
        purpose:
          "Hợp thành các toán tử điểm/không gian theo đúng thứ tự cấu hình (gamma → CLAHE → blur → unsharp). Không có bước ẩn giữa final và model.predict.",
      },
    ],
    symbols: [
      { name: "E_i", meaning: "Một bước enhance được bật trong Cấu hình xử lý ảnh." },
      { name: "I_YOLO", meaning: "ndarray BGR uint8 cùng H×W với khung decode (trừ khi ROI đã khoá vùng)." },
    ],
  },
  original: {
    key: "original",
    algorithm: "Ảnh gốc (trước tiền xử lý)",
    algorithmEn: "Raw decoded frame",
    citation: "OpenCV imgcodecs",
    file: "ai-engine/app/api/frame.py",
    code: `original = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
debug.add("original", original, bytes=len(content))`,
    purpose:
      "Mốc đối chứng luận văn: mọi bước sau so với khung này. Nếu YOLO tốt trên original nhưng kém sau enhance thì biết bước OpenCV đang hại detector.",
    formulas: [
      {
        expr: "I_0 = Decode(bytes)   (chưa ROI, chưa enhance)",
        purpose: "Lưu JPEG debug để chèn hình “trước / sau” vào báo cáo.",
      },
    ],
    symbols: [{ name: "bytes", meaning: "Kích thước payload JPEG gốc (kiểm tra nén camera)." }],
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
    purpose:
      "Gói decode, ROI, enhance và đo chất lượng thành một hàm. quality_score quyết định có gắn cờ khung mờ/tối — không thay SKU, chỉ cảnh báo vận hành.",
    formulas: [
      {
        expr: "blur_score = Var( ∇² I_gray )\nbrightness = Ī ,   contrast = σ_I\nQ = (s_bright + s_contrast + s_blur) / 3",
        purpose:
          "Pech-Pacheco: phương sai Laplacian cao = nét. s_bright phạt lệch khỏi 0.5·255; s_contrast = min(1, σ/64); s_blur = min(1, blur/(2·ngưỡng)). Trung bình đơn giản — giải thích được trong luận văn, không phải mô hình học.",
      },
    ],
    symbols: [
      { name: "brightness", meaning: PARAM_GLOSSARY.brightness },
      { name: "contrast", meaning: PARAM_GLOSSARY.contrast },
      { name: "blur_score", meaning: PARAM_GLOSSARY.blur_score },
      { name: "Q (quality_score)", meaning: "Điểm 0–1; dưới image_quality_threshold → is_low_quality." },
      { name: "∇²", meaning: "Toán tử Laplace rời rạc (cv2.Laplacian, CV_64F)." },
    ],
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
    purpose:
      "Tìm “có vật gì, ở đâu”. Video: ByteTrack giữ ID người qua khung. Ảnh tĩnh / manual_scan: chỉ predict + NMS. Box ra đây mới được crop để phân loại SKU.",
    formulas: [
      {
        expr: "IoU(A,B) = |A ∩ B| / |A ∪ B|\nNMS: nếu IoU(box_i, box_j) > t_iou và p_i < p_j → loại box_i",
        purpose:
          "Non-Maximum Suppression tránh hai box cho cùng một chai. t_iou = 0.50 (mặc định Ultralytics).",
      },
      {
        expr: "ByteTrack: p ≥ τ_high → khớp Kalman ; τ_low ≤ p < τ_high → khớp IoU phần còn lại",
        purpose:
          "Tách detection chắc và detection yếu để không mất ID khi bị che một phần — dùng cho luồng người/quầy, không gắn ID sản phẩm trên ảnh tĩnh.",
      },
    ],
    symbols: [
      { name: "conf", meaning: PARAM_GLOSSARY.conf },
      { name: "iou (t_iou)", meaning: PARAM_GLOSSARY.iou },
      { name: "p", meaning: "objectness × P(class) của một box YOLO." },
      { name: "max_det", meaning: "Số box tối đa một khung — giới hạn CPU khi kệ đông." },
      { name: "classes=[0]", meaning: "Chỉ lớp person (COCO) khi track người." },
    ],
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
    purpose:
      "YOLO chỉ ra hình chữ nhật; CNN phân loại SKU cần ảnh sát sản phẩm. Padding 8% giữ vành nhãn/nắp chai mà YOLO có thể cắt cụt. Crop quá nhỏ bỏ — phóng 24px lên 224px chỉ toàn nhiễu.",
    formulas: [
      {
        expr: "c_x1 = max(0, x1 − w_box·pad) ,  c_x2 = min(W, x2 + w_box·pad)\n(tương tự y) ;  bỏ nếu min(c_x2−c_x1, c_y2−c_y1) < min_size",
        purpose:
          "Crop axis-aligned, kẹp trong khung. Cùng tinh thần R-CNN: detector đề xuất vùng, classifier đọc vùng đó.",
      },
    ],
    symbols: [
      { name: "(x1,y1,x2,y2)", meaning: "Góc bbox YOLO trên khung đã preprocess." },
      { name: "padding", meaning: PARAM_GLOSSARY.padding },
      { name: "min_size", meaning: PARAM_GLOSSARY.min_size },
    ],
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
    purpose:
      "MobileNetV3 được train trên phân phối ImageNet. Phải RGB, 224×224, trừ mean chia std — sai bước này làm softmax “tự tin” nhầm SKU.",
    formulas: [
      {
        expr: "x' = (x/255 − μ) / σ    (từng kênh R,G,B)\nμ = (0.485, 0.456, 0.406) ,  σ = (0.229, 0.224, 0.225)",
        purpose:
          "Z-score theo thống kê ImageNet. INTER_AREA khi thu nhỏ giảm aliasing chữ trên nhãn. NCHW là layout ONNX/CNN.",
      },
    ],
    symbols: [
      { name: "μ, σ", meaning: "Mean và std ImageNet từng kênh RGB (không phải BGR)." },
      { name: "224×224", meaning: "Độ phân giải vào MobileNetV3-Small." },
      { name: "NCHW", meaning: "Batch × Channel × Height × Width." },
    ],
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
    purpose:
      "YOLO COCO không biết SKU siêu thị. CNN nhỏ chạy CPU gán mã hàng cho crop. margin mỏng (hai chai giống hình, khác dung tích) → mở OCR.",
    formulas: [
      {
        expr: "P(k) = exp(z_k − max z) / Σ_j exp(z_j − max z)\nconf = max_k P(k) ,   margin = P_{(1)} − P_{(2)}",
        purpose:
          "Softmax ổn định số học (trừ max). conf là xác suất top-1; margin đo độ “lẫn” hai SKU gần nhau — ngưỡng vận hành, không phải hyperparameter YOLO.",
      },
    ],
    symbols: [
      { name: "z (logits)", meaning: "Đầu ra tuyến tính của CNN trước softmax." },
      { name: "P(k)", meaning: "Xác suất giả định crop thuộc SKU k." },
      { name: "conf", meaning: "max P — độ tin cậy classifier." },
      { name: "margin", meaning: "Khoảng cách top-1 và top-2; nhỏ → look-alike, cân nhắc OCR." },
    ],
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
    purpose:
      "Hai SKU cùng hình khối, khác chữ dung tích. CNN dễ nhầm; OCR đọc “500ml” / “1.5L” trên nhãn rồi map catalog. Không chạy mọi crop — quá chậm CPU.",
    formulas: [
      {
        expr: "chạy OCR  ⇔  (conf_cls < τ_cls) ∨ (margin < τ_m)",
        purpose:
          "Cổng logic, không phải công thức học. τ là ngưỡng cấu hình: chỉ tốn OCR khi hình học không đủ phân biệt.",
      },
    ],
    symbols: [
      { name: "text", meaning: "Chuỗi nhận từ nhãn (thương hiệu, dung tích, …)." },
      { name: "ocr_conf", meaning: "Độ tin cậy engine OCR, đưa vào fusion cuối." },
    ],
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
    purpose:
      "Ba giai đoạn phụ thuộc tuần tự: crop xấu thì classifier “tự tin” cũng không đáng tin. Trung bình số học sẽ che mắt xích yếu (0.2 và 0.99 → 0.6). Tích có trọng số giữ mắt xích yếu trên điểm cuối.",
    formulas: [
      {
        expr: "p_final = Π_i  p_i ^{ w_i / Σ w }     (trung bình nhân có trọng số)\nw_YOLO=0.45 , w_cls=0.40 , w_OCR=0.15\n(chỉ nhân các giai đoạn thực sự chạy; trọng số chuẩn hoá lại)",
        purpose:
          "Geometric mean: p_i → 0 kéo p_final xuống. YOLO nặng nhất vì mọi bước sau phụ thuộc bbox. Bỏ OCR thì không bị kẹt trần 0.85.",
      },
    ],
    symbols: [
      { name: "p_YOLO, p_cls, p_OCR", meaning: "Confidence từng giai đoạn, kẹp [0, 1]." },
      { name: "w_i", meaning: "Độ tin cậy tương đối giai đoạn i (cộng = 1 sau khi chuẩn hoá)." },
      { name: "source", meaning: "classifier | class_map | none — ghi vào log để giải thích quyết định SKU." },
    ],
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
    purpose:
      "VPS không GPU không theo kịp 25 fps. Tạm dừng, xuất một JPEG, chờ AI xong rồi nhảy currentTime += Δt. Mỗi mẫu là một thí nghiệm có thể chụp vào luận văn.",
    formulas: [
      {
        expr: "t_{n+1} = t_n + Δt ,   JPEG_quality = 0.85",
        purpose:
          "Lấy mẫu thời gian đều. Δt lớn = ít khung, đủ cho demo quầy; 0.85 cân dung lượng upload và artefact nén trên chữ nhãn.",
      },
    ],
    symbols: [
      { name: "Δt (frameInterval)", meaning: "Bước tua (giây) giữa hai lần kích hoạt AI." },
      { name: "t", meaning: "currentTime của thẻ video — mốc gắn nhật ký giai đoạn." },
    ],
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
    purpose:
      "Phân tích video không được trộn ID ByteTrack với quầy live. Token phiên đổi camera_key logic, bật manual_scan: mỗi bài test một giỏ, ROI lấy từ file chứ không ghi đè camera thật.",
    formulas: [
      {
        expr: "camera_key_lab = camera_key ∥ \"::video::\" ∥ scan_session",
        purpose:
          "Không gian tên tracker/giỏ tách khỏi live. Cùng camera vật lý vẫn ra giỏ khác.",
      },
    ],
    symbols: [
      { name: "scan_session", meaning: "Token ngẫu nhiên một lần bấm Kích hoạt AI / tự chạy." },
      { name: "manual_scan", meaning: "Cờ: emit product_scanned vào giỏ phiên, không merge checkout-p1." },
      { name: "roi_zones", meaning: "Đa giác vẽ trên snapshot video, gửi theo từng khung." },
    ],
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
    purpose:
      "Khép pipeline luận văn: nhận diện chỉ có giá trị khi thành dòng giỏ và đơn POS. SKU phải có trong catalog; ảnh crop gắn dòng để đối chiếu khi demo.",
    formulas: [
      {
        expr: "total = Σ_line  unit_price(sku) · qty\ncheckout: Cart → Order  (source = ai_vision)",
        purpose:
          "Tổng tiền kế toán chuẩn. QR/xác nhận hộ giống quầy live — chứng minh vision không phải pipeline “đồ chơi” tách POS.",
      },
    ],
    symbols: [
      { name: "sku", meaning: "Mã hàng catalog; không map được thì không tạo dòng." },
      { name: "qty", meaning: "Số lượng (thường 1 mỗi lần quét khung)." },
      { name: "photo_key", meaning: "Crop JPEG lưu object storage, hiện trên dòng giỏ." },
      { name: "source", meaning: "ai_vision — phân biệt với giỏ nhập tay." },
    ],
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
  lines.push("", `**Mục đích trong pipeline.** ${def.purpose}`, "");
  if (def.formulas.length) {
    lines.push("**Công thức và ý nghĩa.**", "");
    def.formulas.forEach((f, i) => {
      lines.push(`${i + 1}. \`${f.expr.replace(/\n/g, "  ")}\``);
      lines.push(`   ${f.purpose}`, "");
    });
  }
  if (def.symbols.length) {
    lines.push("**Thuộc tính / ký hiệu.**", "");
    def.symbols.forEach((s) => {
      lines.push(`- \`${s.name}\`: ${s.meaning}`);
    });
    lines.push("");
  }
  const runtime = explainRuntimeParams(opts?.params);
  if (runtime.length) {
    lines.push("**Tham số lần chạy này.**", "");
    runtime.forEach((p) => {
      lines.push(`- \`${p.name}\` = ${p.value} — ${p.meaning}`);
    });
    lines.push("");
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
    "# Phụ lục — Thuật toán, công thức và mã nguồn pipeline VisionMart",
    "",
    "Mỗi mục gồm: vai trò trong siêu thị tự tính tiền, công thức (mục đích từng ký hiệu), tham số lần chạy, rồi mã nguồn. Dán Markdown vào Word hoặc In PDF từ trang lab.",
    "",
    "Luồng: ảnh/video → OpenCV (gamma, CLAHE, lọc) → YOLOv8/ByteTrack → crop → MobileNetV3 → (OCR) → fusion → giỏ/đơn.",
    "",
    body,
  ].join("\n");
}
