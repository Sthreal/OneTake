import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// 只验"外壳把哪个视图渲染出来"，所以把三个重页面与 API 全部替换成可识别的桩。
vi.mock("./DemoApp", () => ({ DemoApp: ({ initialProjectId }: { initialProjectId?: string | null }) =>
  <div>MOCK_WORKBENCH:{initialProjectId ?? "none"}</div> }));
vi.mock("./DirectorMode", () => ({ DirectorMode: ({ projectId }: { projectId: string | null }) =>
  <div>MOCK_DIRECTOR:{projectId ?? "none"}</div> }));
vi.mock("./CharactersPage", () => ({ CharactersPage: () => <div>MOCK_CHARACTERS</div> }));
vi.mock("../shared/api/projectApi", () => ({
  listProjects: vi.fn().mockResolvedValue([{ project_id: "prj_x", product_name: "测试商品", created_at: "2026-10-15T00:00:00Z" }]),
  createProject: vi.fn(),
  createProjectFromUrl: vi.fn(),
  updateProject: vi.fn(),
}));

import { listProjects } from "../shared/api/projectApi";
import { StudioShell } from "./StudioShell";

function open(url: string) {
  window.history.replaceState(null, "", url);
}

describe("StudioShell 视图路由（方案 §3.1：4 步独立 URL 的前提是「视图真的按 URL 渲染」）", () => {
  beforeEach(() => {
    open("/");
  });

  it("默认（无参数）→ 工作台", async () => {
    render(<StudioShell />);
    expect(await screen.findByText(/MOCK_WORKBENCH/)).toBeInTheDocument();
  });

  it("?view=director&project=… → **导演模式**（而不是工作台）", async () => {
    open("/?view=director&project=prj_x&step=compose");
    render(<StudioShell />);
    // 这一条就是回归守卫：曾因 `isWorkbench` 里带了 `openProjectId !== null`，
    // 带项目进导演模式时会渲染工作台，导演模式整页**根本进不去**。
    expect(await screen.findByText("MOCK_DIRECTOR:prj_x")).toBeInTheDocument();
    expect(screen.queryByText(/MOCK_WORKBENCH/)).not.toBeInTheDocument();
  });

  it("?view=director（没有项目）→ **直接进导演模式**（它自己就能输入，不是出片的下游）", async () => {
    open("/?view=director");
    render(<StudioShell />);
    expect(await screen.findByText("MOCK_DIRECTOR:none")).toBeInTheDocument();
    expect(screen.queryByText(/MOCK_WORKBENCH/)).not.toBeInTheDocument();
  });

  it("?view=workbench&project=… → 工作台带该项目（原有行为不变）", async () => {
    open("/?view=workbench&project=prj_y");
    render(<StudioShell />);
    expect(await screen.findByText("MOCK_WORKBENCH:prj_y")).toBeInTheDocument();
  });

  it("侧边栏**不再**单开「商品链接」入口（它是工作台内的 tab）", async () => {
    render(<StudioShell />);
    expect(screen.queryByRole("button", { name: "商品链接" })).not.toBeInTheDocument();
    for (const label of ["出片", "导演模式", "项目", "出镜人"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("?view=characters → 出镜人页", async () => {
    open("/?view=characters");
    render(<StudioShell />);
    expect(await screen.findByText("MOCK_CHARACTERS")).toBeInTheDocument();
  });
});
