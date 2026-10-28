import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../shared/api/projectApi", () => ({
  createProject: vi.fn(),
  createProjectFromUrl: vi.fn(),
  updateProject: vi.fn(),
}));
vi.mock("../shared/api/assetApi", () => ({ presignAsset: vi.fn(), completeAsset: vi.fn() }));
vi.mock("../shared/api/recognitionApi", () => ({ getPipeline: vi.fn() }));
vi.mock("./api", () => ({ startAutoRun: vi.fn() }));
vi.mock("../features/input/validation", () => ({ inspectImageFile: vi.fn() }));

import { createProject, createProjectFromUrl } from "../shared/api/projectApi";
import { getPipeline } from "../shared/api/recognitionApi";
import { startAutoRun } from "./api";
import { runProjectIntake } from "./intake";

const logs: string[] = [];
const log = (text: string) => logs.push(text);

describe("共用输入链（小白与导演模式同一份实现）", () => {
  beforeEach(() => {
    vi.clearAllMocks();   // 调用记录要按用例清零，否则跨用例断言会失真
    logs.length = 0;
    vi.mocked(createProjectFromUrl).mockResolvedValue({
      project_id: "prj_1",
      product_name: "测试商品",
      asset_ids: ["ast_1"],
      warning: null,
    } as never);
    vi.mocked(startAutoRun).mockResolvedValue({
      stopped_at: "gate1",
      stopped_reason: null,
    } as never);
    vi.mocked(getPipeline).mockResolvedValue({ status: "audio_subtitle_confirmed" } as never);
  });

  it("链接模式：建项目 → 启动自动链 → 停在闸①前就返回 projectId", async () => {
    const projectId = await runProjectIntake({ mode: "url", productUrl: "https://example.com/p/1" }, { log });
    expect(projectId).toBe("prj_1");
    expect(getPipeline).toHaveBeenCalledWith("prj_1");
    expect(startAutoRun).toHaveBeenCalledWith("prj_1");
    expect(logs.some((line) => line.includes("流水线状态"))).toBe(true);
  });

  it("没给链接 / 没给图 → 明确报错（不静默建个空项目）", async () => {
    await expect(runProjectIntake({ mode: "url", productUrl: "  " }, { log })).rejects.toThrow("请先贴商品链接");
    await expect(runProjectIntake({ mode: "file", file: null }, { log })).rejects.toThrow("请先选一张商品图");
    expect(createProjectFromUrl).not.toHaveBeenCalled();
  });

  it("链接抓不到图（0 张）→ 直接停下、**不启动自动链**（项目已建好要说清楚）", async () => {
    vi.mocked(createProjectFromUrl).mockResolvedValue({
      project_id: "prj_empty",
      product_name: "detail.tmall.com",
      asset_ids: [],
      warning: "页面里没有可用主图，请手动上传",
    } as never);
    await expect(runProjectIntake({ mode: "url", productUrl: "https://detail.tmall.com/x" }, { log })).rejects.toThrow(
      /没抓到可用商品图（项目已建好/,
    );
    expect(startAutoRun).not.toHaveBeenCalled();
    expect(getPipeline).not.toHaveBeenCalled();
  });

  it("等前 4 段时**不再后台重复重推** auto-run（旧实现每 5 秒推一次、上限 20 次）", async () => {
    vi.useFakeTimers();
    try {
      let polls = 0;
      vi.mocked(getPipeline).mockImplementation(async () => {
        polls += 1;
        return { status: polls < 3 ? "assets_ready" : "audio_subtitle_confirmed" } as never;
      });
      const pending = runProjectIntake({ mode: "url", productUrl: "https://example.com/p/1" }, { log });
      await vi.advanceTimersByTimeAsync(20000);
      await expect(pending).resolves.toBe("prj_1");
      expect(polls).toBeGreaterThanOrEqual(3);
      expect(vi.mocked(startAutoRun)).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("链接在**请求前**就被查长度与协议：不让用户拿到「请求失败（422）」这种说不出原因的报错", async () => {
    // 后端对 url 的约束是 1..2048 字符（pydantic）→ 超过就是没有可读原因的 422
    await expect(
      runProjectIntake({ mode: "url", productUrl: "https://example.com/" + "a".repeat(2100) }, { log }),
    ).rejects.toThrow(/链接太长（\d+ 字符，上限 2048）/);
    // 少了协议头 → 后端 SSRF 守卫会拒（这条它有可读原因，但前端先说更省一次往返）
    await expect(
      runProjectIntake({ mode: "url", productUrl: "item.taobao.com/item.htm?id=1" }, { log }),
    ).rejects.toThrow(/http:\/\/ 或 https:\/\/ 开头/);
    expect(createProjectFromUrl).not.toHaveBeenCalled();
  });
});

  it("图片不合格时**先报错、不建项目**（否则会留下没有素材的空项目，界面看着像卡住）", async () => {
    const { inspectImageFile } = await import("../features/input/validation");
    vi.mocked(inspectImageFile).mockRejectedValueOnce(new Error("图片长边不能超过 6000 px"));
    const file = new File([new Uint8Array([1, 2, 3])], "big.jpg", { type: "image/jpeg" });
    await expect(runProjectIntake({ mode: "file", file }, { log })).rejects.toThrow(
      /这张图不能用作商品图：图片长边不能超过 6000 px/,
    );
    expect(createProject).not.toHaveBeenCalled();
  });