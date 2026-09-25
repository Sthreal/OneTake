import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const miniclawApiProxyTarget =
    env.VITE_MINICLAW_API_PROXY_TARGET || "http://127.0.0.1:3000";
  const miniclawWsProxyTarget =
    env.VITE_MINICLAW_WS_PROXY_TARGET ||
    miniclawApiProxyTarget.replace(/^http/, "ws");

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/miniclaw-api": {
          target: miniclawApiProxyTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/miniclaw-api/, "/api"),
        },
        "/miniclaw-ws": {
          target: miniclawWsProxyTarget,
          changeOrigin: true,
          ws: true,
          rewrite: (path) => path.replace(/^\/miniclaw-ws/, "/ws"),
        },
        "/api": {
          target: env.VITE_API_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});