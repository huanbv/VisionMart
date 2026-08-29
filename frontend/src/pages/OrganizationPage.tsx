import { useEffect, useState } from "react";
import { Button, Card, Form, Input, message, Skeleton, Typography } from "antd";

import { getOrganization, Organization, updateOrganization } from "@/api/tenancy";
import { useAuth } from "@/contexts/AuthContext";

interface FormValues {
  name: string;
  settings_json: string;
}

const ADMIN_ROLES = new Set(["super_admin", "org_admin"]);

export default function OrganizationPage() {
  const { user } = useAuth();
  const canEdit = !!user?.roles.some((r) => ADMIN_ROLES.has(r));
  const [org, setOrg] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm<FormValues>();

  const load = async () => {
    setLoading(true);
    try {
      const data = await getOrganization();
      setOrg(data);
      form.setFieldsValue({
        name: data.name,
        settings_json: JSON.stringify(data.settings ?? {}, null, 2),
      });
    } catch {
      message.error("Không tải được thông tin tổ chức");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFinish = async (values: FormValues) => {
    let parsed: Record<string, unknown> | null = null;
    try {
      parsed = values.settings_json.trim() ? JSON.parse(values.settings_json) : null;
    } catch {
      message.error("Settings không phải JSON hợp lệ");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateOrganization({
        name: values.name,
        settings: parsed,
      });
      setOrg(updated);
      message.success("Đã cập nhật");
    } catch {
      message.error("Cập nhật thất bại");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Thông tin tổ chức" className="max-w-3xl">
      {loading ? (
        <Skeleton active />
      ) : (
        <Form
          form={form}
          layout="vertical"
          onFinish={onFinish}
          disabled={!canEdit}
        >
          <Form.Item label="Slug">
            <Typography.Text code>{org?.slug}</Typography.Text>
          </Form.Item>
          <Form.Item
            label="Tên tổ chức"
            name="name"
            rules={[{ required: true, max: 255 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label="Settings (JSON)"
            name="settings_json"
            tooltip="Cấu hình tự do của tổ chức dưới dạng JSON object"
          >
            <Input.TextArea rows={8} className="font-mono" />
          </Form.Item>
          {canEdit && (
            <Button type="primary" htmlType="submit" loading={saving}>
              Lưu thay đổi
            </Button>
          )}
          {!canEdit && (
            <Typography.Text type="secondary">
              Bạn không có quyền chỉnh sửa.
            </Typography.Text>
          )}
        </Form>
      )}
    </Card>
  );
}
