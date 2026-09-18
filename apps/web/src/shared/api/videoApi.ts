import type { OutputArtifact, ProductTemplateId, VideoMode, VideoState } from "../../features/video/types";
import { apiRequest } from "./client";

export function getVideo(projectId: string): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video`);
}

export function createVideoPlan(
  projectId: string,
  mode: VideoMode,
  templateId: ProductTemplateId | null,
): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video-plan`, {
    method: "POST",
    body: JSON.stringify({ mode, template_id: templateId }),
  });
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
