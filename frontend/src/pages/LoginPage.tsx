import { useState } from "react";
import { Button, Card, Form, Input, Typography, message } from "antd";
import { LockOutlined, MailOutlined } from "@ant-design/icons";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/contexts/AuthContext";

interface LoginFormValues {
  email: string;
  password: string;
}

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [submitting, setSubmitting] = useState(false);

  if (user) {
    const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? "/";
    return <Navigate to={from} replace />;
  }

  const onFinish = async (values: LoginFormValues) => {
    setSubmitting(true);
    try {
      await login(values.email, values.password);
      message.success("Đăng nhập thành công");
      navigate("/", { replace: true });
    } catch (err: unknown) {
      const data = (err as { response?: { data?: { detail?: unknown } } })?.response?.data;
      let detail = "Đăng nhập thất bại";
      if (typeof data?.detail === "string") {
        detail = data.detail;
      } else if (Array.isArray(data?.detail)) {
        detail = data.detail
          .map((d: { msg?: string; loc?: unknown[] }) =>
            `${(d.loc ?? []).slice(1).join(".")}: ${d.msg ?? ""}`.trim(),
          )
          .join("; ");
      }
      message.error(detail);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-900 p-4">
      <Card className="w-full max-w-md shadow-2xl">
        <div className="text-center mb-6">
          <Typography.Title level={2} style={{ marginBottom: 0 }}>
            VisionMart
          </Typography.Title>
          <Typography.Text type="secondary">
            Smart Retail AI Platform
          </Typography.Text>
        </div>
        <Form<LoginFormValues>
          layout="vertical"
          onFinish={onFinish}
          autoComplete="off"
          requiredMark={false}
        >
          <Form.Item
            name="email"
            label="Email"
            rules={[
              { required: true, message: "Vui lòng nhập email" },
              { type: "email", message: "Email không hợp lệ" },
            ]}
          >
            <Input prefix={<MailOutlined />} size="large" placeholder="admin@visionmart.local" />
          </Form.Item>
          <Form.Item
            name="password"
            label="Mật khẩu"
            rules={[{ required: true, message: "Vui lòng nhập mật khẩu" }]}
          >
            <Input.Password prefix={<LockOutlined />} size="large" placeholder="••••••••" />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
              Đăng nhập
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
