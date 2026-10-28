import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// 只验"输入步存在且能指路"；`refresh()` 在无项目时会提前返回，所以这里不需要 mock 任何接口。
vi.mock("../shared/api/projectApi", () => ({
  listProjects: vi.fn().mockResolvedValue([]),
  createProject: vi.fn(),
  createProjectFromUrl: vi.fn(),
  updateProject: vi.fn(),
}));

import { DirectorMode } from "./DirectorMode";

describe("导演模式的输入步（与小白**并存**，不是它的下游分支）", () => {
  it("没有项目时落在「输入」步：能上传商品图 / 贴商品链接", () => {
    render(<DirectorMode projectId={null} />);
    expect(screen.getByRole("heading", { name: "给素材就能开始" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上传商品图" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "贴商品链接" })).toBeInTheDocument();
    // 还没给素材 → 开始按钮不可点（不让人对着空输入干点）
    expect(screen.getByRole("button", { name: /开始（到分镜）/ })).toBeDisabled();
  });

  it("步骤条是「输入 + 4 个工作步骤」（按序号定位，避免和卡片里的按钮撞名）", () => {
    render(<DirectorMode projectId={null} />);
    const steps: [number, string][] = [[1, "输入"], [2, "分镜"], [3, "素材"], [4, "合成"], [5, "交付"]];
    for (const [order, label] of steps) {
      expect(screen.getByRole("button", { name: new RegExp(`^${order}\\s*${label}`) })).toBeInTheDocument();
    }
  });
});
