export type ProjectStatus = "draft";

export interface Project {
  project_id: string;
  product_name: string;
  product_note: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export type AssetStatus = "pending" | "ready" | "failed";

export interface ServerAsset {
  asset_id: string;
  project_id: string;
  object_key: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  width: number;
  height: number;
  sha256: string | null;
  status: AssetStatus;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface PresignedUpload {
  asset_id: string;
  object_key: string;
  upload_url: string;
  expires_at: string;
  required_headers: Record<string, string>;
}

export type UploadStatus =
  | "queued"
  | "validating"
  | "invalid"
  | "presigning"
  | "uploading"
  | "completing"
  | "ready"
  | "failed";

export interface ImageMetadata {
  originalFilename: string;
  mimeType: string;
  sizeBytes: number;
  width: number;
  height: number;
  sha256: string;
}

export interface UploadItem {
  localId: string;
  source: "local" | "server";
  file?: File;
  previewUrl?: string;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  width?: number;
  height?: number;
  sha256?: string;
  status: UploadStatus;
  progress: number;
  error?: string;
  errorStage?: "presign" | "upload" | "complete";
  assetId?: string;
  objectKey?: string;
}