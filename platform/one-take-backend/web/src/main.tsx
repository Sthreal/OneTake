import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";

/** 清掉历史遗留的 Service Worker / Cache。
 *
 * 为什么必须留着：这个项目早期注册过 SW，浏览器里可能仍有一份在**拦截请求并返回旧壳**，
 * 表现就是"代码明明改了、页面还是旧的或干脆空白"。这里注销 SW、清掉本站缓存，并只重载一次
 * （用 sessionStorage 打标记，避免无限刷新）。2026-10-15 删旧 UI 时曾误删这段，已补回。
 */
async function cleanupLegacyShell(): Promise<void> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    if (registrations.length === 0) {
      // 没有遗留 SW：把「已清理」标记清掉，保证将来真出现 SW 时还能再清一次
      // （旧实现 once-per-session 且永不清除 → 第二次遇到旧壳就再也不自救了）
      sessionStorage.removeItem("onetake-shell-cleaned");
      return;
    }
    await Promise.all(registrations.map((registration) => registration.unregister()));
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => /onetake/i.test(key)).map((key) => caches.delete(key)));
    }
    if (!sessionStorage.getItem("onetake-shell-cleaned")) {
      sessionStorage.setItem("onetake-shell-cleaned", "1");
      window.location.reload();
    }
  } catch {
    // 没有 SW 或读取失败都属正常，静默跳过
  }
}

void cleanupLegacyShell();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
