import type {
  ComposeOptions,
  ComplianceReport,
  GateReport,
  GenerationPath,
  KeyframeState,
  ModelPreflight,
  MotionRealismTier,
  OutputArtifact,
  ProductTemplateId,
  RepairPlan,
  RetakeSymptom,
  SeamMode,
  VideoEstimate,
  VideoMode,
  VideoSegmentState,
  VideoState,
} from "../../features/video/types";
import { apiRequest } from "./client";

export function getVideo(projectId: string): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video`);
}

export function createVideoPlan(
  projectId: string,
  mode: VideoMode,
  templateId: ProductTemplateId | null,
  path?: GenerationPath,
): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video-plan`, {
    method: "POST",
    // path 省略时由服务端 GENERATION_PATH_DEFAULT 决定（保持旧调用方兼容）
    body: JSON.stringify({ mode, template_id: templateId, path }),
  });
}

export function getVideoEstimate(projectId: string, planId: string): Promise<VideoEstimate> {
  return apiRequest<VideoEstimate>(`/api/v1/projects/${projectId}/video-plan/${planId}/estimate`);
}

export function requestVideo(projectId: string): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video`, { method: "POST" });
}

export function requestCompose(projectId: string): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/compose`, { method: "POST" });
}

export function getOutput(projectId: string): Promise<OutputArtifact | null> {
  return apiRequest<OutputArtifact | null>(`/api/v1/projects/${projectId}/output`);
}


export function getVideoSegments(projectId: string): Promise<VideoSegmentState> {
  return apiRequest<VideoSegmentState>(`/api/v1/projects/${projectId}/video/segments`);
}

export function generateSegmentCandidate(projectId: string, segmentId: string, seed?: number): Promise<VideoSegmentState> {
  return apiRequest<VideoSegmentState>(
    `/api/v1/projects/${projectId}/video/segments/${segmentId}/candidates`,
    { method: "POST", body: JSON.stringify(seed === undefined ? {} : { seed }) },
  );
}

export function acceptSegmentCandidate(projectId: string, segmentId: string, candidateId: string): Promise<VideoSegmentState> {
  return apiRequest<VideoSegmentState>(
    `/api/v1/projects/${projectId}/video/segments/${segmentId}/accept`,
    { method: "POST", body: JSON.stringify({ candidate_id: candidateId }) },
  );
}

export function rejectSegment(projectId: string, segmentId: string): Promise<VideoSegmentState> {
  return apiRequest<VideoSegmentState>(
    `/api/v1/projects/${projectId}/video/segments/${segmentId}/reject`,
    { method: "POST" },
  );
}

export function startVideoBatch(projectId: string, stopAfterSegments?: number): Promise<VideoState> {
  // S2 步进：传 1 = 本轮只生成 1 段就返回（保持 running），不传 = 一次跑完（旧行为）
  const query = stopAfterSegments ? `?stop_after_segments=${stopAfterSegments}` : "";
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video/batch${query}`, { method: "POST" });
}

export function stopVideoBatch(projectId: string): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video/batch/stop`, { method: "POST" });
}

// ==================== Phase 0 冻结契约：关键帧 / 交付门 / 合规 ====================
// 说明：写操作（生成关键帧、确认关键帧、症状返修、警告确认）在 Phase 1/2/5 上线前
// 会返回 501 FEATURE_NOT_IMPLEMENTED，调用方应按 ApiError.code 处理。

export function getKeyframes(projectId: string): Promise<KeyframeState> {
  return apiRequest<KeyframeState>(`/api/v1/projects/${projectId}/video/keyframes`);
}

export function generateKeyframeCandidates(
  projectId: string,
  sceneId: string,
  options: { mode?: string; n?: number; seed?: number } = {},
): Promise<KeyframeState> {
  return apiRequest<KeyframeState>(
    `/api/v1/projects/${projectId}/video/keyframes/${sceneId}/candidates`,
    { method: "POST", body: JSON.stringify(options) },
  );
}

export function acceptKeyframe(projectId: string, sceneId: string, keyframeId: string): Promise<KeyframeState> {
  return apiRequest<KeyframeState>(
    `/api/v1/projects/${projectId}/video/keyframes/${sceneId}/accept`,
    { method: "POST", body: JSON.stringify({ keyframe_id: keyframeId }) },
  );
}

export function retakeSegment(projectId: string, segmentId: string, symptom: RetakeSymptom): Promise<VideoSegmentState> {
  return apiRequest<VideoSegmentState>(
    `/api/v1/projects/${projectId}/video/segments/${segmentId}/retake`,
    { method: "POST", body: JSON.stringify({ symptom }) },
  );
}

export function getGateReport(projectId: string): Promise<GateReport> {
  return apiRequest<GateReport>(`/api/v1/projects/${projectId}/video/gate`);
}

export function acknowledgeGateWarnings(projectId: string, checkIds: string[]): Promise<GateReport> {
  return apiRequest<GateReport>(`/api/v1/projects/${projectId}/video/gate/ack`, {
    method: "POST",
    body: JSON.stringify({ check_ids: checkIds }),
  });
}

export function getCompliance(projectId: string): Promise<ComplianceReport> {
  return apiRequest<ComplianceReport>(`/api/v1/projects/${projectId}/compliance`);
}

// ---- S4：导演模式需要的三个只读/免费入口 ----

/** S6 6c：改免费旋钮（真实感档 / 接缝模式）—— 不触发生成、不花钱 */
export function updateVideoPlanSettings(
  projectId: string,
  payload: {
    motion_realism?: MotionRealismTier;
    seam_mode?: SeamMode;
    caption_style?: string | null;
    bgm_enabled?: boolean | null;
    bgm_gain_db?: number | null;
  },
): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video-plan`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** S4-④a：合成旋钮清单（字幕样式 + BGM 取值范围）—— 前端下拉的唯一真源 */
export function getComposeOptions(projectId: string): Promise<ComposeOptions> {
  return apiRequest<ComposeOptions>(`/api/v1/projects/${projectId}/video/compose-options`);
}

/** S6 6d：交付门报告 → 修复动作计划（只读；每个动作由人点，不自动跑） */
export function getVideoRepairs(projectId: string): Promise<RepairPlan> {
  return apiRequest<RepairPlan>(`/api/v1/projects/${projectId}/video/repairs`);
}

/** S6 6e：模型能力预检（只读；不调用任何模型） */
export function getModelPreflight(
  projectId: string,
  options?: { path?: GenerationPath; seamMode?: SeamMode },
): Promise<ModelPreflight> {
  const params = new URLSearchParams();
  if (options?.path) params.set("path", options.path);
  if (options?.seamMode) params.set("seam_mode", options.seamMode);
  const query = params.toString();
  return apiRequest<ModelPreflight>(`/api/v1/projects/${projectId}/video/model-preflight${query ? `?${query}` : ""}`);
}

/** S4-③：段级接缝覆盖（`null` = 清除覆盖、继承方案级）。改它会改该段 kf2v/i2v 条数 → 预估随变。 */
export function setSegmentSeamMode(
  projectId: string,
  segmentId: string,
  seamMode: SeamMode | null,
): Promise<VideoSegmentState> {
  return apiRequest<VideoSegmentState>(`/api/v1/projects/${projectId}/video/segments/${segmentId}/seam`, {
    method: "PATCH",
    body: JSON.stringify({ seam_mode: seamMode }),
  });
}
