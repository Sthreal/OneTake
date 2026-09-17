import type { ImageMetadata, PresignedUpload, ServerAsset } from "../../features/input/types";
import { apiRequest } from "./client";

export async function presignAsset(
  projectId: string,
  metadata: ImageMetadata,
): Promise<PresignedUpload> {
  return apiRequest<PresignedUpload>(`/api/v1/projects/${projectId}/assets/presign`, {
    method: "POST",
    body: JSON.stringify({
      original_filename: metadata.originalFilename,
      mime_type: metadata.mimeType,
      size_bytes: metadata.sizeBytes,
      width: metadata.width,
      height: metadata.height,
      sha256: metadata.sha256,
    }),
  });
}

export async function completeAsset(
  projectId: string,
  assetId: string,
  metadata: ImageMetadata,
): Promise<ServerAsset> {
  return apiRequest<ServerAsset>(
    `/api/v1/projects/${projectId}/assets/${assetId}/complete`,
    {
      method: "POST",
      body: JSON.stringify({
        original_filename: metadata.originalFilename,
        mime_type: metadata.mimeType,
        size_bytes: metadata.sizeBytes,
        width: metadata.width,
        height: metadata.height,
        sha256: metadata.sha256,
      }),
    },
  );
}

export async function listAssets(projectId: string): Promise<ServerAsset[]> {
  return apiRequest<ServerAsset[]>(`/api/v1/projects/${projectId}/assets`);
}