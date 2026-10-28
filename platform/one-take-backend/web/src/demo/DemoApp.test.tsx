import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// 小白主路第一屏的冒烟测试（在此之前**没有任何渲染测试**保护这条主路）。
// 输入链已抽到 `./intake`（与导演模式共用），所以这里把外围接口都打桩。
vi.mock("../shared/api/characterApi", () => ({ listCharacters: vi.fn().mockResolvedValue({ characters: [] }) }));
vi.mock("../shared/api/recognitionApi", () => ({ getPipeline: vi.fn(), getRecognition: vi.fn() }));
vi.mock("../shared/api/projectApi", () => ({
  createProject: vi.fn(),
  createProjectFromUrl: vi.fn(),
  updateProject: vi.fn(),
}));
vi.mock("./api", () => ({ approveCost: vi.fn(), startAutoRun: vi.fn() }));

import { DemoApp } from "./DemoApp";

describe("小白托管主路：第一屏", () => {
  it("默认是上传商品图这一屏：有拖拽区，没选图时「开始生成」不可点", async () => {
    render(<DemoApp />);
    // 拖拽区是**共用组件**（`FileDrop`）：文案承诺的拖拽必须真有实现
    expect(screen.getByTestId("file-drop")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "开始生成" })).toBeDisabled();
  });

  it("页内 tab 就能切到「商品链接」（所以侧边栏不必再开一个入口）", async () => {
    render(<DemoApp />);
    fireEvent.click(await screen.findByRole("button", { name: "商品链接" }));
    expect(await screen.findByPlaceholderText(/贴商品链接/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始生成" })).toBeDisabled();
  });
});
