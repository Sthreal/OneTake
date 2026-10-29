import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../shared/api/projectApi", () => ({
  listProjects: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
}));
vi.mock("../../shared/api/characterApi", () => ({
  listCharacters: vi.fn(),
}));
vi.mock("../../shared/api/scriptApi", () => ({
  getScript: vi.fn(),
  generateScript: vi.fn(),
  editScript: vi.fn(),
  confirmScript: vi.fn(),
  selectScript: vi.fn(),
  reviewScriptGate: vi.fn(),
  applyScriptReview: vi.fn(),
}));

import type { ScriptReviewResult, ScriptState, ScriptVersion } from "../../features/script/types";
import { ApiError } from "../../shared/api/client";
import { listCharacters } from "../../shared/api/characterApi";
import { listProjects, updateProject } from "../../shared/api/projectApi";
import {
  applyScriptReview,
  confirmScript,
  editScript,
  generateScript,
  getScript,
  reviewScriptGate,
  selectScript,
} from "../../shared/api/scriptApi";
import { StudioShell } from "../StudioShell";
import { DEFAULT_STUDIO_DRAFT, PATH_CHANGED_HINT, PRESENTER_CLEAR_FAILED, TALKING_HEAD_PRESENTER_REQUIRED, writeSkuEnrichment, writeStudioDraft } from "./model";

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

function makeVersion(partial: Partial<ScriptVersion>): ScriptVersion {
  return {
    version_id: "scr_pain",
    project_id: "prj_skin",
    version_number: 1,
    status: "ready",
    provider: "mock",
    model: "mock",
    facts: {
      product_name: "春季护肤精华液 30ml",
      product_note: "主图已就绪",
      pain_point: "轻薄不粘腻、一抹吸收",
      selling_points: ["突出材质与质感"],
      usage_scenario: "主图已就绪",
      offer: null,
    },
    hook: "还在为轻薄不粘腻烦恼？",
    pain_point: "重点看它的实际表现。",
    selling_points: ["突出材质与质感。"],
    usage_scenario: "日常用起来很自然，顺手看看。",
    offer: null,
    cta: "想确认这些特点，现在就进一步看看。",
    full_text: "口播全文",
    character_count: 48,
    estimated_duration_seconds: 12,
    error_code: null,
    created_at: "2026-10-28T00:00:00Z",
    updated_at: "2026-10-28T00:00:00Z",
    completed_at: "2026-10-28T00:00:00Z",
    confirmed_at: null,
    angle: "pain_point",
    angle_label: "痛点种草",
    selected: true,
    generation_batch_id: "sbg_1",
    review_gate: { mode: "enforce", status: "pending", decision: null, length_ok: null, error_code: null },
    ...partial,
  };
}

function installScriptBackend() {
  const pain = makeVersion({ hook: "还在为轻薄不粘腻烦恼？" });
  const scene = makeVersion({
    version_id: "scr_scene",
    version_number: 2,
    angle: "scene",
    angle_label: "场景安利",
    selected: false,
    hook: "出门时怎么还不用这瓶？",
  });
  const comparison = makeVersion({
    version_id: "scr_cmp",
    version_number: 3,
    angle: "comparison",
    angle_label: "对比测评",
    selected: false,
    hook: "别再继续为清洗麻烦烦着？",
  });
  let candidates = [pain, scene, comparison];
  let selectedId = pain.version_id;
  let ready = false;
  let lengthFail = false;

  const current = () => candidates.find((item) => item.version_id === selectedId) ?? candidates[0];
  const snapshot = (): ScriptState => {
    const version = current();
    return {
      version,
      selected_version_id: version.version_id,
      candidates: candidates.map((item) => ({ ...item, selected: item.version_id === version.version_id })),
    };
  };
  const write = (version: ScriptVersion) => {
    candidates = candidates.map((item) => (item.version_id === version.version_id ? version : item));
    selectedId = version.version_id;
  };

  vi.mocked(getScript).mockImplementation(async () => (ready ? snapshot() : { version: null, candidates: [], selected_version_id: null }));
  vi.mocked(generateScript).mockImplementation(async () => {
    ready = true;
    return snapshot();
  });
  vi.mocked(selectScript).mockImplementation(async (_projectId, versionId) => {
    if (candidates.some((item) => item.status === "confirmed")) {
      throw new ApiError("文案已确认，不能再切换角度", { code: "SCRIPT_CONFLICT", status: 409, retryable: true });
    }
    selectedId = versionId;
    return snapshot();
  });
  vi.mocked(reviewScriptGate).mockImplementation(async () => {
    const base = current();
    const gate = {
      mode: "enforce",
      status: lengthFail ? "failed" : "reviewed",
      decision: null,
      length_ok: lengthFail ? false : true,
      error_code: lengthFail ? "SCRIPT_REVIEW_LENGTH" : null,
    };
    const version = { ...base, review_gate: gate };
    write(version);
    const result: ScriptReviewResult = {
      gate_mode: "enforce",
      gate_status: gate.status,
      decision: null,
      dimensions: {
        rhythm: { passed: !lengthFail, reason: lengthFail ? "改写超长" : "ok" },
        spoken: { passed: true, reason: "ok" },
        freshness: { passed: true, reason: "ok" },
        structure: { passed: true, reason: "ok" },
      },
      failed_dimensions: lengthFail ? ["rhythm"] : [],
      revised: {
        hook: lengthFail ? `${base.hook}这段改写故意写得很长` : base.hook,
        pain_point: base.pain_point,
        selling_points: base.selling_points,
        usage_scenario: base.usage_scenario,
        cta: base.cta,
      },
      changed_fields: ["hook"],
      length_ok: !lengthFail,
      length_errors: lengthFail ? ["hook"] : [],
      error_code: gate.error_code,
      blocks_paid_video: true,
      version,
    };
    return result;
  });
  vi.mocked(applyScriptReview).mockImplementation(async (_projectId, action) => {
    const base = current();
    if (action === "apply" && base.review_gate?.status === "failed") {
      throw new ApiError("这次审稿的改写不能应用，请明确保留原稿", { code: "SCRIPT_REVIEW_LENGTH", status: 409, retryable: true });
    }
    const decision = action === "apply" ? "applied" : "acked";
    const version = {
      ...base,
      hook: action === "apply" ? "改写后的钩子，还在说这瓶精华。" : base.hook,
      review_gate: { mode: "enforce", status: "passed", decision, length_ok: true, error_code: null },
    };
    write(version);
    return {
      gate_mode: "enforce",
      gate_status: "passed",
      decision,
      dimensions: {},
      failed_dimensions: [],
      revised: null,
      changed_fields: action === "apply" ? ["hook"] : [],
      length_ok: true,
      length_errors: [],
      error_code: null,
      blocks_paid_video: false,
      version,
    } satisfies ScriptReviewResult;
  });
  vi.mocked(confirmScript).mockImplementation(async () => {
    const base = current();
    if (base.review_gate?.status !== "passed") {
      throw new ApiError("文案确认前需要先完成审稿：应用改写或明确保留原稿", { code: "SCRIPT_REVIEW_REQUIRED", status: 409, retryable: true });
    }
    const version = { ...base, status: "confirmed" as const, confirmed_at: "2026-10-28T02:00:00Z" };
    write(version);
    return snapshot();
  });
  vi.mocked(editScript).mockImplementation(async (_projectId, input) => {
    const base = current();
    const version = {
      ...base,
      hook: input.hook,
      pain_point: input.painPoint,
      selling_points: input.sellingPoints,
      usage_scenario: input.usageScenario,
      cta: input.cta,
      status: "ready" as const,
      confirmed_at: null,
      updated_at: "2026-10-28T03:00:00Z",
      review_gate: { mode: "enforce", status: "pending", decision: null, length_ok: null, error_code: null },
    };
    write(version);
    return snapshot();
  });

  return {
    failLength() {
      lengthFail = true;
    },
  };
}

/** 点已经高亮的角 0。这算显式选择，但不该再打一次 select。 */
async function pickHighlightedAngle(user: ReturnType<typeof userEvent.setup>) {
  const group = await screen.findByRole("group", { name: /旁白角度|口播角度/ });
  await user.click(within(group).getByRole("button", { name: "痛点种草" }));
}

async function choosePath(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  const paths = screen.getByRole("group", { name: "创作路径" });
  await user.click(within(paths).getByRole("button", { name }));
}

async function fillPrepare(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByRole("textbox", { name: "痛点" }), "清洗麻烦");
  await user.type(screen.getByRole("textbox", { name: "卖点 1" }), "杯身可拆");
  await user.type(screen.getByRole("textbox", { name: "使用场景" }), "通勤路上");
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  await user.upload(input, new File([Uint8Array.from([1, 2, 3, 4])], "main.png", { type: "image/png" }));
  const start = screen.getByRole("button", { name: "开始制作" });
  await waitFor(() => expect(start).toBeEnabled());
  await user.click(start);
}

describe("iter18 图片广告与工作室解耦", () => {
  beforeEach(() => {
    open("/");
    installScriptBackend();
    vi.mocked(listProjects).mockResolvedValue([product]);
    vi.mocked(generateScript).mockClear();
    vi.mocked(selectScript).mockClear();
    vi.mocked(confirmScript).mockClear();
    vi.mocked(updateProject).mockReset();
    vi.mocked(updateProject).mockResolvedValue(product);
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
    expect(screen.getByRole("button", { name: "导出预览说明（演示）" }).className).toContain("ot-btn-primary");
    expect(screen.getByRole("button", { name: "可选 · 另开工作室出片" }).className).toContain("ot-btn-secondary");

    await user.click(screen.getByRole("button", { name: "导出预览说明（演示）" }));
    expect(await screen.findByRole("status")).toHaveTextContent("已下载预览说明（不是图片）：白底棚拍");
    expect(screen.getByRole("heading", { name: "图片广告" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "可选 · 另开工作室出片" }));
    expect(await screen.findByRole("heading", { name: "准备" })).toBeInTheDocument();
    expect(screen.getByText(/无需先做图片广告/)).toBeInTheDocument();
  });

  it("准备 → 审稿 → 生成 → 成片可以不打开图片广告", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);

    expect(await screen.findByRole("region", { name: "已选商品" })).toHaveTextContent("春季护肤精华液 30ml");
    expect(screen.getByRole("heading", { name: "准备" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "图片广告" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加商品" })).not.toBeInTheDocument();
    expect(screen.queryByText("突出材质与质感")).not.toBeInTheDocument();
    expect(screen.queryByText("强调敏感肌友好")).not.toBeInTheDocument();
    expect(screen.queryByText("限时促销话术")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更换 →" })).toBeInTheDocument();
    const paths = screen.getByRole("group", { name: "创作路径" });
    expect(within(paths).getAllByRole("button")).toHaveLength(3);
    expect(within(paths).getByRole("button", { name: /纯商品无人/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("本路径不出镜人")).toBeInTheDocument();
    expect(screen.queryByText("林晓")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "从出镜人库更换 →" })).not.toBeInTheDocument();
    expect(document.querySelector(".ot-chips")).toHaveTextContent("纯商品无人");
    expect(screen.getByRole("button", { name: "开始制作" })).toBeDisabled();
    expect(screen.getByText("请至少上传 1 张商品图")).toBeInTheDocument();
    expect(screen.getByText("请填写痛点")).toBeInTheDocument();
    expect(screen.getByText("请至少添加 1 条卖点（最多 5 条）")).toBeInTheDocument();
    expect(screen.getByText("请填写使用场景")).toBeInTheDocument();

    await choosePath(user, /口播出镜/);
    expect(screen.getByText("林晓")).toBeInTheDocument();
    expect(document.querySelector(".ot-chips")).toHaveTextContent("口播出镜");
    expect(document.querySelector(".ot-chips")).not.toHaveTextContent("林晓");

    await user.click(screen.getByRole("button", { name: "从出镜人库更换 →" }));
    const castButtons = within(document.querySelector(".ot-cast") as HTMLElement).getAllByRole("button");
    expect(castButtons[0]).toHaveTextContent("无出镜人");
    expect(castButtons[0]).toHaveTextContent("商品镜头为主，不出现人物");
    expect(screen.getByRole("button", { name: /周予/ })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /提示词|描述出镜人|prompt/ })).not.toBeInTheDocument();

    await choosePath(user, /多角度口播/);
    expect(document.querySelector(".ot-talent")).toHaveTextContent("林晓");
    expect(screen.getByRole("textbox", { name: "痛点" })).toHaveValue("");

    await fillPrepare(user);

    expect(await screen.findByRole("heading", { name: "审稿确认" })).toBeInTheDocument();
    expect(screen.getByText(/无需先做图片广告/)).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "审稿九宫格" })).getAllByRole("listitem")).toHaveLength(9);
    const angles = within(await screen.findByRole("group", { name: "口播角度" })).getAllByRole("button");
    expect(angles.map((item) => item.getAttribute("aria-label"))).toEqual(["痛点种草", "场景安利", "对比测评"]);
    expect(generateScript).toHaveBeenCalledWith("prj_skin", {
      painPoint: "清洗麻烦",
      sellingPoints: ["杯身可拆"],
      usageScenario: "通勤路上",
      offer: null,
    });
    expect(screen.getByRole("button", { name: "痛点种草" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("请先选择角度")).toBeInTheDocument();
    expect(screen.getByText("先点选一套角度，再审稿确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "场景安利" }));
    await waitFor(() => expect(selectScript).toHaveBeenCalledWith("prj_skin", "scr_scene"));
    expect(screen.queryByText("请先选择角度")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "场景安利" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("textbox", { name: "钩子" })).toHaveValue("出门时怎么还不用这瓶？");

    await user.click(screen.getByRole("button", { name: "审稿" }));
    expect(await screen.findByText("审稿闸：已审，还没过闸")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "四维审稿" })).getByText("节奏")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用改写" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "保留原稿" }));
    expect(await screen.findByText("审稿闸：已通过（保留原稿）")).toBeInTheDocument();
    expect(applyScriptReview).toHaveBeenCalledWith("prj_skin", "ack");

    const go = screen.getByRole("button", { name: /确认并生成视频/ });
    await waitFor(() => expect(go).toBeEnabled());
    await user.click(go);
    expect(await screen.findByRole("heading", { name: "编排预览" })).toBeInTheDocument();
    expect(screen.getByText(/不经过图片广告/)).toBeInTheDocument();
    expect(screen.getByText(/不会在这里跑完付费视频/)).toBeInTheDocument();
    await waitFor(() => expect(confirmScript).toHaveBeenCalledTimes(1));
    expect(confirmScript).toHaveBeenCalledWith("prj_skin");
    expect(selectScript).toHaveBeenCalledTimes(1);
    expect(selectScript).toHaveBeenCalledWith("prj_skin", "scr_scene");
    await waitFor(() => expect(screen.getByRole("button", { name: "查看交付说明" })).toBeEnabled());
    expect(screen.getByText(/审稿闸已通过/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "查看交付说明" }));
    expect(await screen.findByRole("heading", { name: "交付说明" })).toBeInTheDocument();
    expect(screen.getByText(/没有经过图片广告/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "图片广告" })).not.toBeInTheDocument();
  });

  it("等长失败不能应用改写，保留原稿后才能进生成", async () => {
    const backend = installScriptBackend();
    backend.failLength();
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    await fillPrepare(user);
    await pickHighlightedAngle(user);
    await user.click(await screen.findByRole("button", { name: "审稿" }));
    expect(await screen.findByText(/等长未通过（hook）/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用改写" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保留原稿" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "保留原稿" }));
    expect(await screen.findByText("审稿闸：已通过（保留原稿）")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeEnabled();
  });

  it("手改文案会清闸，要重新审稿", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    await fillPrepare(user);
    await user.click(await screen.findByRole("button", { name: "审稿" }));
    expect(await screen.findByText("审稿闸：已审，还没过闸")).toBeInTheDocument();
    const hook = screen.getByRole("textbox", { name: "钩子" });
    await user.clear(hook);
    await user.type(hook, "换成一句新的开头。");
    await user.click(screen.getByRole("button", { name: "保存手改" }));
    expect(await screen.findByText("手改文案已清掉审稿闸，需要重新审稿。")).toBeInTheDocument();
    expect(editScript).toHaveBeenCalledWith("prj_skin", expect.objectContaining({ hook: "换成一句新的开头。" }));
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeDisabled();
    expect(screen.getByText("审稿闸：未开始")).toBeInTheDocument();
  });

  it("已确认后再切角度会展示 409，生成步在过闸前拦住", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    await fillPrepare(user);
    await pickHighlightedAngle(user);
    await user.click(await screen.findByRole("button", { name: "审稿" }));
    await screen.findByText("审稿闸：已审，还没过闸");
    await user.click(screen.getByRole("button", { name: "保留原稿" }));
    await screen.findByText("审稿闸：已通过（保留原稿）");
    await user.click(screen.getByRole("button", { name: /确认并生成视频/ }));
    expect(await screen.findByRole("heading", { name: "编排预览" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /审稿确认/ }));
    await user.click(await screen.findByRole("button", { name: "场景安利" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("文案已确认，不能再切换角度");
    expect(screen.getByRole("button", { name: "痛点种草" })).toHaveAttribute("aria-pressed", "true");
  });

  it("直接打开生成步时，未过闸会拦住并送回审稿", async () => {
    const user = userEvent.setup();
    open("/?view=generate&project=prj_skin");
    render(<StudioShell />);
    expect(await screen.findByRole("heading", { name: "编排预览" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("SCRIPT_REVIEW_REQUIRED"));
    expect(screen.getByRole("button", { name: "查看交付说明" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "回到审稿过闸" }));
    expect(await screen.findByRole("heading", { name: "审稿确认" })).toBeInTheDocument();
  });

  it("没有商品时准备步不能从零新建，只能去品牌空间", async () => {
    vi.mocked(listProjects).mockResolvedValue([]);
    open("/?view=prepare");
    render(<StudioShell />);
    expect(await screen.findByRole("heading", { name: "请先在品牌空间选择一件商品" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始制作" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "去品牌空间选商品" })).toBeInTheDocument();
    expect(screen.queryByText("突出材质与质感")).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it("没有 project 不拿库里第一件；无效 id 提示商品已不存在", async () => {
    open("/?view=prepare");
    const first = render(<StudioShell />);
    expect(await screen.findByRole("heading", { name: "请先在品牌空间选择一件商品" })).toBeInTheDocument();
    expect(screen.queryByText("春季护肤精华液 30ml")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始制作" })).toBeDisabled();
    first.unmount();

    open("/?view=prepare&project=missing");
    render(<StudioShell />);
    expect(await screen.findByRole("heading", { name: "商品已不存在，回品牌空间" })).toBeInTheDocument();
    expect(screen.queryByText("春季护肤精华液 30ml")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "去品牌空间选商品" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始制作" })).toBeDisabled();
  });

  it("两件 SKU 的卖点跟着商品走，不串到另一件", async () => {
    const user = userEvent.setup();
    const first = { ...product, project_id: "prj_a", product_name: "甲精华" };
    const second = { ...product, project_id: "prj_b", product_name: "乙水杯" };
    vi.mocked(listProjects).mockResolvedValue([first, second]);
    writeSkuEnrichment("prj_a", {
      pain_point: "甲的痛点",
      selling_points: ["甲的卖点"],
      usage_scenario: "甲的场景",
      specs: "甲规格",
      offer: "",
      images: [],
    });
    writeSkuEnrichment("prj_b", {
      pain_point: "乙的痛点",
      selling_points: ["乙的卖点"],
      usage_scenario: "乙的场景",
      specs: "",
      offer: "",
      images: [],
    });
    open("/?view=prepare&project=prj_a");
    render(<StudioShell />);
    expect(await screen.findByRole("textbox", { name: "痛点" })).toHaveValue("甲的痛点");
    expect(screen.getByRole("textbox", { name: "卖点 1" })).toHaveValue("甲的卖点");
    expect(screen.getByRole("textbox", { name: "规格要点" })).toHaveValue("甲规格");
    expect(screen.queryByDisplayValue("乙的卖点")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "仅用于本次出片" }));
    const pain = screen.getByRole("textbox", { name: "痛点" });
    await user.clear(pain);
    await user.type(pain, "只在这一次");
    await user.click(screen.getByRole("button", { name: "更换 →" }));
    expect(await screen.findByRole("heading", { name: "品牌空间" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /乙水杯/ }));
    expect(await screen.findByRole("textbox", { name: "痛点" })).toHaveValue("乙的痛点");
    expect(screen.getByRole("textbox", { name: "卖点 1" })).toHaveValue("乙的卖点");
    expect(screen.queryByDisplayValue("只在这一次")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("甲的卖点")).not.toBeInTheDocument();
  });

  it("非白名单图片不能上传，开始制作保持禁用", async () => {
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    const input = await screen.findByLabelText("选择商品图片");
    fireEvent.change(input, { target: { files: [new File(["gif"], "anim.gif", { type: "image/gif" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("仅支持 PNG / JPEG / JPG / WEBP");
    expect(screen.getByRole("button", { name: "开始制作" })).toBeDisabled();
    expect(screen.getByText("请至少上传 1 张商品图")).toBeInTheDocument();
  });

  it("已有 ready 稿时，准备步是空的也不会重新 generate", async () => {
    const ready = makeVersion({ hook: "已经写好的钩子" });
    vi.mocked(getScript).mockResolvedValue({
      version: ready,
      candidates: [ready],
      selected_version_id: ready.version_id,
    });
    open("/?view=review&project=prj_skin");
    render(<StudioShell />);
    expect(await screen.findByRole("textbox", { name: "钩子" })).toHaveValue("已经写好的钩子");
    expect(generateScript).not.toHaveBeenCalled();
  });

  it("已有稿后再改准备步卖点不会悄悄重新 generate", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    await fillPrepare(user);
    expect(await screen.findByRole("heading", { name: "审稿确认" })).toBeInTheDocument();
    const generated = vi.mocked(generateScript).mock.calls.length;
    expect(generated).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /准备素材/ }));
    const point = await screen.findByRole("textbox", { name: "卖点 1" });
    await user.clear(point);
    await user.type(point, "换成新卖点");
    await user.click(screen.getByRole("button", { name: "开始制作" }));
    expect(await screen.findByRole("heading", { name: "审稿确认" })).toBeInTheDocument();
    expect(generateScript).toHaveBeenCalledTimes(generated);

    await user.click(screen.getByRole("button", { name: /准备素材/ }));
    expect(await screen.findByRole("textbox", { name: "卖点 1" })).toHaveValue("换成新卖点");
    const beforePath = vi.mocked(generateScript).mock.calls.length;
    await choosePath(user, /口播出镜/);
    expect(await screen.findByText(PATH_CHANGED_HINT)).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "痛点" })).toHaveValue("清洗麻烦");
    expect(screen.getByRole("textbox", { name: "卖点 1" })).toHaveValue("换成新卖点");
    expect(screen.queryByRole("heading", { name: "品牌空间" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "开始制作" }));
    expect(await screen.findByRole("heading", { name: "审稿确认" })).toBeInTheDocument();
    expect(generateScript).toHaveBeenCalledTimes(beforePath);
    expect(screen.getByText(PATH_CHANGED_HINT)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新生成三套口播" })).toBeInTheDocument();
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
    expect(await screen.findByRole("heading", { name: "准备" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "← 首页" }));
    await user.click(within(gs()).getByRole("button", { name: /发布广告/ }));
    await user.click(within(gs()).getByRole("button", { name: "连接并发布" }));
    expect(await screen.findByRole("heading", { name: /发布广告/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "连接并发布（尚未接入）" })).toBeDisabled();
    expect(screen.getByText("抖音 · 未接入")).toBeInTheDocument();
    expect(screen.getByText("小红书 · 未接入")).toBeInTheDocument();
    expect(screen.getByText(/尚未接线/)).toBeInTheDocument();
  });

  it("无出镜人会清空 character_id，审稿生成交付都不展示人才卡", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    expect(await screen.findByRole("group", { name: "创作路径" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /纯商品无人/ })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".ot-talent")).toBeNull();
    expect(document.querySelector(".ot-cast-picked")).toHaveTextContent("本路径不出镜人");
    expect(screen.queryByRole("button", { name: "从出镜人库更换 →" })).not.toBeInTheDocument();

    await fillPrepare(user);
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("prj_skin", { characterId: null }));
    expect(await screen.findByRole("heading", { name: "审稿确认" })).toBeInTheDocument();
    expect(screen.getByText("确认前不扣积分。本场无出镜人 · 口播将以配音/字幕呈现。未过闸不会进入付费生成。")).toBeInTheDocument();
    expect(await screen.findByRole("group", { name: "旁白角度" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "口播角度" })).not.toBeInTheDocument();
    expect(screen.queryByText("林晓")).not.toBeInTheDocument();
    expect(screen.queryByText(/演示数字人|数字人预览/)).not.toBeInTheDocument();

    await pickHighlightedAngle(user);
    await user.click(screen.getByRole("button", { name: "审稿" }));
    expect(await screen.findByText("审稿闸：已审，还没过闸")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "四维审稿" })).getByText("节奏")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保留原稿" }));
    expect(await screen.findByText("审稿闸：已通过（保留原稿）")).toBeInTheDocument();
    expect(applyScriptReview).toHaveBeenCalledWith("prj_skin", "ack");
    await user.click(screen.getByRole("button", { name: /确认并生成视频/ }));

    expect(await screen.findByRole("heading", { name: "编排预览" })).toBeInTheDocument();
    expect(screen.getByText("出镜：无（纯商品）")).toBeInTheDocument();
    expect(document.querySelector(".ot-talent")).toBeNull();
    expect(screen.queryByText(/演示数字人|数字人预览/)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "查看交付说明" })).toBeEnabled());
    expect(screen.getByText(/审稿闸已通过/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看交付说明" }));

    expect(await screen.findByRole("heading", { name: "交付说明" })).toBeInTheDocument();
    expect(screen.getByText("纯商品镜头 · 无人出镜")).toBeInTheDocument();
    expect(screen.queryByText("林晓")).not.toBeInTheDocument();
    expect(document.querySelector(".ot-talent")).toBeNull();
    expect(screen.queryByText(/演示数字人|数字人预览/)).not.toBeInTheDocument();
  });

  it("清空出镜人失败时停在准备步，不会改用预制人", async () => {
    vi.mocked(updateProject).mockRejectedValueOnce(new Error("network"));
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    expect(await screen.findByText("本路径不出镜人")).toBeInTheDocument();
    await fillPrepare(user);
    expect(await screen.findByRole("alert")).toHaveTextContent(PRESENTER_CLEAR_FAILED);
    expect(screen.getByRole("heading", { name: "准备" })).toBeInTheDocument();
    expect(document.querySelector(".ot-cast-picked")).toHaveTextContent("本路径不出镜人");
    expect(screen.queryByText("出镜人：林晓")).not.toBeInTheDocument();
  });

  it("直接打开生成步时，无人仍清空 character_id，失败则拦住且不注入预制人", async () => {
    writeStudioDraft({ ...DEFAULT_STUDIO_DRAFT, projectId: "prj_skin", presenterId: null });
    vi.mocked(updateProject).mockRejectedValueOnce(new Error("network"));
    open("/?view=generate&project=prj_skin");
    render(<StudioShell />);
    expect(await screen.findByRole("heading", { name: "编排预览" })).toBeInTheDocument();
    expect(screen.getByText("出镜：无（纯商品）")).toBeInTheDocument();
    expect(await screen.findByText(PRESENTER_CLEAR_FAILED)).toBeInTheDocument();
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("prj_skin", { characterId: null }));
    expect(screen.getByRole("button", { name: "查看交付说明" })).toBeDisabled();
    expect(screen.queryByText("林晓")).not.toBeInTheDocument();
    expect(document.querySelector(".ot-talent")).toBeNull();
    expect(await screen.findByText(/SCRIPT_REVIEW_REQUIRED/)).toBeInTheDocument();
  });

  it("本场草稿 v2 覆盖和无人出镜仍按 studioScriptInput 出稿，默认角要点过才确认", async () => {
    writeSkuEnrichment("prj_skin", {
      pain_point: "库里的痛点",
      selling_points: ["库里的卖点"],
      usage_scenario: "库里的场景",
      specs: "规格",
      offer: "库里的优惠",
      images: [],
    });
    writeStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      projectId: "prj_skin",
      path: "multi_angle",
      presenterId: null,
      sessionOnly: true,
      pain_point: "本次痛点",
      selling_points: ["本次卖点"],
      usage_scenario: "本次场景",
      offer: "本次优惠",
    });
    const user = userEvent.setup();
    open("/?view=review&project=prj_skin");
    render(<StudioShell />);

    expect(await screen.findByRole("group", { name: "旁白角度" })).toBeInTheDocument();
    await waitFor(() => expect(generateScript).toHaveBeenCalledWith("prj_skin", {
      painPoint: "本次痛点",
      sellingPoints: ["本次卖点"],
      usageScenario: "本次场景",
      offer: "本次优惠",
    }));
    expect(screen.getByRole("button", { name: "痛点种草" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("请先选择角度")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "审稿" }));
    expect(await screen.findByText("审稿闸：已审，还没过闸")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保留原稿" }));
    expect(await screen.findByText("审稿闸：已通过（保留原稿）")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeDisabled();
    expect(screen.getByText("请先选择角度")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "痛点种草" }));
    expect(selectScript).not.toHaveBeenCalled();
    expect(screen.queryByText("请先选择角度")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "钩子" })).toHaveValue("还在为轻薄不粘腻烦恼？");

    await user.click(screen.getByRole("button", { name: "场景安利" }));
    await waitFor(() => expect(selectScript).toHaveBeenCalledTimes(1));
    expect(selectScript).toHaveBeenCalledWith("prj_skin", "scr_scene");
    expect(screen.getByRole("textbox", { name: "钩子" })).toHaveValue("出门时怎么还不用这瓶？");
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "审稿" }));
    expect(await screen.findByText("审稿闸：已审，还没过闸")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保留原稿" }));
    const go = screen.getByRole("button", { name: /确认并生成视频/ });
    await waitFor(() => expect(go).toBeEnabled());
    await user.click(go);
    await waitFor(() => expect(confirmScript).toHaveBeenCalledTimes(1));
    expect(confirmScript).toHaveBeenCalledWith("prj_skin");
    expect(selectScript).toHaveBeenCalledTimes(1);
  });

  it("重新生成一批后，默认角高亮仍要再点一次", async () => {
    writeSkuEnrichment("prj_skin", {
      pain_point: "清洗麻烦",
      selling_points: ["杯身可拆"],
      usage_scenario: "通勤路上",
      specs: "",
      offer: "",
      images: [],
    });
    const failed = makeVersion({ status: "failed", hook: "", generation_batch_id: "sbg_fail" });
    vi.mocked(getScript).mockResolvedValue({
      version: failed,
      candidates: [
        failed,
        makeVersion({ version_id: "scr_scene", angle: "scene", angle_label: "场景安利", status: "failed", selected: false, generation_batch_id: "sbg_fail" }),
        makeVersion({ version_id: "scr_cmp", angle: "comparison", angle_label: "对比测评", status: "failed", selected: false, generation_batch_id: "sbg_fail" }),
      ],
      selected_version_id: failed.version_id,
    });
    vi.mocked(generateScript).mockImplementation(async () => {
      const pain = makeVersion({ generation_batch_id: "sbg_fail", hook: "新的一批仍是默认角" });
      const scene = makeVersion({
        version_id: "scr_scene",
        angle: "scene",
        angle_label: "场景安利",
        selected: false,
        generation_batch_id: "sbg_fail",
        hook: "出门时怎么还不用这瓶？",
      });
      const comparison = makeVersion({
        version_id: "scr_cmp",
        angle: "comparison",
        angle_label: "对比测评",
        selected: false,
        generation_batch_id: "sbg_fail",
      });
      return { version: pain, candidates: [pain, scene, comparison], selected_version_id: pain.version_id };
    });
    writeStudioDraft({
      ...DEFAULT_STUDIO_DRAFT,
      projectId: "prj_skin",
      path: "multi_angle",
      presenterId: "premade:linxiao",
    });
    const user = userEvent.setup();
    open("/?view=review&project=prj_skin");
    render(<StudioShell />);

    await user.click(await screen.findByRole("button", { name: "痛点种草" }));
    expect(selectScript).not.toHaveBeenCalled();
    expect(screen.queryByText("请先选择角度")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新生成三套口播" }));
    expect(await screen.findByText("请先选择角度")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "痛点种草" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeDisabled();
    expect(screen.getByRole("group", { name: "口播角度" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "钩子" })).toHaveValue("新的一批仍是默认角");
  });

  it("纯商品无人：默认路径不出镜，审稿用旁白角度且不软强制", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    const paths = await screen.findByRole("group", { name: "创作路径" });
    expect(within(paths).getAllByRole("button")).toHaveLength(3);
    expect(within(paths).getByRole("button", { name: /纯商品无人/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(paths).getByRole("button", { name: /口播出镜/ })).toHaveAttribute("aria-pressed", "false");
    expect(within(paths).getByRole("button", { name: /多角度口播/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("同一商品信息，选不同成片方式 · 不增加费用")).toBeInTheDocument();
    expect(screen.getByText("本路径不出镜人")).toBeInTheDocument();
    expect(document.querySelector(".ot-talent")).toBeNull();
    expect(screen.queryByText("林晓")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /音色|提示词|描述出镜人/ })).not.toBeInTheDocument();
    expect(document.querySelector(".ot-chips")).toHaveTextContent("纯商品无人");

    const pain = screen.getByRole("textbox", { name: "痛点" });
    await user.type(pain, "清洗麻烦");
    await choosePath(user, /多角度口播/);
    await choosePath(user, /纯商品无人/);
    expect(pain).toHaveValue("清洗麻烦");
    expect(screen.queryByRole("heading", { name: "品牌空间" })).not.toBeInTheDocument();
    expect(document.querySelector(".ot-talent")).toBeNull();

    await fillPrepare(user);
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("prj_skin", { characterId: null }));
    expect(await screen.findByRole("group", { name: "旁白角度" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "口播角度" })).not.toBeInTheDocument();
    expect(screen.queryByText("请先选择角度")).not.toBeInTheDocument();
    expect(screen.queryByText("先点选一套角度，再审稿确认")).not.toBeInTheDocument();
    expect(screen.queryByText("林晓")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "场景安利" }));
    await waitFor(() => expect(selectScript).toHaveBeenCalledWith("prj_skin", "scr_scene"));
    expect(generateScript).toHaveBeenCalledTimes(1);
  });

  it("口播出镜：无人不能开始，预填预制人后可以，审稿不软强制", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    await screen.findByRole("group", { name: "创作路径" });
    await choosePath(user, /口播出镜/);
    expect(document.querySelector(".ot-talent")).toHaveTextContent("林晓");
    expect(document.querySelector(".ot-chips")).toHaveTextContent("口播出镜");
    expect(screen.queryByText("本路径不出镜人")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "从出镜人库更换 →" }));
    await user.click(screen.getByRole("button", { name: /无出镜人/ }));
    expect(screen.getByText(TALKING_HEAD_PRESENTER_REQUIRED)).toBeInTheDocument();
    expect(document.querySelector(".ot-talent")).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "痛点" }), "清洗麻烦");
    await user.type(screen.getByRole("textbox", { name: "卖点 1" }), "杯身可拆");
    await user.type(screen.getByRole("textbox", { name: "使用场景" }), "通勤路上");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File([Uint8Array.from([1, 2, 3])], "main.png", { type: "image/png" }));
    expect(screen.getByRole("button", { name: "开始制作" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /周予/ }));
    const start = screen.getByRole("button", { name: "开始制作" });
    await waitFor(() => expect(start).toBeEnabled());
    await user.click(start);
    expect(await screen.findByRole("group", { name: "口播角度" })).toBeInTheDocument();
    expect(screen.queryByText("请先选择角度")).not.toBeInTheDocument();
    expect(screen.queryByText("先点选一套角度，再审稿确认")).not.toBeInTheDocument();
    expect(screen.getByText(/配音人 周予/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeDisabled();
    expect(screen.queryByRole("textbox", { name: /音色/ })).not.toBeInTheDocument();
  });

  it("多角度口播：无人也能开始，选角是主交互", async () => {
    const user = userEvent.setup();
    open("/?view=prepare&project=prj_skin");
    render(<StudioShell />);
    await screen.findByRole("group", { name: "创作路径" });
    await choosePath(user, /多角度口播/);
    expect(screen.getByRole("button", { name: /多角度口播/ })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".ot-cast-picked")).toHaveTextContent("无出镜人");
    expect(document.querySelector(".ot-talent")).toBeNull();
    expect(screen.queryByText("林晓")).not.toBeInTheDocument();
    expect(document.querySelector(".ot-chips")).toHaveTextContent("多角度口播");
    expect(screen.queryByText(TALKING_HEAD_PRESENTER_REQUIRED)).not.toBeInTheDocument();

    await fillPrepare(user);
    expect(await screen.findByRole("group", { name: "旁白角度" })).toBeInTheDocument();
    expect(screen.getByText("请先选择角度")).toBeInTheDocument();
    expect(screen.getByText("先点选一套角度，再审稿确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认并生成视频/ })).toBeDisabled();
    expect(screen.getByText(/本场无出镜人/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "痛点种草" }));
    expect(selectScript).not.toHaveBeenCalled();
    expect(screen.queryByText("请先选择角度")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "对比测评" }));
    await waitFor(() => expect(selectScript).toHaveBeenCalledWith("prj_skin", "scr_cmp"));
  });
});
