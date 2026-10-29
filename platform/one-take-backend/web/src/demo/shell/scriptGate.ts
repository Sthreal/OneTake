/** 工作室审稿步：多角度选稿（切片 B）和花钱前审稿闸（切片 C）。
 *
 * 这里只有纯判断和轮询编排，不渲染。付费视频入口是否放行，以稿上的 review_gate 为准：
 * enforce 且不是 passed，就当成会 409 SCRIPT_REVIEW_REQUIRED。
 */
import type {
  EditScriptInput,
  GenerateScriptInput,
  ReviewGateSummary,
  ScriptReviewResult,
  ScriptState,
  ScriptVersion,
} from "../../features/script/types";
import { readSkuEnrichment, type StudioDraft } from "./model";

export const SCRIPT_ANGLES = ["pain_point", "scene", "comparison"] as const;

export const ANGLE_LABELS: Record<string, string> = {
  pain_point: "痛点种草",
  scene: "场景安利",
  comparison: "对比测评",
};

export const REVIEW_DIMENSIONS = [
  { id: "rhythm", label: "节奏" },
  { id: "spoken", label: "口语" },
  { id: "freshness", label: "新鲜" },
  { id: "structure", label: "结构" },
] as const;

const PENDING_GATE: ReviewGateSummary = {
  mode: "enforce",
  status: "pending",
  decision: null,
  length_ok: null,
  error_code: null,
};

export interface PaidVideoGuard {
  blocked: boolean;
  code: "SCRIPT_REVIEW_REQUIRED" | null;
  message: string;
}

export interface StudioScriptClient {
  getScript: (projectId: string) => Promise<ScriptState>;
  generateScript: (projectId: string, input: GenerateScriptInput) => Promise<ScriptState>;
}

export interface LoadScriptOptions {
  sleep?: (ms: number) => Promise<void>;
  intervalMs?: number;
  maxPolls?: number;
}

const pendingLoads = new Map<string, Promise<ScriptState>>();

export function scriptVersions(state: ScriptState | null | undefined): ScriptVersion[] {
  if (!state) return [];
  if (state.candidates && state.candidates.length > 0) return state.candidates;
  return state.version ? [state.version] : [];
}

export function orderedCandidates(state: ScriptState | null | undefined): ScriptVersion[] {
  return [...scriptVersions(state)].sort((a, b) => {
    const ai = SCRIPT_ANGLES.indexOf((a.angle ?? "") as (typeof SCRIPT_ANGLES)[number]);
    const bi = SCRIPT_ANGLES.indexOf((b.angle ?? "") as (typeof SCRIPT_ANGLES)[number]);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi) || a.version_number - b.version_number;
  });
}

export function angleLabel(version: ScriptVersion): string {
  return version.angle_label || ANGLE_LABELS[version.angle ?? ""] || "口播";
}

/** 创作路径三选一是 PR-3。这里只给审稿文案和软强制用。 */
export type StudioCreationPath = "talking_head" | "product_only" | "multi_angle";

export const ANGLE_PICK_HINT = "请先选择角度";
export const ANGLE_PICK_GUIDE = "先点选一套角度，再审稿确认";

/**
 * 无人 / 纯商品体感用「旁白角度」，有人出镜仍是「口播角度」。
 * 路径条还没做时，用出镜人是否为空来区分，不靠 path。
 */
export function reviewAngleGroupLabel(presenter: { source: string }): "旁白角度" | "口播角度" {
  return presenter.source === "none" ? "旁白角度" : "口播角度";
}

/**
 * 多角度软强制。path 还没进草稿时按多角度处理（审稿三角就是主交互）。
 * talking_head / product_only 允许沿用服务端默认角，不挡确认。
 */
export function explicitAngleRequired(path: StudioCreationPath | null | undefined): boolean {
  if (path == null) return true;
  return path === "multi_angle";
}

/** 同一批候选的身份。没有 batch id 时用版本 id 串起来，换一批就会变。 */
export function angleBatchKey(state: ScriptState | null | undefined): string | null {
  const versions = orderedCandidates(state);
  if (versions.length === 0) return null;
  const batch = versions.find((item) => item.generation_batch_id)?.generation_batch_id;
  if (batch) return batch;
  return versions.map((item) => item.version_id).join("|");
}

export interface AngleConfirmSoftForce {
  blocked: boolean;
  hint: string | null;
}

/**
 * 新一批 ready 之后，服务端默认高亮的角 0 不算用户选过。
 * 点任意角（含已经高亮的角 0）后解除。已确认、还在生成、整批失败都不挡。
 * 只影响确认按钮，不改 confirm / select 接口。
 */
export function angleConfirmSoftForce(input: {
  path?: StudioCreationPath | null;
  batchKey: string | null;
  pickedBatchKey: string | null;
  selectedStatus: string | null | undefined;
  hasSelectableCandidate: boolean;
}): AngleConfirmSoftForce {
  if (!explicitAngleRequired(input.path)) return { blocked: false, hint: null };
  if (input.selectedStatus === "confirmed") return { blocked: false, hint: null };
  if (!input.hasSelectableCandidate) return { blocked: false, hint: null };
  if (input.batchKey && input.pickedBatchKey === input.batchKey) return { blocked: false, hint: null };
  return { blocked: true, hint: ANGLE_PICK_HINT };
}

export function gateSummary(version: ScriptVersion | null | undefined): ReviewGateSummary {
  return version?.review_gate ?? PENDING_GATE;
}

/** enforce 下没到 passed，生成步就要拦住，避免付费入口 409。off / warn 不拦。 */
export function paidVideoBlock(version: ScriptVersion | null | undefined): PaidVideoGuard {
  if (!version) {
    return {
      blocked: true,
      code: "SCRIPT_REVIEW_REQUIRED",
      message: "还没有口播稿。先在审稿步生成三套角度并过闸，再进付费视频。未完成时付费入口会返回 409 SCRIPT_REVIEW_REQUIRED。",
    };
  }
  const gate = gateSummary(version);
  if (gate.mode === "off" || gate.mode === "warn") {
    return { blocked: false, code: null, message: "" };
  }
  if (gate.status === "passed") {
    return { blocked: false, code: null, message: "" };
  }
  if (gate.status === "reviewed") {
    return {
      blocked: true,
      code: "SCRIPT_REVIEW_REQUIRED",
      message: "四维已经审完，但还没过闸。请应用改写或明确保留原稿。未完成时付费视频会返回 409 SCRIPT_REVIEW_REQUIRED。",
    };
  }
  if (gate.status === "failed") {
    return {
      blocked: true,
      code: "SCRIPT_REVIEW_REQUIRED",
      message: "这次审稿没有过闸。等长或审稿失败时不能应用改写，请保留原稿后再进生成。",
    };
  }
  return {
    blocked: true,
    code: "SCRIPT_REVIEW_REQUIRED",
    message: "审稿还没过闸。请先审稿，再应用改写或明确保留原稿。未完成时付费视频会返回 409 SCRIPT_REVIEW_REQUIRED。",
  };
}

export function applyAllowed(input: { gate_status?: string; length_ok?: boolean | null; error_code?: string | null } | null): boolean {
  if (!input) return false;
  return input.gate_status === "reviewed" && input.length_ok === true && !input.error_code;
}

export function ackAllowed(input: { gate_status?: string } | null): boolean {
  if (!input) return false;
  return input.gate_status === "reviewed" || input.gate_status === "failed";
}

export function gateHeadline(gate: ReviewGateSummary): string {
  if (gate.status === "passed") {
    if (gate.decision === "applied") return "审稿闸：已通过（已写入改写）";
    if (gate.decision === "acked") return "审稿闸：已通过（保留原稿）";
    return "审稿闸：已通过";
  }
  if (gate.status === "failed") {
    return gate.error_code === "SCRIPT_REVIEW_LENGTH"
      ? "审稿闸：等长未通过，只能保留原稿"
      : "审稿闸：审稿失败，只能保留原稿";
  }
  if (gate.status === "reviewed") return "审稿闸：已审，还没过闸";
  return "审稿闸：未开始";
}

export function lengthFailureCopy(input: {
  gate_status?: string;
  error_code?: string | null;
  length_errors?: string[];
} | null): string | null {
  if (!input || input.gate_status !== "failed") return null;
  const lengthFail = input.error_code === "SCRIPT_REVIEW_LENGTH" || (input.length_errors?.length ?? 0) > 0;
  if (!lengthFail && input.error_code && input.error_code !== "SCRIPT_REVIEW_LENGTH") {
    return "这次审稿失败，不能应用改写，只能保留原稿。";
  }
  const fields = input.length_errors?.length ? input.length_errors.join("、") : "";
  return fields
    ? `等长未通过（${fields}）。这次改写不能应用，只能保留原稿。`
    : "等长未通过。这次改写不能应用，只能保留原稿。";
}

export function editResetGate(before: ReviewGateSummary, after: ReviewGateSummary): boolean {
  return before.status !== "pending" && after.status === "pending";
}

export function angleSwitchLocked(state: ScriptState | null | undefined): boolean {
  return scriptVersions(state).some((item) => item.status === "confirmed");
}

export function scriptInFlight(state: ScriptState | null | undefined): boolean {
  const versions = scriptVersions(state);
  return versions.length > 0 && versions.some((item) => item.status === "queued" || item.status === "generating");
}

export function scriptFailed(state: ScriptState | null | undefined): boolean {
  const versions = scriptVersions(state);
  return versions.length > 0 && versions.every((item) => item.status === "failed");
}

export function toEditInput(version: ScriptVersion): EditScriptInput {
  return {
    hook: version.hook,
    painPoint: version.pain_point,
    sellingPoints: [...version.selling_points],
    usageScenario: version.usage_scenario,
    cta: version.cta,
  };
}

export function sameEdit(form: EditScriptInput, version: ScriptVersion): boolean {
  const current = toEditInput(version);
  return form.hook === current.hook
    && form.painPoint === current.painPoint
    && form.usageScenario === current.usageScenario
    && form.cta === current.cta
    && form.sellingPoints.join("\n") === current.sellingPoints.join("\n");
}

export function mergeReviewedVersion(state: ScriptState, version: ScriptVersion): ScriptState {
  const existing = scriptVersions(state);
  const found = existing.some((item) => item.version_id === version.version_id);
  const candidates = found
    ? existing.map((item) => (item.version_id === version.version_id ? version : item))
    : [...existing, version];
  return {
    version,
    candidates,
    selected_version_id: version.version_id,
  };
}

export function reviewFacts(review: ScriptReviewResult | null, version: ScriptVersion | null): {
  gate_status: string;
  length_ok: boolean | null;
  error_code: string | null;
  length_errors: string[];
} {
  if (review) {
    return {
      gate_status: review.gate_status,
      length_ok: review.length_ok,
      error_code: review.error_code,
      length_errors: review.length_errors,
    };
  }
  const gate = gateSummary(version);
  return {
    gate_status: gate.status,
    length_ok: gate.length_ok,
    error_code: gate.error_code,
    length_errors: [],
  };
}

export interface PrepareSkuInput {
  /** 传入后，本场覆盖只在 draft.projectId 对得上时生效，避免两件商品串味。 */
  project_id?: string | null;
  product_name: string;
  pain_point?: string | null;
  selling_points?: string[] | null;
  usage_scenario?: string | null;
  offer_default?: string | null;
}

/** 准备步文本：本场覆盖 → 商品草稿。缺了就留空，调用方拦提交，不造假。 */
export function studioScriptInput(sku: PrepareSkuInput, draft: Pick<StudioDraft, "projectId" | "sessionOnly" | "pain_point" | "selling_points" | "usage_scenario" | "offer">): GenerateScriptInput {
  const useOverride = draft.sessionOnly && (sku.project_id == null || draft.projectId === sku.project_id);
  const pain = pickText(useOverride, draft.pain_point, sku.pain_point);
  const scene = pickText(useOverride, draft.usage_scenario, sku.usage_scenario);
  const points = pickPoints(useOverride, draft.selling_points, sku.selling_points);
  return {
    painPoint: clamp(pain, 80),
    sellingPoints: points,
    usageScenario: clamp(scene, 100),
    offer: pickOffer(useOverride, draft.offer, sku.offer_default),
  };
}

export function scriptInputReady(input: GenerateScriptInput): boolean {
  return input.painPoint.trim().length >= 2
    && input.painPoint.trim().length <= 80
    && input.usageScenario.trim().length >= 2
    && input.usageScenario.trim().length <= 100
    && input.sellingPoints.length >= 1
    && input.sellingPoints.length <= 5
    && input.sellingPoints.every((item) => item.trim().length >= 1 && item.trim().length <= 60)
    && (input.offer == null || input.offer.trim().length <= 80);
}

/** 读本机商品草稿再套本场覆盖。商品接口还没有这些字段。 */
export function prepareScriptInput(
  product: { project_id: string; product_name: string },
  draft: StudioDraft,
): GenerateScriptInput {
  const sku = readSkuEnrichment(product.project_id);
  return studioScriptInput({
    project_id: product.project_id,
    product_name: product.product_name,
    pain_point: sku.pain_point,
    selling_points: sku.selling_points,
    usage_scenario: sku.usage_scenario,
    offer_default: sku.offer,
  }, draft);
}

function pickText(useOverride: boolean, override: string | null | undefined, fallback: string | null | undefined): string {
  if (useOverride && override != null) return override;
  return fallback ?? "";
}

function pickPoints(useOverride: boolean, override: string[] | null | undefined, fallback: string[] | null | undefined): string[] {
  const source = useOverride && override != null ? override : (fallback ?? []);
  return source.map((item) => clamp(item, 60)).filter((item) => item.length > 0).slice(0, 5);
}

function pickOffer(useOverride: boolean, override: string | null | undefined, fallback: string | null | undefined): string | null {
  const raw = useOverride && override != null ? override : (fallback ?? "");
  const trimmed = clamp(raw, 80);
  return trimmed ? trimmed : null;
}

function clamp(value: string, max: number): string {
  const trimmed = value.trim();
  return trimmed.length <= max ? trimmed : trimmed.slice(0, max);
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function settleScript(
  state: ScriptState,
  projectId: string,
  api: StudioScriptClient,
  options: LoadScriptOptions | undefined,
): Promise<ScriptState> {
  const sleep = options?.sleep ?? defaultSleep;
  const intervalMs = options?.intervalMs ?? 800;
  const maxPolls = options?.maxPolls ?? 40;
  let current = state;
  let polls = 0;
  while (scriptInFlight(current) && polls < maxPolls) {
    polls += 1;
    await sleep(intervalMs);
    current = await api.getScript(projectId);
  }
  return current;
}

/** 没有稿就 generate 一次；排队中则轮询 GET，直到 ready / failed 或次数用尽。 */
export function loadStudioScript(
  projectId: string,
  input: GenerateScriptInput,
  api: StudioScriptClient,
  options?: LoadScriptOptions,
): Promise<ScriptState> {
  const existing = pendingLoads.get(projectId);
  if (existing) return existing;
  const job = (async () => {
    let state = await api.getScript(projectId);
    if (scriptVersions(state).length === 0) {
      state = await api.generateScript(projectId, input);
    }
    return settleScript(state, projectId, api, options);
  })().finally(() => {
    pendingLoads.delete(projectId);
  });
  pendingLoads.set(projectId, job);
  return job;
}

/** 明确再生成一批。已有 ready 稿时 generate 会另开一批，默认仍是角 0。 */
export function regenerateStudioScript(
  projectId: string,
  input: GenerateScriptInput,
  api: StudioScriptClient,
  options?: LoadScriptOptions,
): Promise<ScriptState> {
  const job = (async () => {
    const state = await api.generateScript(projectId, input);
    return settleScript(state, projectId, api, options);
  })();
  return job;
}
