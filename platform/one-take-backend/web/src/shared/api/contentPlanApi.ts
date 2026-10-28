import type { ContentPlan, ContentPlanOptions, ContentScene } from "../../features/content-plan/types";
import { apiRequest } from "./client";

export function getContentPlan(projectId: string): Promise<ContentPlan | null> {
  return apiRequest<ContentPlan | null>(`/api/v1/projects/${projectId}/content-plan`);
}

export function generateContentPlan(projectId: string): Promise<ContentPlan> {
  return apiRequest<ContentPlan>(`/api/v1/projects/${projectId}/content-plan`, { method: "POST" });
}

export function updateContentPlan(
  projectId: string,
  selectedVariantIndex: number,
  scenes: ContentScene[],
): Promise<ContentPlan> {
  return apiRequest<ContentPlan>(`/api/v1/projects/${projectId}/content-plan`, {
    method: "PATCH",
    body: JSON.stringify({ selected_variant_index: selectedVariantIndex, scenes }),
  });
}

export function confirmContentPlan(projectId: string): Promise<ContentPlan> {
  return apiRequest<ContentPlan>(`/api/v1/projects/${projectId}/content-plan/confirm`, {
    method: "POST",
  });
}

/** 运镜 / 转场 / 商品模式可选项：前端下拉框的唯一数据源 */
export function getContentPlanOptions(projectId: string): Promise<ContentPlanOptions> {
  return apiRequest<ContentPlanOptions>(`/api/v1/projects/${projectId}/content-plan/options`);
}

/** S4-②：逐镜运镜（**允许方案已确认后**改；只影响下一次生成该镜，不触发付费、不改预估）。 */
export function updateSceneCamera(projectId: string, sceneId: string, cameraMove: string): Promise<ContentPlan> {
  return apiRequest<ContentPlan>(`/api/v1/projects/${projectId}/content-plan/scene/${sceneId}/camera`, {
    method: "PATCH",
    body: JSON.stringify({ camera_move: cameraMove }),
  });
}
