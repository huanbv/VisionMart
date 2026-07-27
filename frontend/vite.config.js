import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    server: {
        host: true,
        port: 3000,
        strictPort: true,
        allowedHosts: ["visionmart.thehuan.com", "localhost"],
        proxy: {
            "/api": {
                target: "http://localhost:8000",
                changeOrigin: true,
            },
            "/ai": {
                target: "http://ai-engine:8100",
                changeOrigin: true,
                rewrite: function (path) { return path.replace(/^\/ai/, ""); },
            },
            "/ws": {
                target: "ws://localhost:8000",
                ws: true,
            },
        },
    },
    preview: {
        port: 3000,
    },
    build: {
        outDir: "dist",
        sourcemap: true,
        target: "es2022",
    },
});
