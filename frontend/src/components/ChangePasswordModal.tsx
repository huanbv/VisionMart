import { useState } from "react";
import { Form, Input, Modal, message } from "antd";
import { isAxiosError } from "axios";

import { changePassword } from "@/api/auth";

interface Props {
  open: boolean;
  onClose: () => void;
}

interface FormValues {
  current_password: string;
  new_password: string;
  confirm_password: string;
}

export default function ChangePasswordModal({ open, onClose }: Props) {
  const [form] = Form.useForm<FormValues>();
  const [submitting, setSubmitting] = useState(false);

  const handleOk = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      await changePassword(values.current_password, values.new_password);
      message.success("Đã đổi mật khẩu");
      form.resetFields();
      onClose();
    } catch (err) {
      if (isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        message.error(
          typeof detail === "string" ? detail : "Không đổi được mật khẩu",
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      title="Đổi mật khẩu"
      okText="Cập nhật"
      cancelText="Hủy"
      confirmLoading={submitting}
      onOk={() => void handleOk()}
      onCancel={() => {
        form.resetFields();
        onClose();
      }}
      destroyOnClose
    >
      <Form form={form} layout="vertical" preserve={false}>
        <Form.Item
          name="current_password"
          label="Mật khẩu hiện tại"
          rules={[{ required: true, message: "Bắt buộc" }]}
        >
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="new_password"
          label="Mật khẩu mới"
          rules={[
            { required: true, message: "Bắt buộc" },
            { min: 8, message: "Tối thiểu 8 ký tự" },
            { max: 128, message: "Tối đa 128 ký tự" },
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm_password"
          label="Nhập lại mật khẩu mới"
          dependencies={["new_password"]}
          rules={[
            { required: true, message: "Bắt buộc" },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue("new_password") === value) {
                  return Promise.resolve();
                }
                return Promise.reject(new Error("Mật khẩu xác nhận không khớp"));
              },
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
