import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// vite.config runs in Node; declare process so tsc -b doesn't need @types/node.
declare const process: { env: Record<string, string | undefined> };

// Proxy targets are overridable so the same config works whether Vite runs on
// the host (the 127.0.0.1 defaults) or inside compose (service names via env,
// see compose.override.yaml). Mirrors web/nginx.conf: /api/query -> the query
// plane, /api/* -> the control plane (with the /api prefix stripped).
const control = process.env.VITE_PROXY_CONTROL ?? "http://127.0.0.1:8000";
const query = process.env.VITE_PROXY_QUERY ?? "http://127.0.0.1:8001";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 8080,
    proxy: {
      // order matters: the more specific /api/query is matched before /api
      "/api/query": {
        target: query, changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/query/, "/query"),
      },
      "/api": {
        target: control, changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
