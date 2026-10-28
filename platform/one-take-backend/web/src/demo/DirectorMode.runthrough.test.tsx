import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// 「导演模式能跑通」的守卫：闸①（确认分镜）→ 建方案 → 预估 → 闸②（批准费用）必须真的按序发生。
// 全部接口打桩；这里只验编排，不碰网络。
const calls: string[] = [];
const confirmedPlan = {
  plan_id: "cpl_1",
  project_id: "prj_x",
  status: "confirmed",
  provider: "rules",
  model: "rules-v1",
  selected_variant_index: 0,
  total_duration_seconds: 14,
  variants: [
    {
      variant_id: "var_1",
      name: "标准",
      style: "clean",
      scenes: [
        {
          scene_id: "scene_1", order: 1, purpose: "hook", script_excerpt: "文案", start_seconds: 0,
          end_seconds: 3, shot_type: "product_reveal", prompt: "x", overlay_product: true,
          product_position: "center", background_style: "clean", template_id: "clean",
          subtitle_segment_ids: [1], qa_rules: [], visual_goal: "product_reveal",
          subject_action: "展示", camera_move: "slow_push_in", product_mode: "overlay", transition: "fade",
        },
      ],
    },
  ],
  error_code: null,
  created_at: "2026-10-15T00:00:00Z",
  updated_at: "2026-10-15T00:00:00Z",
  confirmed_at: "2026-10-15T00:00:00Z",
};

vi.mock("../shared/api/contentPlanApi", () => ({
  getContentPlan: vi.fn(async () => confirmedPlan),
  confirmContentPlan: vi.fn(async () => {
    calls.push("confirmContentPlan");
    return confirmedPlan;
  }),
  getContentPlanOptions: vi.fn(async () => ({ camera_moves: [] })),
  generateContentPlan: vi.fn(async () => confirmedPlan),
  updateSceneCamera: vi.fn(async () => confirmedPlan),
}));
vi.mock("./api", () => ({
  approveCost: vi.fn(async () => {
    calls.push("approveCost");
    return { plan_id: "vid_1", is_paid: false, estimated_cny: 7.31, payload_hash: "h", approved_by: "director-mode" };
  }),
  startAutoRun: vi.fn(),
}));
vi.mock("../shared/api/videoApi", () => ({
  getVideo: vi.fn(async () => ({ plan: null })),          // 还没有视频方案 → 费用卡应当自动建一个
  createVideoPlan: vi.fn(async () => {
    calls.push("createVideoPlan");
    return { plan: { plan_id: "vid_1", project_id: "prj_x", path: "segmented" } };
  }),
  getVideoEstimate: vi.fn(async () => {
    calls.push("getVideoEstimate");
    return {
      plan_id: "vid_1", duration_seconds: 14, estimated_known_cost: 7.31, estimated_cost_max: 9.31,
      missing_price_config: [], price_notes: ["分段：i2v 1 次、kf2v 3 次"], path: "segmented",
    };
  }),
  getVideoSegments: vi.fn(async () => ({ plan_id: null, segments: [] })),
  getOutput: vi.fn(async () => null),
  getGateReport: vi.fn(async () => null),
  getVideoRepairs: vi.fn(async () => null),
  getModelPreflight: vi.fn(async () => null),
  getComposeOptions: vi.fn(async () => null),
  acceptKeyframe: vi.fn(async () => {
    calls.push("acceptKeyframe");
    return { mode: "integrated", generation_available: true, candidates_per_call: 2, keyframes: [] };
  }),
  generateKeyframeCandidates: vi.fn(),
  getKeyframes: vi.fn(async () => ({ mode: "integrated", generation_available: false, candidates_per_call: 2, keyframes: [] })),
  retakeSegment: vi.fn(),
  setSegmentSeamMode: vi.fn(),
  startVideoBatch: vi.fn(),
  updateVideoPlanSettings: vi.fn(),
}));
vi.mock("../shared/api/projectApi", () => ({
  listProjects: vi.fn(async () => []),
  createProject: vi.fn(),
  createProjectFromUrl: vi.fn(),
  updateProject: vi.fn(),
}));

import * as contentPlanApi from "../shared/api/contentPlanApi";
import * as videoApi from "../shared/api/videoApi";
import { DirectorMode } from "./DirectorMode";

describe("导演模式能否跑通（闸① + 闸② 编排）", () => {
  beforeEach(() => {
    calls.length = 0;
    window.history.replaceState(null, "", "/?view=director&project=prj_x&step=storyboard");
    vi.mocked(contentPlanApi.getContentPlan).mockResolvedValue({ ...confirmedPlan, status: "confirmed" } as never);
  });

  it("新项目刚跑完自动链（分镜 = ready、还没视频方案）也必须**有按钮能往下走**", async () => {
    // 复现用户实测的死路（2026-10-16「到分镜卡住、没有往下的提示和按钮」）：
    // 分镜 ready → 方案未建 → 预估为空；旧实现按钮只在"有预估"那支里 → 整页无处可点。
    vi.mocked(contentPlanApi.getContentPlan).mockResolvedValue({ ...confirmedPlan, status: "ready" } as never);
    (videoApi.getVideo as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({ plan: null });
    render(<DirectorMode projectId="prj_x" />);

    const button = await screen.findByRole("button", { name: /确认分镜并批准这笔费用/ });
    expect(button).toBeEnabled();
    expect(screen.getByText(/还没有费用预估/)).toBeInTheDocument();
    // 还没点，不该偷偷花钱
    expect(calls).not.toContain("approveCost");

    fireEvent.click(button);
    await waitFor(() => expect(calls).toContain("approveCost"));
    // 顺序：闸① 确认分镜 → 建方案（免费）→ 取预估 → 闸② 批准
    expect(calls.indexOf("confirmContentPlan")).toBeLessThan(calls.indexOf("createVideoPlan"));
    expect(calls.indexOf("createVideoPlan")).toBeLessThan(calls.indexOf("getVideoEstimate"));
    expect(calls.indexOf("getVideoEstimate")).toBeLessThan(calls.indexOf("approveCost"));
  });

  it("进入分镜步会自动建方案并取预估，费用可见", async () => {
    render(<DirectorMode projectId="prj_x" />);
    expect(await screen.findByText(/预估费用：/)).toBeInTheDocument();
    expect(screen.getByText(/7.31/)).toBeInTheDocument();
    expect(calls).toContain("createVideoPlan");
    expect(calls).toContain("getVideoEstimate");
  });

  it("素材步不过线时不堵死人：低分候选不会静默采用，但可以人手动采用某一张", async () => {
    // 两个候选：一个低于门槛(0.55)的 ready、一个失败态 —— 自动挑必须拒绝，界面必须给出手动入口
    (videoApi.getKeyframes as unknown as { mockImplementation: (f: () => Promise<unknown>) => void }).mockImplementation(async () => ({
      mode: "integrated", generation_available: true, candidates_per_call: 2,
      keyframes: [{
        scene_id: "scene_1", order: 1, purpose: "hook", visual_goal: "product_reveal", mode: "integrated",
        prompt_warning: null, accepted: null,
        candidates: [
          { keyframe_id: "kfc_low", scene_id: "scene_1", mode: "integrated", status: "ready", image_url: "blob:low", product_match: 0.41, text_intact: true, issues: [] },
          { keyframe_id: "kfc_bad", scene_id: "scene_1", mode: "integrated", status: "failed", image_url: null, product_match: null, text_intact: null, issues: ["x"] },
        ],
      }],
    }));
    window.history.replaceState(null, "", "/?view=director&project=prj_x&step=assets");
    render(<DirectorMode projectId="prj_x" />);

    // 自动挑：明确拒绝 + 说清原因（不静默采用低分图）
    const auto = await screen.findByRole("button", { name: "采用过线候选" });
    fireEvent.click(auto);
    expect(await screen.findByText(/没有候选过线/)).toBeInTheDocument();
    expect(calls).not.toContain("acceptKeyframe");

    // 手动：低分候选也能采用（门槛是给人看的建议，不是替人做决定）
    expect(screen.getByText(/低于门槛 0.55/)).toBeInTheDocument();
    const manual = screen.getByRole("button", { name: "采用这张" });
    expect(manual).toBeEnabled();
    fireEvent.click(manual);
    await waitFor(() => expect(calls).toContain("acceptKeyframe"));
    expect((videoApi.acceptKeyframe as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][2]).toBe("kfc_low");
    // 失败态候选不给点（后端会拒，界面先拦）
    expect(screen.getByRole("button", { name: "failed" })).toBeDisabled();
  });

  it("每一步底部都有「下一步 / 上一步」：素材步做完能直接点去合成（用户实测三次卡在没按钮）", async () => {
    window.history.replaceState(null, "", "/?view=director&project=prj_x&step=assets");
    vi.mocked(videoApi.getVideo).mockResolvedValue({ plan: { plan_id: "vid_1" } } as never);
    (videoApi.getVideoSegments as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({
      plan_id: "vid_1",
      segments: [0, 1, 2, 3].map((order) => ({
        segment_id: `seg_${order}`, plan_id: "vid_1", order_index: order, scene_id: `scene_${order}`,
        start_seconds: 0, end_seconds: 3, duration_seconds: 3, status: "planned",
        accepted_candidate_id: null, last_error: null, anchor_source: null, candidates: [],
      })),
    });
    (videoApi.getKeyframes as unknown as { mockImplementation: (f: () => Promise<unknown>) => void }).mockImplementation(async () => ({
      mode: "integrated", generation_available: true, candidates_per_call: 2,
      keyframes: [1, 2, 3, 4].map((order) => ({
        scene_id: `scene_${order}`, order, purpose: "hook", visual_goal: "x", mode: "integrated",
        prompt_warning: null,
        accepted: {
          keyframe_id: `kfc_${order}`, scene_id: `scene_${order}`, mode: "integrated", status: "accepted",
          image_url: "blob:x", product_match: 0.6, text_intact: true, issues: [],
        },
        candidates: [],
      })),
    }));

    render(<DirectorMode projectId="prj_x" />);
    // 卡片头给出进度、底部导航给出"下一步去哪"（两处都出现，所以用 getAllByText）
    await waitFor(() => expect(screen.getAllByText(/4\/4 镜已采纳/).length).toBeGreaterThanOrEqual(2));
    expect(screen.getByText(/→ 去「合成」逐段出片/)).toBeInTheDocument();

    const next = screen.getByRole("button", { name: /下一步（合成）/ });
    expect(next).toBeEnabled();
    fireEvent.click(next);
    await waitFor(() => expect(window.location.search).toContain("step=compose"));
  });

  it("逐段推进在生成当中：必须显示「生成中」与等待时长（用户实测：看不到状态以为坏了）", async () => {
    window.history.replaceState(null, "", "/?view=director&project=prj_x&step=compose");
    vi.mocked(videoApi.getVideo).mockResolvedValue({ plan: { plan_id: "vid_1" } } as never);
    (videoApi.getVideoSegments as unknown as { mockResolvedValue: (v: unknown) => void }).mockResolvedValue({
      plan_id: "vid_1",
      // order_index 是 1 基（与后端一致）——测试里也别用 0 基，否则界面会显示"第 0 段"
      segments: [1, 2, 3, 4].map((order) => ({
        segment_id: `seg_${order}`, plan_id: "vid_1", order_index: order, scene_id: `scene_${order}`,
        start_seconds: 0, end_seconds: 3, duration_seconds: 3, status: "planned",
        accepted_candidate_id: null, last_error: null, anchor_source: null, candidates: [],
      })),
    });
    // 真实调用是几十秒的：这里用一个"不 resolve"的 promise 把中间态钉住
    const gate: { release?: (value: unknown) => void } = {};
    (videoApi.startVideoBatch as unknown as { mockImplementation: (f: () => Promise<unknown>) => void }).mockImplementation(
      () => new Promise((resolve) => { gate.release = resolve as (value: unknown) => void; }),
    );

    render(<DirectorMode projectId="prj_x" />);
    const click = await screen.findByRole("button", { name: "逐段推进一段" });
    fireEvent.click(click);

    // ① 顶部横幅：说清在干什么 + 不是立刻返回（用括号里的长文案定位，避免和按钮文案撞名）
    expect(await screen.findByText(/正在生成第 1 段（真实调用/)).toBeInTheDocument();
    expect(screen.getByText(/已等待 0 秒/)).toBeInTheDocument();
    // ② 那一段自己的状态必须变成「生成中」（不是英文 planned）
    await waitFor(() => expect(screen.getAllByText("生成中").length).toBeGreaterThan(0));
    // ③ 按钮自己也说明白，避免"点了没反应"
    expect(screen.getByRole("button", { name: /正在生成第 1 段…/ })).toBeDisabled();

    gate.release?.({ plan: {} });
    await waitFor(() => expect(screen.queryByText(/正在生成第 1 段（真实调用/)).not.toBeInTheDocument());
  });

  it("点「确认分镜并批准这笔费用」→ 闸① 与 闸② 按序发生（这是跑通的关键）", async () => {
    render(<DirectorMode projectId="prj_x" />);
    const button = await screen.findByRole("button", { name: /确认分镜并批准这笔费用/ });
    fireEvent.click(button);
    await waitFor(() => expect(calls).toContain("approveCost"));
    // 顺序：先确认分镜（闸①），再批准费用（闸②）
    expect(calls.indexOf("confirmContentPlan")).toBeLessThan(calls.indexOf("approveCost"));
  });
});
