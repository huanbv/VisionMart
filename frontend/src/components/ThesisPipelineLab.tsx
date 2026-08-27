/**
 * Shared thesis lab UI: per-stage images + algorithm names + copyable source.
 * Used by Tải ảnh & Quét and Phân tích Video.
 */
import { Button, Card, Col, Collapse, Empty, Image, Row, Space, Tag, Typography, message } from "antd";
import { CopyOutlined, DownloadOutlined } from "@ant-design/icons";

import type { DebugStep, PipelineTraceResult, TraceStage } from "@/api/cameras";
import {
  formatAlgorithmMarkdown,
  formatAppendixMarkdown,
  lookupAlgorithm,
} from "@/pages/imageScanAlgorithms";

const { Paragraph, Text, Title } = Typography;

export function copyThesisText(text: string, ok = "Đã copy vào clipboard") {
  void navigator.clipboard.writeText(text).then(
    () => message.success(ok),
    () => message.error("Trình duyệt không cho copy"),
  );
}

function downloadDataUrl(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}

export function AlgorithmSnippet({
  stage,
  title,
  params,
  elapsedMs,
}: {
  stage: string;
  title?: string;
  params?: Record<string, unknown>;
  elapsedMs?: number | null;
}) {
  const def = lookupAlgorithm(stage);
  if (!def) return null;
  const md = formatAlgorithmMarkdown(stage, { title: title ?? def.algorithm, params, elapsedMs });
  return (
    <div style={{ marginTop: 8 }}>
      <Tag color="geekblue" style={{ whiteSpace: "normal", height: "auto" }}>
        {def.algorithm}
      </Tag>
      <div>
        <Text type="secondary" style={{ fontSize: 11 }}>
          {def.algorithmEn}
        </Text>
      </div>
      <Collapse
        size="small"
        style={{ marginTop: 6 }}
        items={[
          {
            key: "code",
            label: "Mã nguồn + tài liệu",
            children: (
              <div>
                <Paragraph style={{ marginBottom: 6, fontSize: 12 }}>
                  {def.citation}
                  <br />
                  <Text code>{def.file}</Text>
                </Paragraph>
                <pre className="algo-code">{def.code}</pre>
                <Button
                  className="no-print"
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => copyThesisText(md, "Đã copy mục này (Markdown)")}
                >
                  Sao chép mục này
                </Button>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}

export function DebugStepGallery({ steps }: { steps: DebugStep[] }) {
  if (!steps.length) return null;
  return (
    <Card title={`Ảnh từng giai đoạn AI (${steps.length} bước)`}>
      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        Chuỗi DEBUG trên khung vừa kích hoạt: ảnh gốc → OpenCV → YOLO → crop → phân loại SKU.
        Tải JPEG hoặc mở mã nguồn để chèn luận văn.
      </Paragraph>
      <Row gutter={[12, 12]}>
        {steps.map((s, i) => (
          <Col xs={24} sm={12} lg={8} key={`${s.step}-${i}`}>
            <Card
              className="print-break"
              size="small"
              title={`${i + 1}. ${s.label}`}
              extra={
                <Button
                  className="no-print"
                  size="small"
                  type="link"
                  icon={<DownloadOutlined />}
                  onClick={() =>
                    downloadDataUrl(
                      `data:image/jpeg;base64,${s.image_jpeg_b64}`,
                      `${String(i + 1).padStart(2, "0")}_${s.step}.jpg`,
                    )
                  }
                />
              }
            >
              <Image
                src={`data:image/jpeg;base64,${s.image_jpeg_b64}`}
                alt={s.label}
                style={{ width: "100%", maxHeight: 200, objectFit: "contain" }}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                {s.step}
                {s.elapsed_ms != null ? ` · ${s.elapsed_ms} ms` : ""}
              </Text>
              <AlgorithmSnippet stage={s.step} title={s.label} params={s.params} elapsedMs={s.elapsed_ms} />
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  );
}

export function OpenCvStageGallery({
  trace,
  stageUrls,
}: {
  trace: PipelineTraceResult;
  stageUrls: Record<number, string>;
}) {
  if (!trace.stages.length) return null;
  return (
    <Card
      title={`Chi tiết tiền xử lý OpenCV (${trace.stages.length} bước · ${trace.opencv_ms.toFixed(0)} ms)`}
      extra={
        trace.quality ? (
          <Tag color={trace.quality.is_low_quality ? "red" : "green"}>
            quality {trace.quality.quality_score.toFixed(2)}
          </Tag>
        ) : null
      }
    >
      <Row gutter={[12, 12]}>
        {trace.stages.map((s: TraceStage) => (
          <Col xs={24} sm={12} lg={8} key={s.order}>
            <Card
              className="print-break"
              size="small"
              title={`${s.order + 1}. ${s.label}`}
              extra={
                stageUrls[s.order] ? (
                  <Button
                    className="no-print"
                    size="small"
                    type="link"
                    icon={<DownloadOutlined />}
                    onClick={() =>
                      downloadDataUrl(
                        stageUrls[s.order],
                        `${String(s.order).padStart(2, "0")}_${s.stage}.jpg`,
                      )
                    }
                  />
                ) : null
              }
            >
              {stageUrls[s.order] ? (
                <Image
                  src={stageUrls[s.order]}
                  alt={s.label}
                  style={{ width: "100%", maxHeight: 180, objectFit: "contain" }}
                />
              ) : (
                <Empty description="Không có JPEG" />
              )}
              <Text type="secondary" style={{ fontSize: 11 }}>
                {s.stage} · {s.elapsed_ms.toFixed(1)} ms · sáng {s.metrics.brightness.toFixed(0)} · nét{" "}
                {s.metrics.blur_score.toFixed(0)}
              </Text>
              <AlgorithmSnippet stage={s.stage} title={s.label} params={s.params} elapsedMs={s.elapsed_ms} />
            </Card>
          </Col>
        ))}
      </Row>
    </Card>
  );
}

export interface ThesisAppendixSection {
  stage: string;
  title: string;
  params?: Record<string, unknown>;
  elapsedMs?: number | null;
}

export function ThesisAppendix({
  sections,
  intro,
}: {
  sections: ThesisAppendixSection[];
  intro?: string;
}) {
  if (!sections.length) return null;
  const markdown = formatAppendixMarkdown(sections);
  return (
    <Card
      title="Phụ lục thuật toán & mã nguồn (copy vào luận văn)"
      extra={
        <Space className="no-print">
          <Button size="small" icon={<CopyOutlined />} onClick={() => copyThesisText(markdown, "Đã copy phụ lục (Markdown)")}>
            Sao chép toàn bộ
          </Button>
          <Button size="small" onClick={() => window.print()}>
            In / lưu PDF
          </Button>
        </Space>
      }
    >
      <Paragraph type="secondary">
        {intro ??
          "Dán vào Word: Markdown hoặc In / lưu PDF. Tên thuật toán kèm tài liệu (YOLOv8, ByteTrack, CLAHE, MobileNetV3, …)."}
      </Paragraph>
      {sections.map((s, i) => {
        const def = lookupAlgorithm(s.stage);
        if (!def) return null;
        return (
          <div key={`${s.stage}-${i}`} className="print-break" style={{ marginBottom: 20 }}>
            <Title level={5} style={{ marginBottom: 4 }}>
              {i + 1}. {s.title}
            </Title>
            <Space wrap size={[4, 4]}>
              <Tag color="geekblue">{def.algorithm}</Tag>
              <Tag>{def.algorithmEn}</Tag>
            </Space>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {def.citation}
              </Text>
            </div>
            <Text code>{def.file}</Text>
            {s.elapsedMs != null && (
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                {s.elapsedMs} ms
              </Text>
            )}
            <pre className="algo-code">{def.code}</pre>
            <Button
              className="no-print"
              size="small"
              icon={<CopyOutlined />}
              onClick={() =>
                copyThesisText(
                  formatAlgorithmMarkdown(s.stage, {
                    title: `${i + 1}. ${s.title}`,
                    params: s.params,
                    elapsedMs: s.elapsedMs,
                  }),
                  "Đã copy mục này",
                )
              }
            >
              Sao chép mục này
            </Button>
          </div>
        );
      })}
    </Card>
  );
}

export const THESIS_CODE_CSS = `
  pre.algo-code {
    background: #f6f8fa;
    border: 1px solid #eaeaea;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 11px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }
  @media print {
    .no-print, .ant-layout-sider, .ant-layout-header { display: none !important; }
    .ant-layout-content { margin: 0 !important; padding: 0 !important; }
    .print-break { break-inside: avoid; page-break-inside: avoid; }
    .ant-collapse-content { display: block !important; height: auto !important; }
  }
`;
