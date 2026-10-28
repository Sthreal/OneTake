/** 导演模式的**纯逻辑**（可测）：4 步定义、职能徽章、逐段质量摘要、修复头条。
 *
 * 为什么单独抽出来：这些是"给人看的口径"（标签 / 颜色 / 缺数据怎么说），不是渲染细节 ——
 * 必须有单测钉住；组件只负责摆放。
 */
import type { MotionRealismTier, SeamMode, SegmentQuality } from "../features/video/types";

export const DIRECTOR_STEPS = [
  // 「输入」是导演模式自己的入口（商品图 / 商品链接）—— 导演模式与小白**并存**，
  // 不是"出片"的下游分支：两者只是"全自动"与"可人为干预"的区别。
  { key: "intake", label: "输入", hint: "商品图或商品链接，都行" },
  { key: "storyboard", label: "分镜", hint: "这一版分镜与口播文案" },
  { key: "assets", label: "素材", hint: "每一镜的关键帧" },
  { key: "compose", label: "合成", hint: "逐段出片 + 整片参数" },
  { key: "delivery", label: "交付", hint: "成片与交付门" },
] as const;

export type DirectorStepKey = (typeof DIRECTOR_STEPS)[number]["key"];

/** 镜头职能徽章：按分镜 `purpose`；**未知 purpose 原样显示**（不猜、不吞）。 */
export const PURPOSE_BADGES: Record<string, { label: string; tone: string }> = {
  hook: { label: "钩子", tone: "hook" },
  selling_point: { label: "卖点", tone: "selling" },
  usage_scenario: { label: "演示", tone: "demo" },
  cta: { label: "行动号召", tone: "cta" },
};

export function purposeBadge(purpose: string | null | undefined): { label: string; tone: string } {
  const key = (purpose ?? "").trim();
  return PURPOSE_BADGES[key] ?? { label: key || "分镜", tone: "plain" };
}

export const SEAM_MODE_LABELS: Record<SeamMode, string> = {
  pin: "钉帧（结尾过渡到下一镜关键帧）",
  tail: "续拍（从上一段真实尾帧继续，需按顺序生成）",
  off: "关（各镜独立）",
};

export const REALISM_LABELS: Record<MotionRealismTier, string> = {
  auto: "自动（材质约束 + 物理反馈 + 情绪 + 活背景 + 音效）",
  constraints: "仅约束（材质约束 + 光线锁）",
  off: "关（与本方案之前的历史行为一致）",
};

/** 逐段质量摘要（人话）。缺数据就说"未测" —— **不编数字**。 */
export function qualitySummary(quality?: SegmentQuality | null): string[] {
  if (!quality) return ["质量指标未生成"];
  const parts: string[] = [];
  parts.push(
    quality.product_match === null || quality.product_match === undefined
      ? "商品相似度未测"
      : `商品相似度 ${quality.product_match.toFixed(3)}`,
  );
  parts.push(
    quality.text_intact === null || quality.text_intact === undefined
      ? "文字未测"
      : quality.text_intact
        ? "文字完好"
        : "文字可能受损",
  );
  if (quality.keyframe_fallback) parts.push(`关键帧走后备校正（${quality.keyframe_fallback}）`);
  const delta = quality.duration_delta_seconds;
  if (delta !== null && delta !== undefined && Math.abs(delta) >= 0.5) {
    parts.push(`时长偏差 ${delta > 0 ? "+" : ""}${delta.toFixed(1)}s`);
  }
  if (quality.symptom) parts.push("症状式返修产物");
  return parts;
}

/** 修复计划头条：没有问题时别吓人；有问题时先说"必须处理"几条。
 *
 * 形参刻意收窄成**结构最小集**（只读 level）：调用方拿到的 JSON 只要够看就能传，
 * 不必构造完整的 `RepairAction`（后端字段增删也不影响这里）。
 */
export interface RepairHeadlineInput {
  gate_status: string | null;
  actions: { level: string }[];
}

export function repairHeadline(plan: RepairHeadlineInput | null): string {
  if (!plan || plan.actions.length === 0) return "没有需要处理的问题";
  const fails = plan.actions.filter((item) => item.level === "fail").length;
  const warns = plan.actions.length - fails;
  if (fails > 0) return `${fails} 项必须处理、${warns} 项待确认`;
  return `${warns} 项待确认`;
}

/** 这一步能不能点：只判断"前置有没有"，不做业务判断（业务由后端拦）。 */
export function stepEnabled(step: DirectorStepKey, facts: { hasPlan: boolean; hasSegments: boolean; hasFinal: boolean }): boolean {
  if (step === "intake") return true;   // 输入步永远能进（其它步骤要先有方案）
  if (step === "storyboard") return facts.hasPlan;
  if (step === "assets") return facts.hasPlan;
  if (step === "compose") return facts.hasPlan && facts.hasSegments;
  return facts.hasFinal;
}

/** 每一步底部的"我做完没有 / 下一步点哪"一句话。
 *
 * 为什么要有：用户连着三次卡在"这一步做完了，但页面上没有往下的按钮"（2026-10-16 分镜、素材各一次）。
 * 顶部步骤条虽然能点，但做完事的人不会想到去点标题栏 —— 所以每一步都要**自己说清楚**。
 * 纯函数：只吃数字与布尔，方便单测钉死口径（不编"完成度"）。
 */
export interface StepProgressInput {
  step: DirectorStepKey;
  hasProject: boolean;
  contentPlanStatus: string | null;
  keyframeTotal: number;
  keyframeAccepted: number;
  segmentTotal: number;
  segmentAccepted: number;
  hasOutput: boolean;
}

export function stepProgressHint(input: StepProgressInput): string {
  const { step } = input;
  if (step === "intake") {
    return input.hasProject
      ? "项目已有：点顶部「分镜」继续，或再传一个商品开新项目。"
      : "选一张商品图或贴商品链接，点「开始」——前 4 段自动跑完就停在分镜。";
  }
  if (step === "storyboard") {
    if (input.contentPlanStatus === "confirmed") return "分镜已确认 → 批准费用后就能去素材。";
    if (input.contentPlanStatus === "ready") {
      return "分镜已生成但**还没确认**：点这一页的「确认分镜并批准这笔费用」，会自动建方案、出预估。";
    }
    return "还没有分镜方案：先回「输入」跑完自动链。";
  }
  if (step === "assets") {
    if (input.keyframeTotal === 0) return "还没有可生成的关键帧（先确认分镜）。";
    if (input.keyframeAccepted >= input.keyframeTotal) {
      return `${input.keyframeAccepted}/${input.keyframeTotal} 镜已采纳 → 去「合成」逐段出片。`;
    }
    return `已采纳 ${input.keyframeAccepted}/${input.keyframeTotal} 镜：每镜都要采纳一张（分段出片需要它作首帧），没过的可以「重新生成」。`;
  }
  if (step === "compose") {
    if (input.segmentTotal === 0) return "还没有分段：先回「素材」采纳关键帧。";
    if (input.segmentAccepted >= input.segmentTotal) return "所有分段都已出片 → 去「交付」看成片。";
    return `已出片 ${input.segmentAccepted}/${input.segmentTotal} 段：点「逐段推进一段」，最后一段走完会自动合成。`;
  }
  return input.hasOutput ? "成片已就绪，可直接下载。" : "还没有成片：回「合成」把分段跑完。";
}
/** 分段状态的中文口径（原样显示英文状态 = 用户看不懂，还会以为坏了：2026-10-16）。 */
export const SEGMENT_STATUS_LABELS: Record<string, string> = {
  planned: "待生成",
  generating: "生成中",
  awaiting_review: "待采用",
  accepted: "已采用",
  failed: "失败",
};

/** 未知状态**原样显示**（不猜、不编）。 */
export function segmentStatusLabel(status: string | null | undefined): string {
  const key = (status ?? "").trim();
  if (!key) return "未知";
  return SEGMENT_STATUS_LABELS[key] ?? key;
}

/** 已等待时长（人话）。生成一段真实调用实测 ~72 秒，界面必须让人看得出"在动"。 */
export function formatElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return rest === 0 ? `${minutes} 分` : `${minutes} 分 ${rest} 秒`;
}