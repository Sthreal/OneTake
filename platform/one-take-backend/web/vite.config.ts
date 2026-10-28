import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // Windows 挂载到 Linux 容器时**文件变更事件不会传到容器**（实测：改了 App.tsx 而 dev server
      // 一直返回旧模块 → 截图/预览都是旧界面）。打开轮询开关，热更新才可靠。
      watch: { usePolling: true, interval: 300 },
      proxy: {
        "/api": {
          target: env.VITE_API_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
