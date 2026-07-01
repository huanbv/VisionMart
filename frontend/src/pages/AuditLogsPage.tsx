import { useEffect, useState } from "react";
import {
  Button,
  Card,
  DatePicker,
  Input,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";

import {
  exportAuditLogsCsv,
  listAuditLogs,
  type AuditLog,
} from "@/api/auditLogs";

const PAGE_SIZE = 50;

function actionColor(action: string): string {
  if (action.startsWith("POST")) return "blue";
  if (action.startsWith("PUT") || action.startsWith("PATCH")) return "gold";
  if (action.startsWith("DELETE")) return "red";
  return "default";
}

export default function AuditLogsPage() {
  const [data, setData] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [resourceType, setResourceType] = useState("");
  const [action, setAction] = useState("");
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const res = await listAuditLogs({
        skip: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
        resource_type: resourceType || undefined,
        action: action || undefined,
        date_from: dateRange?.[0]?.startOf("day").toISOString(),
        date_to: dateRange?.[1]?.endOf("day").toISOString(),
      });
      setData(res.items);
      setTotal(res.total);
    } catch {
      message.error("Không tải được nhật ký");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, resourceType, action, dateRange]);

  const onExport = async () => {
    try {
      const blob = await exportAuditLogsCsv({
        resource_type: resourceType || undefined,
        action: action || undefined,
        date_from: dateRange?.[0]?.startOf("day").toISOString(),
        date_to: dateRange?.[1]?.endOf("day").toISOString(),
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `audit_logs_${new Date().toISOString()}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      message.error("Không xuất được CSV");
    }
  };

  const columns: ColumnsType<AuditLog> = [
    {
      title: "Thời điểm",
      dataIndex: "created_at",
      width: 180,
      render: (v: string) => new Date(v).toLocaleString("vi-VN"),
    },
    {
      title: "Hành động",
      dataIndex: "action",
      width: 160,
      render: (v: string) => <Tag color={actionColor(v)}>{v}</Tag>,
    },
    {
      title: "Tài nguyên",
      dataIndex: "resource_type",
      width: 140,
    },
    {
      title: "ID tài nguyên",
      dataIndex: "resource_id",
      width: 280,
      render: (v: string | null) =>
        v ? <Typography.Text code>{v}</Typography.Text> : "-",
    },
    {
      title: "Người dùng",
      dataIndex: "user_id",
      width: 280,
      render: (v: string | null) =>
        v ? <Typography.Text code>{v}</Typography.Text> : "-",
    },
    {
      title: "IP",
      dataIndex: "ip_address",
      width: 140,
      render: (v: string | null) => v ?? "-",
    },
  ];

  return (
    <Card
      title="Nhật ký hệ thống"
      extra={
        <Button icon={<DownloadOutlined />} onClick={() => void onExport()}>
          Xuất CSV
        </Button>
      }
    >
      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          allowClear
          placeholder="Tài nguyên (vd: products)"
          value={resourceType}
          onChange={(e) => {
            setPage(1);
            setResourceType(e.target.value);
          }}
          style={{ width: 220 }}
        />
        <Input
          allowClear
          placeholder='Hành động (vd: "POST 201")'
          value={action}
          onChange={(e) => {
            setPage(1);
            setAction(e.target.value);
          }}
          style={{ width: 220 }}
        />
        <DatePicker.RangePicker
          value={dateRange ?? undefined}
          onChange={(v) => {
            setPage(1);
            setDateRange(v as [Dayjs, Dayjs] | null);
          }}
        />
      </Space>

      <Table<AuditLog>
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          showSizeChanger: false,
          onChange: (p) => setPage(p),
        }}
        scroll={{ x: 1200 }}
      />
    </Card>
  );
}
