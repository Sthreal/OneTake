import type { MainImageState } from "../../features/main-image/types";
import { apiRequest } from "./client";

export function getMainImage(projectId: string): Promise<MainImageState> {
  return apiRequest<MainImageState>(`/api/v1/projects/${projectId}/main-image`);
}

export function requestMainImage(projectId: string): Promise<MainImageState> {
  return apiRequest<MainImageState>(`/api/v1/projects/${projectId}/main-image`, {
    method: "POST",
  });
}

export function confirmMainImage(projectId: string): Promise<MainImageState> {
  return apiRequest<MainImageState>(`/api/v1/projects/${projectId}/main-image/confirm`, {
    method: "POST",
  });
}
