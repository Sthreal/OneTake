import type { SubtitleSegment, SubtitleState } from "../../features/audio-subtitle/types";
import { apiRequest } from "./client";

export function getSubtitle(projectId: string): Promise<SubtitleState> {
  return apiRequest<SubtitleState>("/api/v1/projects/" + projectId + "/subtitle");
}

export function updateSubtitle(projectId: string, segments: SubtitleSegment[]): Promise<SubtitleState> {
  return apiRequest<SubtitleState>("/api/v1/projects/" + projectId + "/subtitle", {
    method: "PATCH",
    body: JSON.stringify({ segments: segments.map(({ index, text }) => ({ index, text })) }),
  });
}

export function confirmAudioSubtitle(projectId: string): Promise<unknown> {
  return apiRequest("/api/v1/projects/" + projectId + "/audio-subtitle/confirm", { method: "POST" });
}
