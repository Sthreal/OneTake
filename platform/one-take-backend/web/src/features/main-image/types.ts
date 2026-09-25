export type MainImageStatus =
  | "queued"
  | "editing"
  | "matting"
  | "processing"
  | "ready"
  | "confirmed"
  | "failed";

export interface MainImageVersion {
  version_id: string;
  project_id: string;
  source_asset_id: string;
  status: MainImageStatus;
  png_url: string | null;
  jpg_url: string | null;
  png_width: number | null;
  png_height: number | null;
  jpg_width: number | null;
  jpg_height: number | null;
  jpg_size_bytes: number | null;
  product_ratio: number | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  confirmed_at: string | null;
}

export interface MainImageState {
  version: MainImageVersion | null;
}
