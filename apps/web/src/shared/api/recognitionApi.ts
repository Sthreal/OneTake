import type { PipelineState, RecognitionState } from "../../features/recognition/types";
import { apiRequest } from "./client";

export function getPipeline(projectId: string): Promise<PipelineState> {
  return apiRequest<PipelineState>(`/api/v1/projects/${projectId}/pipeline`);
}

export function getRecognition(projectId: string): Promise<RecognitionState> {
  return apiRequest<RecognitionState>(`/api/v1/projects/${projectId}/recognition`);
}

export function requestRecognition(projectId: string): Promise<RecognitionState> {
  return apiRequest<RecognitionState>(`/api/v1/projects/${projectId}/recognition`, { method: "POST" });
}

export function confirmRecognition(
  projectId: string,
  runId: string,
  assetId: string,
  candidateId: string,
): Promise<RecognitionState> {
  return apiRequest<RecognitionState>(
    `/api/v1/projects/${projectId}/recognition/${runId}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ asset_id: assetId, candidate_id: candidateId }),
    },
  );
}
