import type {
  EditScriptInput,
  GenerateScriptInput,
  ScriptReviewAction,
  ScriptReviewResult,
  ScriptState,
} from "../../features/script/types";
import { apiRequest } from "./client";

export function getScript(projectId: string): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script`);
}

export function generateScript(projectId: string, input: GenerateScriptInput): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script/generate`, {
    method: "POST",
    body: JSON.stringify({
      pain_point: input.painPoint,
      selling_points: input.sellingPoints,
      usage_scenario: input.usageScenario,
      offer: input.offer,
    }),
  });
}

export function editScript(projectId: string, input: EditScriptInput): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script`, {
    method: "PATCH",
    body: JSON.stringify({
      hook: input.hook,
      pain_point: input.painPoint,
      selling_points: input.sellingPoints,
      usage_scenario: input.usageScenario,
      cta: input.cta,
    }),
  });
}

export function confirmScript(projectId: string): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script/confirm`, {
    method: "POST",
  });
}

/** 切片 B：在最近一批候选里改选角度。已确认后再切会 409 SCRIPT_CONFLICT。 */
export function selectScript(projectId: string, versionId: string): Promise<ScriptState> {
  return apiRequest<ScriptState>(`/api/v1/projects/${projectId}/script/select`, {
    method: "POST",
    body: JSON.stringify({ version_id: versionId }),
  });
}

/** 切片 C：对当前 latest 稿跑四维。gate_status=reviewed 只表示审完，还没过闸。 */
export function reviewScriptGate(projectId: string): Promise<ScriptReviewResult> {
  return apiRequest<ScriptReviewResult>(`/api/v1/projects/${projectId}/script/review`, {
    method: "POST",
  });
}

/** apply 写入等长改写；ack 保留原稿。等长失败只能 ack。 */
export function applyScriptReview(projectId: string, action: ScriptReviewAction): Promise<ScriptReviewResult> {
  return apiRequest<ScriptReviewResult>(`/api/v1/projects/${projectId}/script/review/apply`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}
