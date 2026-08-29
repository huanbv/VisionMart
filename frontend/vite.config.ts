import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Scanners (and some browser tools) request `/.git/config`. Behind nginx the
 * Vite HMR client lives at `/@vite/client`, so that probe becomes
 * `/@vite/client/.git/config` → Vite concatenates it onto `client.mjs` and
 * `readFile` throws ENOTDIR, which paints the red overlay over the app.
 */
function blockGitProbes(): Plugin {
  return {
    name: "block-git-probes",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = (req.url ?? "").split("?")[0] ?? "";
        if (url.includes("/.git") || url.includes(".git/")) {
          res.statusCode = 404;
          res.end();
          return;
        }
        next();
      });
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [blockGitProbes(), react()],
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
    fs: {
      deny: [".env", ".env.*", "*.{crt,pem}", "**/.git/**"],
    },
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Proxy ai-engine, nhưng bỏ qua route SPA /ai-training, /ai-labeling…
      "/ai": {
        target: "http://localhost:8100",
        changeOrigin: true,
        bypass(req) {
          const path = (req.url ?? "").split("?")[0] ?? "";
          if (/^\/ai-/.test(path)) return path;
          return null;
        },
        rewrite: (path) => path.replace(/^\/ai/, ""),
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
