import type { ContentPlan, ContentScene } from "../../features/content-plan/types";
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
