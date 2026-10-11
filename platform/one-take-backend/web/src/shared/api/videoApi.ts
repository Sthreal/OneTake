import type { OutputArtifact, ProductTemplateId, VideoEstimate, VideoMode, VideoSegmentState, VideoState } from "../../features/video/types";
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

export function startVideoBatch(projectId: string): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video/batch`, { method: "POST" });
}

export function stopVideoBatch(projectId: string): Promise<VideoState> {
  return apiRequest<VideoState>(`/api/v1/projects/${projectId}/video/batch/stop`, { method: "POST" });
}
