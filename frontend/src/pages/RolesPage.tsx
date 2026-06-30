import { useEffect, useState } from "react";
import { Card, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";

import { listRoles, Role } from "@/api/roles";

export default function RolesPage() {
  const [data, setData] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listRoles()
      .then(setData)
      .catch(() => message.error("Không tải được danh sách vai trò"))
      .finally(() => setLoading(false));
  }, []);

  const columns: ColumnsType<Role> = [
    {
      title: "Code",
      dataIndex: "code",
      width: 200,
      render: (v: string) => <Tag color="blue">{v}</Tag>,
    },
    { title: "Tên", dataIndex: "name", width: 240 },
    { title: "Mô tả", dataIndex: "description", render: (v) => v ?? "—" },
  ];

  return (
    <Card title="Vai trò hệ thống">
      <Table
        rowKey="id"
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={false}
      />
      <p className="text-slate-500 text-sm mt-4 mb-0">
        Các vai trò hệ thống được khởi tạo từ seed. Việc chỉnh sửa quyền chi tiết sẽ
        được bổ sung ở sprint sau.
      </p>
    </Card>
  );
}
