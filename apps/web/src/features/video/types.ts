export type VideoMode = "avatar" | "product";
export type ProductTemplateId = "clean" | "dynamic" | "lifestyle";
export type VideoPlanStatus = "plan_ready" | "video_generating" | "video_ready" | "rendering" | "completed" | "failed";

export interface VideoPlan {
  plan_id: string;
  project_id: string;
  mode: VideoMode;
  template_id: ProductTemplateId | null;
  status: VideoPlanStatus;
  duration_seconds: number;
  width: number;
  height: number;
  fps: number;
  voice_enabled: boolean;
  subtitle_enabled: boolean;
  provider: string;
  error_code: string | null;
  video_url: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface VideoState {
  plan: VideoPlan | null;
}

export interface OutputArtifact {
  artifact_id: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
  duration_seconds: number;
  download_url: string;
  expires_at: string;
  video_width: number | null;
  video_height: number | null;
  fps: number | null;
  video_codec: string | null;
  audio_codec: string | null;
}

export interface VideoEstimate {
  plan_id: string;
  mode: VideoMode;
  template_id: ProductTemplateId | null;
  duration_seconds: number;
  is_paid: boolean;
  wan_clip_count: number;
  wan_generated_seconds: number;
  qwen_image_edit_calls: number;
  shotstack_renders: number;
  estimated_wan_cost: number;
  estimated_known_cost: number;
  estimated_cost_max: number | null;
  currency: string;
  estimated_minutes: number;
  confirmation_threshold: number;
  requires_confirmation: boolean;
  missing_price_config: string[];
  price_notes: string[];
}
