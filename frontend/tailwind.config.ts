import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#1677ff",
          dark: "#0f172a",
        },
      },
    },
  },
  // Avoid Tailwind preflight overriding Ant Design's base styles.
  corePlugins: {
    preflight: false,
  },
  plugins: [],
} satisfies Config;
