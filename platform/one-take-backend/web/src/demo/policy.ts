/** 托管模式的代按策略（对齐文档 §10「用户可见流程与托管模式代按策略」的代码版本）。
 *
 * 为什么单独抽成纯函数：这 5 条规则决定"什么时候系统替用户按确认、什么时候必须打断人"，
 * 是产品口径而不是渲染细节 —— 必须有单测钉住，且阈值要能被"导演模式"显示出来。
 * 阈值与依据见 docs/前端重建方案-核心链路契约与结构.md §10.2。
 */

export const AUTO_APPROVE_POLICY = {
  /** 识别：最高置信度低于此值 → 打断让人选 */
  recognitionConfidenceFloor: 0.6,
  /** 识别：第一名与第二名差值低于此值 → 视为有歧义，打断 */
  recognitionMarginFloor: 0.15,
  /** 配音：|TTS 时长 − 分镜总时长| 超过 max(比例×总时长, 3s) → 打断 */
  subtitleToleranceRatio: 0.3,
  subtitleToleranceSeconds: 3,
  /** 关键帧档的门槛（与后端同口径：网格档 0.52 / 单帧档 0.55） */
  keyframeFloorGrid: 0.52,
  keyframeFloorIntegrated: 0.55,
} as const;

export interface RecognitionCandidateLike {
  candidate_id: string;
  asset_id: string;
  confidence: number;
}

export type Decision<T> =
  | { auto: true; value: T }
  | { auto: false; reason: string };

/** A1：识别确认能不能代按 —— 取置信度最高的候选，但"没候选/太低/太接近"都必须打断。 */
export function pickRecognitionCandidate(
  candidates: RecognitionCandidateLike[],
): Decision<RecognitionCandidateLike> {
  if (candidates.length === 0) {
    return { auto: false, reason: "识别没有返回候选商品，需要你确认用哪张图/哪个主体" };
  }
  const ranked = [...candidates].sort((a, b) => b.confidence - a.confidence);
  const best = ranked[0];
  if (best.confidence < AUTO_APPROVE_POLICY.recognitionConfidenceFloor) {
    return {
      auto: false,
      reason: `识别置信度偏低（${best.confidence.toFixed(2)} < ${AUTO_APPROVE_POLICY.recognitionConfidenceFloor}），需要你确认主体`,
    };
  }
  const runnerUp = ranked[1];
  if (runnerUp && best.confidence - runnerUp.confidence < AUTO_APPROVE_POLICY.recognitionMarginFloor) {
    return { auto: false, reason: "有两个候选置信度接近（有歧义），需要你选一个" };
  }
  return { auto: true, value: best };
}

/** 关键帧档门槛（网格档比单帧档低，因为格子经过裁切+上采样，分数系统性偏低）。 */
export function keyframeFloor(mode: string): number {
  return mode === "grid" ? AUTO_APPROVE_POLICY.keyframeFloorGrid : AUTO_APPROVE_POLICY.keyframeFloorIntegrated;
}

export interface KeyframeCandidateLike {
  keyframe_id: string;
  /** 后端状态：只有 "ready" 能被采纳（accepted/rejected/failed 一律不可采纳） */
  status?: string;
  product_match: number | null;
  text_intact: boolean | null;
  issues: string[];
}

export interface KeyframeSlotLike {
  scene_id: string;
  order: number;
  mode: string;
  candidates: KeyframeCandidateLike[];
}

/** A5：关键帧自动采纳 —— 取该镜**第一个过线**的候选；一镜都没有过线候选就打断（不静默用坏图）。 */
export function pickKeyframeCandidate(
  slot: KeyframeSlotLike,
  mode: string,
): Decision<KeyframeCandidateLike> {
  const floor = keyframeFloor(mode);
  // 只考虑 ready：后端 accept_candidate 明确拒绝非 ready 候选（"该候选未通过质检，不能采用"），
  // 而"生成新候选/采纳别的候选"都会把旧候选置 rejected —— 挑错状态就会无限重生成、永不采纳。
  const ready = slot.candidates.filter((item) => item.status === undefined || item.status === "ready");
  const passing = ready.filter(
    (item) => item.text_intact !== false && (item.product_match ?? 0) >= floor,
  );
  const chosen = passing.length > 0 ? passing[passing.length - 1] : undefined;
  if (!chosen) {
    return {
      auto: false,
      reason: ready.length === 0
        ? `第 ${slot.order} 镜还没有可用的候选（后端 status 必须是 ready），需要重新生成`
        : `第 ${slot.order} 镜没有候选过线（门槛 ${floor}），需要你介入或重生成`,
    };
  }
  return { auto: true, value: chosen };
}

/** A4：配音/字幕能不能代按 —— 时长偏差过大说明字幕会对不上，必须打断。 */
export function voiceSubtitleAutoApprovable(
  durationSeconds: number | null,
  subtitleSegmentCount: number,
  expectedSeconds: number | null,
): Decision<number> {
  if (!durationSeconds || durationSeconds <= 0) {
    return { auto: false, reason: "配音没有产出有效时长，需要你检查（可能是音色或供应商问题）" };
  }
  if (subtitleSegmentCount <= 0) {
    return { auto: false, reason: "字幕分段为空，需要你确认" };
  }
  if (expectedSeconds && expectedSeconds > 0) {
    const tolerance = Math.max(
      expectedSeconds * AUTO_APPROVE_POLICY.subtitleToleranceRatio,
      AUTO_APPROVE_POLICY.subtitleToleranceSeconds,
    );
    const deviation = Math.abs(durationSeconds - expectedSeconds);
    if (deviation > tolerance) {
      return {
        auto: false,
        reason: `配音时长 ${durationSeconds.toFixed(1)}s 与分镜 ${expectedSeconds.toFixed(1)}s 偏差超过 ${tolerance.toFixed(1)}s，字幕会对不上`,
      };
    }
  }
  return { auto: true, value: durationSeconds };
}

export interface GateLike {
  status: string;
  download_allowed: boolean;
  checks: { id: string; level: string; label: string; message: string }[];
}

/** A6：交付门 —— 不代按。只有全部 ok 才算自动过；有 warn 就要一次"已知悉"，fail 阻断下载。 */
export function gateNeedsHuman(gate: GateLike | null): Decision<null> {
  if (!gate) return { auto: false, reason: "还没有交付门结论" };
  const warnings = gate.checks.filter((item) => item.level !== "ok");
  if (gate.status === "fail" || !gate.download_allowed) {
    return { auto: false, reason: "交付门未放行（存在不通过项），修复后才能下载" };
  }
  if (warnings.length > 0) {
    return {
      auto: false,
      reason: `交付门有 ${warnings.length} 条警告需要你逐条确认后才能下载`,
    };
  }
  return { auto: true, value: null };
}

/** 进度清单（对标 ClipForge 的"进度卡"）：按后端 pipeline.status 依次点亮，不靠前端猜测。 */
export const PIPELINE_STEPS = [
  { key: "create", label: "创建项目" },
  { key: "upload", label: "上传商品图" },
  { key: "recognize", label: "识别商品主体" },
  { key: "main_image", label: "主图去背" },
  { key: "script", label: "写口播文案" },
  { key: "voice", label: "配音 + 字幕" },
  { key: "plan", label: "生成分镜方案" },
  { key: "estimate", label: "算清费用" },
] as const;

export type PipelineStepKey = (typeof PIPELINE_STEPS)[number]["key"];

const STATUS_TO_STEP: [RegExp, PipelineStepKey][] = [
  [/^assets_ready$/, "upload"],
  [/^recogniz/, "recognize"],
  [/^(main_image|image_editing|matting)/, "main_image"],
  [/^script/, "script"],
  [/^(voice|subtitle|audio_subtitle)/, "voice"],
  [/^content_plan/, "plan"],
  [/^(content_qa|video_plan|video_generating|video_ready|rendering|completed)/, "estimate"],
];

/** 后端状态 → 当前进行到清单里的哪一项（返回下标；未知状态返回 -1 → 不点亮，如实）。 */
export function stepIndexFromStatus(status: string | null | undefined): number {
  if (!status) return -1;
  for (const [pattern, key] of STATUS_TO_STEP) {
    if (pattern.test(status)) return PIPELINE_STEPS.findIndex((step) => step.key === key);
  }
  return -1;
}

/** 打开一个已存在的项目时，按后端状态决定进哪一屏（"按 project_id 恢复进度"的核心判断）。 */
export type ResumeStage =
  | "done"            // 已成片：直接进成片页（读 /output + 闸③）
  | "review"          // 分镜已就绪 / 已确认：进审核页（文案 + 分镜 + 费用）
  | "poll"            // 前 4 段还在跑：继续轮询等它到闸①
  | "retry"           // 上一次跑失败了：重读方案/费用后即可重试（视频已生成会复用，不重复付费）
  | "unknown";        // 未知状态：如实告知，不猜

export function resumeStageFromStatus(status: string | null | undefined): ResumeStage {
  if (!status) return "unknown";
  // failed / interrupted 不是死路：重读方案与费用后可以直接重试（后端 base 视频幂等复用）
  if (/^(failed|interrupted)$/.test(status)) return "retry";
  if (/^(completed|video_ready|rendering)$/.test(status)) return "done";
  // 前 4 段跑完就停在闸①前（后端不再自动往下走），此时该进审核页让前端触发"生成分镜"。
  // 2026-10-15 实测缺陷：原先 audio_subtitle_confirmed 被归到 "poll" → 前端永远等不到
  // content_plan_* → 一直转圈（用户看到的"卡住"）。
  if (/^(audio_subtitle_confirmed|content_plan_ready|content_plan_confirmed|content_qa_passed|content_qa_failed|video_plan_ready|video_generating)$/.test(status)) {
    return "review";
  }
  if (/^(assets_ready|recogniz|main_image|image_editing|matting|script|voice|subtitle)/.test(status)) {
    return "poll";
  }
  return "unknown";
}

/** 关键帧：**只**判断"这一镜"的候选到齐没（2026-10-15 修的 bug：原先要求所有镜都有候选，
 *  而我们是一镜一镜生成的 → 第 1 镜就永远等不到，页面卡死）。
 *  accepted 非空 = 已采纳；candidates 非空 = 有候选可挑。 */
export function keyframeReadyFor(
  slots: { scene_id: string; accepted: unknown; candidates: { status?: string }[] }[],
  sceneId: string,
): boolean {
  const slot = slots.find((item) => item.scene_id === sceneId);
  if (!slot) return false;
  if (slot.accepted !== null && slot.accepted !== undefined) return true;
  // 必须出现"可采纳"的候选（ready）—— 只有长度 > 0 不够，rejected 的候选挑了也会被后端拒绝
  return slot.candidates.some((item) => item.status === undefined || item.status === "ready");
}

/** 关键帧汇总（成片页「关键帧与九宫格」卡片用）。 */
export interface KeyframeSlotLike2 {
  scene_id: string;
  order: number;
  purpose?: string;
  mode?: string;
  accepted?: { keyframe_id?: string; image_url?: string | null; product_match?: number | null; text_intact?: boolean | null; mode?: string } | null;
}

export interface KeyframeSummary {
  total: number;
  accepted: number;
  averageMatch: number | null;
  /** 有镜的实际生成档位 ≠ 顶层档位 → 说明该镜走了"单帧回退"（网格该格没过线） */
  fellBackScenes: number[];
  /** 顶层档位本身就是单帧（没走九宫格） */
  gridMode: boolean;
}

export function summarizeKeyframes(slots: KeyframeSlotLike2[], mode: string | null | undefined): KeyframeSummary {
  const matches = slots
    .map((slot) => slot.accepted?.product_match)
    .filter((value): value is number => typeof value === "number");
  const fellBackScenes = mode === "grid"
    ? slots.filter((slot) => slot.accepted && slot.accepted.mode && slot.accepted.mode !== "grid").map((slot) => slot.order)
    : [];
  return {
    total: slots.length,
    accepted: slots.filter((slot) => Boolean(slot.accepted)).length,
    averageMatch: matches.length > 0 ? Math.round((matches.reduce((a, b) => a + b, 0) / matches.length) * 1000) / 1000 : null,
    fellBackScenes,
    gridMode: mode === "grid",
  };
}

/** S3：小白模式「一次生成整片」的能力上限 —— 超过就引导去导演模式，**不偷偷拆调用拼接**。
 *
 * 依据是后端硬约束（不是拍脑袋），出处写在 `apps/api`：
 * - `modules/video_plan/one_shot.py` → `MAX_CALL_SECONDS = 15`（单次调用时长上限）
 * - 同文件 → `MAX_MEDIA_ITEMS = 5`，其中首帧占 1 个名额 ⇒ **参考图最多 4 张**（= 4 个分镜关键帧）
 *
 * 为什么不是「自动拆成两次调用再拼」：一次成片的唯一价值是**一次调用**（镜头原生切换、曝光一致、
 * 零接缝）；一旦拆调用，它与逐镜生成相比只剩劣势 —— 所以正解是引导去导演模式（逐镜可控、可单镜重拍）。
 *
 * 文案纪律：**不出现金额**（钱由闸②负责说），也不出现 `one_shot` / `r2v` 这类实现词。
 */
export const ONE_SHOT_LIMITS = { maxSeconds: 15, maxShots: 4 } as const;

export type OneShotLimitReason = "duration-over-limit" | "shots-over-limit";

export interface OneShotEligibility {
  allowed: boolean;
  /** 命中的限制（空数组 = 没命中） */
  reasons: OneShotLimitReason[];
  /** 给人看的一句话；可出片时为空串 */
  message: string;
}

export function oneShotEligibility(input: { durationSeconds: number; shotCount: number }): OneShotEligibility {
  const reasons: OneShotLimitReason[] = [];
  if (input.durationSeconds > ONE_SHOT_LIMITS.maxSeconds) reasons.push("duration-over-limit");
  if (input.shotCount > ONE_SHOT_LIMITS.maxShots) reasons.push("shots-over-limit");
  if (reasons.length === 0) return { allowed: true, reasons, message: "" };

  const parts: string[] = [];
  if (reasons.includes("duration-over-limit")) parts.push(`时长 ${Math.round(input.durationSeconds)} 秒`);
  if (reasons.includes("shots-over-limit")) parts.push(`分镜 ${input.shotCount} 个`);
  return {
    allowed: false,
    reasons,
    message:
      `这条${parts.join("、")}，超过「一次生成整片」的上限（${ONE_SHOT_LIMITS.maxSeconds} 秒 / ` +
      `${ONE_SHOT_LIMITS.maxShots} 个分镜）。硬跑就得拆成多次生成再拼起来，接缝会露。` +
      `要精细控制，进导演模式做这条。`,
  };
}
