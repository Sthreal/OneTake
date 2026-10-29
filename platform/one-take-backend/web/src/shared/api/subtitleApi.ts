import type { SubtitleSegment, SubtitleState } from "../../features/audio-subtitle/types";
import { apiRequest } from "./client";

export function getSubtitle(projectId: string): Promise<SubtitleState> {
  return apiRequest<SubtitleState>("/api/v1/projects/" + projectId + "/subtitle");
}

/** 配音已就绪但还没有字幕时补一次。配音任务收尾通常会自己开字幕；这里只补缺口。 */
export function requestSubtitle(projectId: string, enabled = true): Promise<SubtitleState> {
  return apiRequest<SubtitleState>("/api/v1/projects/" + projectId + "/subtitle", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
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
