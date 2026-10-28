import { DemoApp } from "./demo/DemoApp";
import { StudioShell } from "./demo/StudioShell";

export default function App() {
  // 默认 = 新前端（两段式侧边栏）；
  // ?demo=1 = 只跑托管主路、不要导航（纯演示 / 录屏用）。
  // 旧工作台已按用户指令于 2026-10-15 完全舍弃。
  const params = new URLSearchParams(window.location.search);
  if (params.get("demo") === "1") return <DemoApp />;
  return <StudioShell />;
}
