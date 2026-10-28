import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/projectApi", () => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
}));
vi.mock("../../shared/api/characterApi", () => ({
  listCharacters: vi.fn(),
}));

import { listCharacters } from "../../shared/api/characterApi";
import { listProjects } from "../../shared/api/projectApi";
import { StudioShell } from "../StudioShell";

const product = {
  project_id: "prj_skin",
  product_name: "春季护肤精华液 30ml",
  product_note: "主图已就绪",
  status: "draft" as const,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
};

function open(url: string) {
  window.history.replaceState(null, "", url);
}

describe("iter18 图片广告与工作室解耦", () => {
  beforeEach(() => {
    open("/");
    vi.mocked(listProjects).mockResolvedValue([product]);
    vi.mocked(listCharacters).mockResolvedValue({
      characters: [{
        character_id: "chr_zhou",
        name: "周予",
        appearance: "",
        voice_style: "男声 · 库",
        source: "uploaded",
        sheet_url: null,
      }],
      sheet_generation: { cny_per_call: null, is_mock: true },
    });
  });

  it("上手第 2 步去图片广告；九宫格主按钮是导出，工作室只是可选", async () => {
    const user = userEvent.setup();
    render(<StudioShell />);
    await user.click(await screen.findByRole("button", { name: "去图片广告" }));

    expect(await screen.findByRole("heading", { name: "图片广告" })).toBeInTheDocument();
    const grid = screen.getByRole("list", { name: "图片广告九宫格" });
    expect(within(grid).getAllByRole("listitem")).toHaveLength(9);
    expect(screen.getByRole("button", { name: "导出选中图（演示）" }).className).toContain("ot-btn-primary");
    expect(screen.getByRole("button", { name: "可选 · 另开工作室出片" }).className).toContain("ot-btn-secondary");

    await user.click(screen.getByRole("button", { name: "导出选中图（演示）" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已导出选中图：白底棚拍");
    expect(screen.getByRole("heading", { name: "图片广告" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "可选 · 另开工作室出片" }));
    expect(await screen.findByRole("heading", { name: "准备素材" })).toBeInTheDocument();
    expect(screen.getByText(/无需先做图片广告/)).toBeInTheDocument();
  });

  it("准备 → 审稿 → 生成 → 成片可以不打开图片广告", async () => {
    const user = userEvent.setup();
    open("/?view=prepare");
    render(<StudioShell />);

    expect(await screen.findByRole("heading", { name: "准备素材" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "图片广告" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加商品" })).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(document.querySelector("textarea")).toBeNull();
    expect(screen.getByText("林晓")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "从出镜人库更换 →" }));
    expect(screen.getByRole("button", { name: /周予/ })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /提示词|描述出镜人|prompt/ })).not.toBeInTheDocument();

    const start = screen.getByRole("button", { name: "开始制作" });
    await waitFor(() => expect(start).toBeEnabled());
    await user.click(start);

    expect(await screen.findByRole("heading", { name: "审稿确认" })).toBeInTheDocument();
    expect(screen.getByText(/无需先做图片广告/)).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "审稿九宫格" })).getAllByRole("listitem")).toHaveLength(9);

    await user.click(screen.getByRole("button", { name: /确认并生成视频/ }));
    expect(await screen.findByRole("heading", { name: "生成中" })).toBeInTheDocument();
    expect(screen.getByText(/不经过图片广告/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看成片" }));
    expect(await screen.findByRole("heading", { name: "成片交付" })).toBeInTheDocument();
    expect(screen.getByText(/没有经过图片广告/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "图片广告" })).not.toBeInTheDocument();
  });

  it("没有商品时准备步不能从零新建，只能去品牌空间", async () => {
    vi.mocked(listProjects).mockResolvedValue([]);
    open("/?view=prepare");
    render(<StudioShell />);
    expect(await screen.findByText(/品牌空间里还没有可选用的商品/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始制作" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "去品牌空间添加" })).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it("上手四步按钮去四个不同页面", async () => {
    const user = userEvent.setup();
    render(<StudioShell />);
    const gs = () => screen.getByRole("region", { name: "开始上手" });

    await user.click(within(gs()).getByRole("button", { name: "加商品" }));
    await user.click(within(gs()).getByRole("button", { name: "去品牌空间" }));
    expect(await screen.findByRole("heading", { name: "品牌空间" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "首页" }));
    await user.click(within(gs()).getByRole("button", { name: "图片广告" }));
    await user.click(within(gs()).getByRole("button", { name: "去图片广告" }));
    expect(await screen.findByRole("heading", { name: "图片广告" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "返回首页" }));
    await user.click(within(gs()).getByRole("button", { name: "生成视频" }));
    await user.click(within(gs()).getByRole("button", { name: "进入工作室" }));
    expect(await screen.findByRole("heading", { name: "准备素材" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "← 首页" }));
    await user.click(within(gs()).getByRole("button", { name: /发布广告/ }));
    await user.click(within(gs()).getByRole("button", { name: "连接并发布" }));
    expect(await screen.findByRole("heading", { name: /发布广告/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "连接并发布（演示禁用）" })).toBeDisabled();
    expect(screen.getByText("抖音 · 未连接")).toBeInTheDocument();
    expect(screen.getByText("小红书 · 未连接")).toBeInTheDocument();
  });
});
