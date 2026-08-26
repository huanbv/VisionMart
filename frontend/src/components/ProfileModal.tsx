import { useEffect, useState } from "react";
import { Alert, Button, Divider, Form, Input, Modal, Space, Typography, message } from "antd";
import { CopyOutlined } from "@ant-design/icons";
import { isAxiosError } from "axios";

import { updateProfile } from "@/api/auth";
import { tokenStore } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import SessionsPanel from "@/components/SessionsPanel";

const { Text, Paragraph } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
}

interface FormValues {
  full_name: string;
}

export default function ProfileModal({ open, onClose }: Props) {
  const { user, refreshMe } = useAuth();
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);
  const [accessToken, setAccessToken] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      form.setFieldsValue({ full_name: user?.full_name ?? "" });
      setAccessToken(tokenStore.getAccess());
    }
  }, [open, user, form]);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      await updateProfile(values.full_name.trim() || null);
      await refreshMe();
      message.success("Đã cập nhật hồ sơ");
      onClose();
    } catch (err) {
      if (isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        message.error(
          typeof detail === "string" ? detail : "Không cập nhật được hồ sơ",
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="Hồ sơ cá nhân"
      okText="Lưu"
      cancelText="Hủy"
      confirmLoading={submitting}
      onOk={() => void handleOk()}
      onCancel={onClose}
      destroyOnHidden
      width={640}
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item label="Email">
          <Input value={user?.email ?? ""} disabled />
        </Form.Item>
        <Form.Item label="Tên đăng nhập">
          <Input value={user?.username ?? ""} disabled />
        </Form.Item>
        <Form.Item
          name="full_name"
          label="Họ và tên"
          rules={[{ max: 255, message: "Tối đa 255 ký tự" }]}
        >
          <Input placeholder="Nguyễn Văn A" />
        </Form.Item>
      </Form>
      <Divider />
      <Space direction="vertical" style={{ width: "100%" }} size={8}>
        <Text strong>API access token</Text>
        <Alert
          type="warning"
          showIcon
          message="Token đăng nhập hiện tại — dùng cho curl/API khi cần. Không chia sẻ; hết hạn sau một thời gian."
        />
        <Input.TextArea
          readOnly
          value={accessToken ?? ""}
          rows={4}
          placeholder="Chưa đăng nhập"
          style={{ fontFamily: "monospace", fontSize: 12 }}
        />
        <Button
          icon={<CopyOutlined />}
          disabled={!accessToken}
          onClick={async () => {
            if (!accessToken) return;
            try {
              await navigator.clipboard.writeText(accessToken);
              message.success("Đã copy access token");
            } catch {
              message.error("Không copy được — chọn và copy thủ công");
            }
          }}
        >
          Copy token
        </Button>
        <Paragraph type="secondary" style={{ marginBottom: 0, fontSize: 12 }}>
          Mở modal này bằng cách bấm tên bạn ở góc phải header. Deploy model nên
          dùng nút trên trang Train AI — không cần token tay.
        </Paragraph>
      </Space>
      <Divider />
      <SessionsPanel />
    </Modal>
  );
}
