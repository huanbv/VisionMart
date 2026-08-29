import { useEffect, useMemo, useState } from "react";
import {
  Button,
  Card,
  DatePicker,
  Select,
  Space,
  Table,
  Tabs,
  Typography,
  message,
} from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";

import { listBranches, type Branch } from "@/api/tenancy";
import {
  downloadReportCsv,
  fetchInventoryValuation,
  fetchSalesByBranch,
  fetchSalesByDay,
  fetchTopCustomers,
  fetchTopProducts,
  type InventoryValuationRow,
  type SalesByBranchRow,
  type SalesByDayRow,
  type TopCustomerRow,
  type TopProductRow,
} from "@/api/reports";

const { RangePicker } = DatePicker;

const fmtMoney = (v: string | number) =>
  Number(v).toLocaleString("vi-VN", { maximumFractionDigits: 0 });

export default function ReportsPage() {
  const [range, setRange] = useState<[Dayjs, Dayjs]>([
    dayjs().startOf("month"),
    dayjs().endOf("day"),
  ]);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchId, setBranchId] = useState<string | undefined>();
  const [tab, setTab] = useState("by-day");

  const [salesDay, setSalesDay] = useState<SalesByDayRow[]>([]);
  const [salesBranch, setSalesBranch] = useState<SalesByBranchRow[]>([]);
  const [topProds, setTopProds] = useState<TopProductRow[]>([]);
  const [valuation, setValuation] = useState<InventoryValuationRow[]>([]);
  const [topCust, setTopCust] = useState<TopCustomerRow[]>([]);
  const [loading, setLoading] = useState(false);

  const params = useMemo(
    () => ({
      date_from: range[0].startOf("day").toISOString(),
      date_to: range[1].endOf("day").toISOString(),
      branch_id: branchId,
    }),
    [range, branchId],
  );

  useEffect(() => {
    listBranches({ limit: 200 })
      .then((r) => setBranches(r.items))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const load = async () => {
      try {
        if (tab === "by-day") {
          const r = await fetchSalesByDay(params);
          if (!cancelled) setSalesDay(r);
        } else if (tab === "by-branch") {
          const r = await fetchSalesByBranch({
            date_from: params.date_from,
            date_to: params.date_to,
          });
          if (!cancelled) setSalesBranch(r);
        } else if (tab === "top-products") {
          const r = await fetchTopProducts({ ...params, limit: 100 });
          if (!cancelled) setTopProds(r);
        } else if (tab === "valuation") {
          const r = await fetchInventoryValuation({ branch_id: branchId });
          if (!cancelled) setValuation(r);
        } else if (tab === "top-customers") {
          const r = await fetchTopCustomers({
            date_from: params.date_from,
            date_to: params.date_to,
            limit: 100,
          });
          if (!cancelled) setTopCust(r);
        }
      } catch {
        if (!cancelled) message.error("Không tải được báo cáo");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [tab, params, branchId]);

  const dayCols: ColumnsType<SalesByDayRow> = [
    { title: "Ngày", dataIndex: "day", width: 140 },
    { title: "Số đơn", dataIndex: "orders", width: 120, align: "right" },
    {
      title: "Doanh thu (VND)",
      dataIndex: "revenue",
      align: "right",
      render: fmtMoney,
    },
  ];

  const branchCols: ColumnsType<SalesByBranchRow> = [
    { title: "Chi nhánh", dataIndex: "branch_name" },
    { title: "Số đơn", dataIndex: "orders", width: 120, align: "right" },
    {
      title: "Doanh thu (VND)",
      dataIndex: "revenue",
      align: "right",
      render: fmtMoney,
    },
  ];

  const prodCols: ColumnsType<TopProductRow> = [
    { title: "SKU", dataIndex: "sku", width: 140 },
    { title: "Sản phẩm", dataIndex: "name" },
    { title: "SL", dataIndex: "quantity", width: 120, align: "right" },
    {
      title: "Doanh thu (VND)",
      dataIndex: "revenue",
      align: "right",
      render: fmtMoney,
    },
  ];

  const valCols: ColumnsType<InventoryValuationRow> = [
    { title: "SKU", dataIndex: "sku", width: 140 },
    { title: "Sản phẩm", dataIndex: "product_name" },
    { title: "Chi nhánh", dataIndex: "branch_name", width: 180 },
    { title: "Tồn", dataIndex: "quantity", width: 100, align: "right" },
    {
      title: "Đơn giá",
      dataIndex: "unit_price",
      width: 140,
      align: "right",
      render: fmtMoney,
    },
    {
      title: "Giá trị tồn",
      dataIndex: "total_value",
      width: 160,
      align: "right",
      render: fmtMoney,
    },
  ];

  const custCols: ColumnsType<TopCustomerRow> = [
    { title: "Khách hàng", dataIndex: "full_name", render: (v) => v ?? "(không tên)" },
    { title: "SĐT", dataIndex: "phone", width: 160 },
    { title: "Đơn", dataIndex: "orders", width: 100, align: "right" },
    {
      title: "Tổng chi tiêu (VND)",
      dataIndex: "revenue",
      align: "right",
      render: fmtMoney,
    },
  ];

  const onExport = () => {
    const base = {
      date_from: params.date_from,
      date_to: params.date_to,
      branch_id: branchId,
    };
    if (tab === "by-day")
      return downloadReportCsv("/reports/sales/by-day", base, "sales-by-day.csv");
    if (tab === "by-branch")
      return downloadReportCsv(
        "/reports/sales/by-branch",
        { date_from: base.date_from, date_to: base.date_to },
        "sales-by-branch.csv",
      );
    if (tab === "top-products")
      return downloadReportCsv(
        "/reports/sales/top-products",
        { ...base, limit: 100 },
        "top-products.csv",
      );
    if (tab === "valuation")
      return downloadReportCsv(
        "/reports/inventory/valuation",
        { branch_id: branchId },
        "inventory-valuation.csv",
      );
    if (tab === "top-customers")
      return downloadReportCsv(
        "/reports/customers/top",
        { date_from: base.date_from, date_to: base.date_to, limit: 100 },
        "top-customers.csv",
      );
  };

  return (
    <Card
      title="Báo cáo"
      extra={
        <Space>
          <RangePicker
            value={range}
            onChange={(v) => v && setRange(v as [Dayjs, Dayjs])}
            allowClear={false}
          />
          <Select
            allowClear
            placeholder="Tất cả chi nhánh"
            style={{ width: 220 }}
            value={branchId}
            onChange={setBranchId}
            options={branches.map((b) => ({ value: b.id, label: b.name }))}
          />
          <Button icon={<DownloadOutlined />} onClick={onExport}>
            Tải CSV
          </Button>
        </Space>
      }
    >
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "by-day",
            label: "Doanh thu theo ngày",
            children: (
              <Table<SalesByDayRow>
                rowKey="day"
                size="middle"
                loading={loading}
                columns={dayCols}
                dataSource={salesDay}
                pagination={{ pageSize: 31 }}
              />
            ),
          },
          {
            key: "by-branch",
            label: "Doanh thu theo chi nhánh",
            children: (
              <Table<SalesByBranchRow>
                rowKey="branch_id"
                size="middle"
                loading={loading}
                columns={branchCols}
                dataSource={salesBranch}
                pagination={false}
              />
            ),
          },
          {
            key: "top-products",
            label: "Sản phẩm bán chạy",
            children: (
              <Table<TopProductRow>
                rowKey="product_id"
                size="middle"
                loading={loading}
                columns={prodCols}
                dataSource={topProds}
                pagination={{ pageSize: 20 }}
              />
            ),
          },
          {
            key: "valuation",
            label: "Giá trị tồn kho",
            children: (
              <>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                  Tính theo giá bán hiện tại × số lượng tồn.
                </Typography.Paragraph>
                <Table<InventoryValuationRow>
                  rowKey={(r) => `${r.sku}-${r.branch_name}`}
                  size="middle"
                  loading={loading}
                  columns={valCols}
                  dataSource={valuation}
                  pagination={{ pageSize: 20 }}
                />
              </>
            ),
          },
          {
            key: "top-customers",
            label: "Khách hàng VIP",
            children: (
              <Table<TopCustomerRow>
                rowKey="customer_id"
                size="middle"
                loading={loading}
                columns={custCols}
                dataSource={topCust}
                pagination={{ pageSize: 20 }}
              />
            ),
          },
        ]}
      />
    </Card>
  );
}
