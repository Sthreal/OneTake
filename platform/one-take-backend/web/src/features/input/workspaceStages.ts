import type { PipelineStatus } from "../recognition/types";

export const WORKSPACE_STAGES = [
  { id: 1, title: "项目与素材", detail: "商品信息与图片" },
  { id: 2, title: "商品识别", detail: "确认商品主体" },
  { id: 3, title: "主图与文案", detail: "处理主图和口播" },
  { id: 4, title: "声音字幕与分镜", detail: "配音、字幕和镜头" },
  { id: 5, title: "视频与成片", detail: "生成预览与下载" },
] as const;

export type WorkspaceStageId = (typeof WORKSPACE_STAGES)[number]["id"];

const VIDEO_STATUSES = new Set<PipelineStatus>([
  "video_plan_ready",
  "video_generating",
  "video_ready",
  "rendering",
  "completed",
]);

export interface WorkspaceStageSignals {
  hasProject: boolean;
  readyAssetCount: number;
  pipelineStatus: PipelineStatus | null;
  currentStep: number | null;
  recognitionStatus: string | null;
  hasMainImage: boolean;
  scriptStatus: string | null;
  hasVoice: boolean;
  hasSubtitle: boolean;
  hasContentPlan: boolean;
  hasVideoPlan: boolean;
}

export function deriveWorkspaceStage(signals: WorkspaceStageSignals): WorkspaceStageId {
  const {
    hasProject,
    readyAssetCount,
    pipelineStatus,
    currentStep,
    recognitionStatus,
    hasMainImage,
    scriptStatus,
    hasVoice,
    hasSubtitle,
    hasContentPlan,
    hasVideoPlan,
  } = signals;

  if (!hasProject) return 1;
  if (hasVideoPlan || (pipelineStatus && VIDEO_STATUSES.has(pipelineStatus))) return 5;
  if (hasContentPlan || hasVoice || hasSubtitle || (currentStep ?? 1) >= 4) return 4;
  if (hasMainImage || scriptStatus || recognitionStatus === "confirmed" || (currentStep ?? 1) >= 3) return 3;
  if (readyAssetCount > 0 || recognitionStatus || (currentStep ?? 1) >= 2) return 2;
  return 1;
}

export function getStageState(
  stageId: WorkspaceStageId,
  activeStage: WorkspaceStageId,
  currentStage: WorkspaceStageId,
) {
  if (stageId === activeStage) return "active" as const;
  // 已经到达过的阶段都保持可点。注意当前阶段也要算 done：只回看更早的阶段时，
  // stageId === currentStage 会落进原来的 locked 分支，导航项被禁用，用户点不回当前阶段。
  if (stageId <= currentStage) return "done" as const;
  return "locked" as const;
}
