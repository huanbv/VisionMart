import { Typography } from "antd";

const { Title, Paragraph } = Typography;

/**
 * Root application shell.
 * Feature routes and layouts will be introduced in subsequent sprints.
 */
export default function App() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-brand-dark text-white p-8">
      <div className="max-w-xl text-center">
        <Title style={{ color: "white" }}>VisionMart</Title>
        <Paragraph style={{ color: "rgba(255,255,255,0.75)" }}>
          Enterprise AI Smart Retail Platform — Sprint 01 foundation ready.
        </Paragraph>
      </div>
    </main>
  );
}
