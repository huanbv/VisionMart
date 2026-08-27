/**
 * Sinh file .docx khổ A4 cho tiểu luận: Times New Roman 13pt, ảnh + công thức
 * + ghi chú từng giai đoạn. Bố cục báo cáo, không phải bản chụp giao diện lab.
 */
import {
  AlignmentType,
  BorderStyle,
  convertMillimetersToTwip,
  Document,
  Footer,
  Header,
  HeadingLevel,
  ImageRun,
  Packer,
  PageNumber,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  VerticalAlign,
  WidthType,
} from "docx";

import {
  explainRuntimeParams,
  lookupAlgorithm,
  PARAM_GLOSSARY,
} from "@/pages/imageScanAlgorithms";

const FONT = "Times New Roman";
/** 13pt — chuẩn luận văn VN (size trong OOXML tính bằng half-point). */
const PT13 = 26;
const PT12 = 24;
const PT11 = 22;
const PT14 = 28;
const PT16 = 32;
const LINE_15 = 360;

const PAGE_W = convertMillimetersToTwip(210);
const PAGE_H = convertMillimetersToTwip(297);
const MARGIN = {
  top: convertMillimetersToTwip(25),
  bottom: convertMillimetersToTwip(25),
  left: convertMillimetersToTwip(30),
  right: convertMillimetersToTwip(20),
};
const CONTENT_MM = 160;

const THIN = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const BORDERS = { top: THIN, bottom: THIN, left: THIN, right: THIN, insideHorizontal: THIN, insideVertical: THIN };

export type ThesisImage = {
  data: Uint8Array;
  width: number;
  height: number;
  type: "jpg" | "png" | "gif" | "bmp";
};

export type ThesisStage = {
  key: string;
  title: string;
  elapsedMs?: number | null;
  params?: Record<string, unknown>;
  metrics?: { brightness?: number; contrast?: number; blur_score?: number };
  image?: ThesisImage | null;
};

export type ThesisWordInput = {
  kind: "image" | "video";
  context: {
    branchName?: string;
    cameraName?: string;
    detectorTitle: string;
    detectorDetail: string;
    modelFile?: string;
    elapsedMs?: number;
    sourceLabel?: string;
    videoTimeSec?: number | null;
    framesProcessed?: number;
    roiCount?: number;
    opencvMs?: number;
    quality?: {
      quality_score: number;
      brightness: number;
      contrast: number;
      blur_score: number;
      is_blurry: boolean;
      is_low_quality?: boolean;
      reason?: string | null;
    };
  };
  notes: Array<{
    time?: string;
    phase?: string;
    kind?: string;
    message: string;
    detail?: string;
  }>;
  detections: Array<{ label: string; sku?: string | null; confidence: number }>;
  preview?: ThesisImage | null;
  opencvStages: ThesisStage[];
  aiStages: ThesisStage[];
  carts: Array<{
    id: string;
    status: string;
    sessionId?: string | null;
    total: string;
    currency: string;
    lines: Array<{
      sku: string;
      name: string;
      qty: number;
      subtotal: string;
      confidence?: number | null;
    }>;
  }>;
};

function run(text: string, extra?: ConstructorParameters<typeof TextRun>[0]) {
  return new TextRun({ text, font: FONT, size: PT13, ...extra });
}

function pBody(text: string): Paragraph {
  return new Paragraph({
    alignment: AlignmentType.BOTH,
    spacing: { after: 160, line: LINE_15 },
    indent: { firstLine: convertMillimetersToTwip(12.5) },
    children: [run(text)],
  });
}

function pPlain(text: string, extra?: { italics?: boolean; bold?: boolean; center?: boolean; size?: number }): Paragraph {
  return new Paragraph({
    alignment: extra?.center ? AlignmentType.CENTER : AlignmentType.LEFT,
    spacing: { after: 120, line: LINE_15 },
    children: [run(text, { italics: extra?.italics, bold: extra?.bold, size: extra?.size ?? PT13 })],
  });
}

function pCaption(text: string): Paragraph {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 80, after: 240, line: LINE_15 },
    children: [run(text, { italics: true, size: PT12 })],
  });
}

function heading1(text: string): Paragraph {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200, line: LINE_15 },
    children: [run(text, { bold: true, size: PT16 })],
  });
}

function heading2(text: string): Paragraph {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 280, after: 160, line: LINE_15 },
    children: [run(text, { bold: true, size: PT14 })],
  });
}

function cell(text: string, opts?: { bold?: boolean; header?: boolean; widthMm?: number }): TableCell {
  return new TableCell({
    borders: BORDERS,
    width: opts?.widthMm
      ? { size: convertMillimetersToTwip(opts.widthMm), type: WidthType.DXA }
      : undefined,
    shading: opts?.header ? { type: ShadingType.CLEAR, fill: "E7E6E6" } : undefined,
    verticalAlign: VerticalAlign.CENTER,
    margins: { top: 40, bottom: 40, left: 80, right: 80 },
    children: [
      new Paragraph({
        spacing: { after: 0, line: 276 },
        children: [run(text, { bold: opts?.bold || opts?.header, size: opts?.header ? PT12 : PT13 })],
      }),
    ],
  });
}

function simpleTable(headers: string[], rows: string[][], colMm: number[]): Table {
  const total = colMm.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: convertMillimetersToTwip(total), type: WidthType.DXA },
    columnWidths: colMm.map((mm) => convertMillimetersToTwip(mm)),
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) => cell(h, { header: true, widthMm: colMm[i] })),
      }),
      ...rows.map(
        (r) =>
          new TableRow({
            children: r.map((v, i) => cell(v || "—", { widthMm: colMm[i] })),
          }),
      ),
    ],
  });
}

function formulaBox(expr: string): Table {
  const lines = expr.split("\n").map((l) => l.trim()).filter(Boolean);
  return new Table({
    width: { size: convertMillimetersToTwip(CONTENT_MM), type: WidthType.DXA },
    rows: [
      new TableRow({
        children: [
          new TableCell({
            borders: {
              top: { style: BorderStyle.SINGLE, size: 8, color: "2F4B7C" },
              bottom: { style: BorderStyle.SINGLE, size: 8, color: "2F4B7C" },
              left: { style: BorderStyle.SINGLE, size: 12, color: "2F4B7C" },
              right: { style: BorderStyle.SINGLE, size: 4, color: "2F4B7C" },
            },
            shading: { type: ShadingType.CLEAR, fill: "F4F7FB" },
            margins: { top: 80, bottom: 80, left: 120, right: 120 },
            children: lines.map(
              (line) =>
                new Paragraph({
                  alignment: AlignmentType.CENTER,
                  spacing: { after: 40, line: 276 },
                  children: [run(line, { italics: true, size: PT13 })],
                }),
            ),
          }),
        ],
      }),
    ],
  });
}

function fitImage(w: number, h: number, maxW = 480, maxH = 340): { width: number; height: number } {
  const r = Math.min(maxW / Math.max(w, 1), maxH / Math.max(h, 1), 1);
  return { width: Math.max(1, Math.round(w * r)), height: Math.max(1, Math.round(h * r)) };
}

function imageParagraph(img: ThesisImage): Paragraph {
  const size = fitImage(img.width, img.height);
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 80, after: 80 },
    children: [
      new ImageRun({
        type: img.type,
        data: img.data,
        transformation: size,
        altText: { title: "Minh họa giai đoạn", description: "Ảnh trung gian pipeline", name: "stage" },
      }),
    ],
  });
}

function kindLabel(kind?: string): string {
  const map: Record<string, string> = {
    ok: "Thành công",
    warn: "Cảnh báo",
    err: "Lỗi",
    error: "Lỗi",
    info: "Thông tin",
    scan: "Quét khung",
    add: "Cập nhật giỏ",
    remove: "Huỷ / xóa",
    checkout: "Thanh toán",
  };
  return map[kind || ""] || "Ghi nhận";
}

function cartStatusVi(status: string): string {
  if (status === "active") return "Đang mở";
  if (status === "pending_checkout") return "Chờ xác nhận";
  if (status === "abandoned") return "Đã huỷ";
  if (status === "checked_out") return "Đã thanh toán";
  return status;
}

function stampFile(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export async function loadThesisImageFromUrl(url: string | null | undefined): Promise<ThesisImage | null> {
  if (!url) return null;
  try {
    const res = await fetch(url);
    const blob = await res.blob();
    return blobToThesisImage(blob);
  } catch {
    return null;
  }
}

export async function loadThesisImageFromBase64(b64: string | null | undefined): Promise<ThesisImage | null> {
  if (!b64) return null;
  const raw = b64.includes(",") ? b64.slice(b64.indexOf(",") + 1) : b64;
  try {
    const res = await fetch(`data:image/jpeg;base64,${raw}`);
    return blobToThesisImage(await res.blob());
  } catch {
    return null;
  }
}

async function blobToThesisImage(blob: Blob): Promise<ThesisImage | null> {
  const buf = new Uint8Array(await blob.arrayBuffer());
  if (!buf.length) return null;
  let width = 640;
  let height = 480;
  const url = URL.createObjectURL(blob);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("image"));
      el.src = url;
    });
    width = img.naturalWidth || width;
    height = img.naturalHeight || height;
  } catch {
    /* keep defaults */
  } finally {
    URL.revokeObjectURL(url);
  }
  const mime = blob.type.toLowerCase();
  const type: ThesisImage["type"] = mime.includes("png") ? "png" : mime.includes("gif") ? "gif" : mime.includes("bmp") ? "bmp" : "jpg";
  return { data: buf, width, height, type };
}

function appendStage(
  children: Array<Paragraph | Table>,
  stage: ThesisStage,
  sectionNo: string,
  figure: { n: number },
): void {
  const def = lookupAlgorithm(stage.key);
  children.push(heading2(`${sectionNo}  ${stage.title}`));
  if (def) {
    children.push(pBody(def.purpose));
    children.push(
      pPlain(`Thuật toán: ${def.algorithm} (${def.algorithmEn}). Nguồn: ${def.citation}.`, { italics: true, size: PT12 }),
    );
    def.formulas.forEach((f, i) => {
      children.push(pPlain(def.formulas.length > 1 ? `Công thức ${i + 1}` : "Công thức áp dụng", { bold: true }));
      children.push(formulaBox(f.expr));
      children.push(pBody(f.purpose));
    });
    if (def.symbols.length) {
      children.push(pPlain("Bảng ký hiệu", { bold: true }));
      children.push(
        simpleTable(
          ["Ký hiệu / thuộc tính", "Ý nghĩa trong thí nghiệm"],
          def.symbols.map((s) => [s.name, s.meaning]),
          [45, 115],
        ),
      );
    }
  } else {
    children.push(
      pBody(
        `Bước «${stage.title}» (${stage.key}) nằm trong chuỗi xử lý lần chạy này. Hệ thống chưa gắn mục lục thuật toán riêng cho khoá này; ảnh trung gian vẫn được lưu để đối chiếu.`,
      ),
    );
  }

  const runtime = explainRuntimeParams(stage.params);
  if (runtime.length) {
    children.push(pPlain("Tham số lần chạy này", { bold: true }));
    children.push(
      simpleTable(
        ["Tham số", "Giá trị", "Dùng để làm gì"],
        runtime.map((p) => [p.name, p.value, p.meaning]),
        [32, 28, 100],
      ),
    );
  }

  const m = stage.metrics;
  if (m && (m.brightness != null || m.contrast != null || m.blur_score != null)) {
    const bits: string[] = [];
    if (m.brightness != null) bits.push(`độ sáng trung bình Ī = ${m.brightness.toFixed(1)} (${PARAM_GLOSSARY.brightness})`);
    if (m.contrast != null) bits.push(`độ lệch chuẩn σ_I = ${m.contrast.toFixed(1)} (${PARAM_GLOSSARY.contrast})`);
    if (m.blur_score != null) bits.push(`độ nét Laplacian = ${m.blur_score.toFixed(1)} (${PARAM_GLOSSARY.blur_score})`);
    children.push(pBody(`Ghi chú đo lường ngay sau bước này: ${bits.join(" ")}`));
  }
  if (stage.elapsedMs != null) {
    children.push(pPlain(`Thời gian thực thi bước: ${Number(stage.elapsedMs).toFixed(1)} ms.`, { italics: true, size: PT12 }));
  }
  if (stage.image) {
    figure.n += 1;
    children.push(imageParagraph(stage.image));
    children.push(pCaption(`Hình ${figure.n}. Ảnh trung gian — ${stage.title}`));
  }
}

function buildDocument(input: ThesisWordInput): Document {
  const children: Array<Paragraph | Table> = [];
  const figure = { n: 0 };
  const isVideo = input.kind === "video";
  const experimentTitle = isVideo
    ? "Thí nghiệm phân tích video quầy và tạo đơn hàng tự động"
    : "Thí nghiệm tải ảnh tĩnh và nhận diện mã hàng (SKU)";
  const now = new Date().toLocaleString("vi-VN", { dateStyle: "long", timeStyle: "short" });

  children.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 80 },
      children: [run("PHỤ LỤC THỰC NGHIỆM", { bold: true, size: 36 })],
    }),
  );
  children.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 80 },
      children: [run("HỆ THỐNG NHẬN DIỆN SẢN PHẨM VISIONMART", { bold: true, size: PT16 })],
    }),
  );
  children.push(
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
      children: [run(experimentTitle, { italics: true, size: PT14 })],
    }),
  );
  children.push(
    pPlain(
      "Khổ giấy A4 · Phông Times New Roman 13pt · Giãn dòng 1,5. Tài liệu được biên tập từ nhật ký pipeline (ảnh trung gian, công thức, tham số lần chạy), không phải bản xuất giao diện phần mềm.",
      { center: true, italics: true, size: PT12 },
    ),
  );
  children.push(pPlain(`Thời điểm xuất: ${now}`, { center: true, size: PT12 }));

  children.push(heading1("1. Mô tả thí nghiệm"));
  children.push(
    pBody(
      isVideo
        ? "Thí nghiệm tái hiện luồng thanh toán bằng camera: thư viện video được tua tới đoạn mặt quầy, tạm dừng, rồi kích hoạt nhận diện trên một khung (hoặc lấy mẫu đều theo thời gian). Mục tiêu là chứng minh chuỗi Decode → ROI → tiền xử lý OpenCV → YOLOv8 → crop → MobileNetV3 → giỏ hàng / đơn POS trên dữ liệu video, tách biệt khỏi giỏ live của quầy."
        : "Thí nghiệm dùng một ảnh quầy (tải lên hoặc chụp khung live) để chạy trọn pipeline nhận diện. Mục tiêu là ghi lại, theo đúng thứ tự xử lý, từng phép biến đổi ảnh và quyết định SKU — phục vụ minh họa trong tiểu luận thạc sĩ — chứ không mô tả thao tác nút bấm trên màn hình lab.",
    ),
  );

  const ctxRows: string[][] = [
    ["Nguồn dữ liệu", input.context.sourceLabel || (isVideo ? "Khung video" : "Ảnh tĩnh")],
    ["Chi nhánh", input.context.branchName || "—"],
    ["Camera (ngữ cảnh cấu hình)", input.context.cameraName || "—"],
    ["Bộ nhận diện", `${input.context.detectorTitle}. ${input.context.detectorDetail}`],
    ["Tệp trọng số / model", input.context.modelFile || "—"],
  ];
  if (input.context.elapsedMs != null) ctxRows.push(["Thời gian suy luận AI", `${Math.round(input.context.elapsedMs)} ms`]);
  if (input.context.opencvMs != null) ctxRows.push(["Thời gian chuỗi OpenCV", `${Math.round(input.context.opencvMs)} ms`]);
  if (input.context.videoTimeSec != null) ctxRows.push(["Mốc thời gian trên video", `${input.context.videoTimeSec.toFixed(1)} s`]);
  if (input.context.framesProcessed != null) ctxRows.push(["Số khung đã gửi AI", String(input.context.framesProcessed)]);
  if (input.context.roiCount != null) {
    ctxRows.push([
      "Vùng quan tâm (ROI)",
      input.context.roiCount > 0
        ? `${input.context.roiCount} đa giác — chỉ pixel trong vùng được đưa vào detector`
        : "Không vẽ ROI — toàn khung",
    ]);
  }
  children.push(simpleTable(["Hạng mục", "Giá trị"], ctxRows, [50, 110]));

  const q = input.context.quality;
  if (q) {
    children.push(
      pBody(
        `Sau tiền xử lý, hệ thống đo chất lượng khung: điểm tổng hợp Q = ${q.quality_score.toFixed(2)} (trung bình các điểm sáng, tương phản và nét). Độ sáng Ī = ${q.brightness.toFixed(1)}; tương phản σ_I = ${q.contrast.toFixed(1)}; độ nét Laplacian = ${q.blur_score.toFixed(1)}. ${
          q.is_blurry ? "Khung bị gắn cờ mờ so với ngưỡng cấu hình." : "Khung không bị gắn cờ mờ."
        }${q.reason ? ` Ghi chú kỹ thuật: ${q.reason}.` : ""} Các đại lượng này không đổi SKU; chúng giải thích vì sao một lần chạy có thể bị từ chối hoặc cảnh báo.`,
      ),
    );
  }

  children.push(heading1("2. Dữ liệu đầu vào"));
  if (input.preview) {
    figure.n += 1;
    children.push(
      pBody(
        isVideo
          ? "Hình dưới là khung video tại thời điểm kích hoạt AI — đầu vào của chuỗi Decode, trước khi ROI và các bộ lọc."
          : "Hình dưới là ảnh đưa vào thí nghiệm, trước các phép enhance. Các hình ở mục sau là ảnh trung gian của cùng lần chạy.",
      ),
    );
    children.push(imageParagraph(input.preview));
    children.push(pCaption(`Hình ${figure.n}. ${isVideo ? "Khung video tại thời điểm suy luận" : "Ảnh đầu vào của thí nghiệm"}`));
  } else {
    children.push(pBody("Không nhúng được ảnh đầu vào (trình duyệt không giữ bản sao khung). Các ảnh giai đoạn bên dưới vẫn đủ để minh họa pipeline."));
  }

  children.push(heading1("3. Nhật ký vận hành"));
  children.push(
    pBody(
      "Bảng dưới tóm tắt diễn biến lần chạy theo thời gian thực — tương ứng các mốc trong pipeline, viết lại thành ghi chú thí nghiệm chứ không sao chép giao diện nhật ký.",
    ),
  );
  if (input.notes.length) {
    children.push(
      simpleTable(
        ["Thời điểm", "Nhóm", "Nội dung"],
        input.notes.map((n) => {
          const body = n.detail ? `${n.message} (${n.detail})` : n.message;
          const group = n.phase || kindLabel(n.kind);
          return [n.time || "—", group, body];
        }),
        [28, 32, 100],
      ),
    );
  } else {
    children.push(pBody("Không có dòng nhật ký kèm lần xuất này."));
  }

  children.push(heading1("4. Tiền xử lý ảnh (OpenCV)"));
  children.push(
    pBody(
      "Trước YOLOv8, khung được giải mã JPEG/PNG, (tuỳ cấu hình) cắt vùng ROI, rồi lần lượt các phép điểm và lọc không gian: gamma, dịch độ sáng, giãn tương phản, CLAHE hoặc cân bằng histogram, lọc nhiễu, unsharp. Thứ tự đúng như cấu hình camera / lần trace. Mỗi tiểu mục nêu mục đích tại quầy, công thức, ký hiệu, tham số đo được, và ảnh sau bước đó.",
    ),
  );
  if (!input.opencvStages.length) {
    children.push(
      pBody(
        "Lần chạy này không lưu vết OpenCV (cần bật lưu vết tại cấu hình xử lý ảnh). Phần nhận diện SKU bên dưới vẫn có ảnh DEBUG nếu đã yêu cầu nhật ký giai đoạn.",
      ),
    );
  } else {
    input.opencvStages.forEach((s, i) => appendStage(children, s, `4.${i + 1}`, figure));
  }

  children.push(heading1("5. Nhận diện đối tượng và gán SKU"));
  children.push(
    pBody(
      "Sau tiền xử lý, YOLOv8 đề xuất hộp bao; NMS loại hộp chồng; mỗi hộp được crop (có đệm) rồi chuẩn hoá ImageNet trước MobileNetV3. Softmax cho P(SKU | crop); khi lề top-1/top-2 mỏng có thể gọi OCR. Độ tin cậy cuối là trung bình nhân có trọng số (YOLO 0,45 — classifier 0,40 — OCR 0,15) để mắt xích yếu không bị trung bình số học che đi.",
    ),
  );
  if (!input.aiStages.length) {
    children.push(
      pBody(
        isVideo
          ? "Chế độ tự chạy nhiều khung không đính JPEG từng bước (tránh quá tải). Hãy dùng «Kích hoạt AI tại khung này (ghi luận văn)» rồi xuất Word để có đủ ảnh giai đoạn."
          : "Không có ảnh DEBUG từng bước AI. Hãy quét lại với nhật ký giai đoạn (include_debug_steps).",
      ),
    );
  } else {
    input.aiStages.forEach((s, i) => appendStage(children, s, `5.${i + 1}`, figure));
  }

  children.push(heading1("6. Kết quả nhận diện và giỏ hàng"));
  if (input.detections.length) {
    children.push(pBody("Các hộp detector giữ lại sau ngưỡng tin cậy, kèm SKU nếu bước phân loại / ánh xạ catalog thành công."));
    children.push(
      simpleTable(
        ["Đối tượng", "SKU", "Độ tin cậy"],
        input.detections.map((d) => [
          d.label,
          d.sku || "—",
          `${Math.round(d.confidence * 100)}%`,
        ]),
        [70, 45, 45],
      ),
    );
  } else {
    children.push(pBody("Không có hộp nhận diện kèm lần xuất này (khung trống, ROI lệch, hoặc model chưa map SKU)."));
  }

  if (input.carts.length) {
    children.push(
      pBody(
        "Giỏ dưới đây phát sinh từ sự kiện product_scanned của chính thí nghiệm (không lẫn giỏ live của quầy). Tổng tiền theo đơn giá catalog × số lượng.",
      ),
    );
    input.carts.forEach((c, i) => {
      children.push(heading2(`6.${i + 1}. Giỏ ${c.id.slice(0, 8)} — ${cartStatusVi(c.status)}`));
      if (c.sessionId) children.push(pPlain(`Phiên: ${c.sessionId}`, { italics: true, size: PT12 }));
      if (c.lines.length) {
        children.push(
          simpleTable(
            ["Sản phẩm", "SKU", "SL", "Thành tiền"],
            c.lines.map((l) => [l.name, l.sku, String(l.qty), l.subtotal]),
            [70, 35, 20, 35],
          ),
        );
      } else {
        children.push(pBody("Giỏ không có dòng hàng (SKU chưa có trong catalog hoặc dòng đã bị xoá)."));
      }
      children.push(pPlain(`Tổng cộng: ${c.total} ${c.currency}.`, { bold: true }));
    });
  } else {
    children.push(
      pBody("Chưa tạo được giỏ từ lần chạy này. Điều kiện thường gặp: SKU chưa có trong catalog, hoặc pipeline không phát sự kiện product_scanned."),
    );
  }

  children.push(heading1("7. Kết luận ngắn cho lần chạy"));
  const nBox = input.detections.length;
  const nSku = input.detections.filter((d) => d.sku).length;
  const nCart = input.carts.length;
  children.push(
    pBody(
      `Tóm tắt định lượng: ${nBox} hộp nhận diện, ${nSku} hộp có SKU, ${nCart} giỏ được ghi nhận, ${input.opencvStages.length} ảnh trung gian OpenCV và ${input.aiStages.length} ảnh DEBUG AI. Các công thức ở mục 4–5 đủ để trích vào chương phương pháp (gamma, CLAHE, Laplacian, IoU/NMS, softmax, fusion). Ảnh «Hình n» là minh họa thực nghiệm, không phải ảnh minh hoạ giả lập.`,
    ),
  );

  return new Document({
    creator: "VisionMart",
    title: `Phụ lục thực nghiệm — ${experimentTitle}`,
    description: "Nhật ký pipeline nhận diện sản phẩm, bố cục A4 Times New Roman 13pt",
    styles: {
      default: {
        document: {
          run: { font: FONT, size: PT13 },
          paragraph: { spacing: { line: LINE_15 } },
        },
      },
      paragraphStyles: [
        {
          id: "Heading1",
          name: "Heading 1",
          basedOn: "Normal",
          next: "Normal",
          quickStyle: true,
          run: { font: FONT, size: PT16, bold: true, color: "000000" },
          paragraph: { spacing: { before: 360, after: 200, line: LINE_15 }, outlineLevel: 0 },
        },
        {
          id: "Heading2",
          name: "Heading 2",
          basedOn: "Normal",
          next: "Normal",
          quickStyle: true,
          run: { font: FONT, size: PT14, bold: true, color: "000000" },
          paragraph: { spacing: { before: 280, after: 160, line: LINE_15 }, outlineLevel: 1 },
        },
      ],
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: PAGE_W, height: PAGE_H },
            margin: MARGIN,
          },
        },
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "888888", space: 4 } },
                children: [run("VisionMart — Phụ lục thực nghiệm nhận diện sản phẩm", { italics: true, size: PT11, color: "666666" })],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  run("Trang ", { size: PT11 }),
                  new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: PT11 }),
                  run(" / ", { size: PT11 }),
                  new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: PT11 }),
                  run("  ·  A4  ·  Times New Roman 13pt", { size: PT11 }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });
}

export async function downloadThesisWord(input: ThesisWordInput): Promise<string> {
  const doc = buildDocument(input);
  const blob = await Packer.toBlob(doc);
  const filename = `VisionMart_PhuLuc_${input.kind === "video" ? "Video" : "TaiAnh"}_${stampFile()}.docx`;
  triggerDownload(blob, filename);
  return filename;
}
