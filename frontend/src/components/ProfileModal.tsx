import { useEffect, useState } from "react";
import { Divider, Form, Input, Modal, message } from "antd";
import { isAxiosError } from "axios";

import { updateProfile } from "@/api/auth";
import { useAuth } from "@/contexts/AuthContext";
import SessionsPanel from "@/components/SessionsPanel";

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

  useEffect(() => {
    if (open) {
      form.setFieldsValue({ full_name: user?.full_name ?? "" });
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
      destroyOnClose
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
      <SessionsPanel />
    </Modal>
  );
}
