import type { ContentQualityReport } from "../../features/content-quality/types";
import { apiRequest } from "./client";
export function getContentQuality(projectId: string): Promise<ContentQualityReport | null> { return apiRequest(`/api/v1/projects/${projectId}/content-quality`); }
