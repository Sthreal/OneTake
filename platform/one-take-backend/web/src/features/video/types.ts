export type VideoMode = "avatar" | "product";
export type ProductTemplateId = "clean" | "dynamic" | "lifestyle";
export type VideoPlanStatus = "plan_ready" | "video_generating" | "video_ready" | "rendering" | "completed" | "failed";
export type VideoBatchStatus = "idle" | "running" | "stopped" | "done" | "failed" | "interrupted";
export type SegmentStatus = "planned" | "generating" | "awaiting_review" | "accepted" | "failed";
export type SegmentCandidateStatus = "ready" | "accepted" | "rejected" | "failed";

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
  batch_status?: VideoBatchStatus;
  batch_stop_requested?: boolean;
}

export interface SegmentCandidate {
  candidate_id: string;
  segment_id: string;
  order_index: number;
  status: SegmentCandidateStatus;
  provider: string;
  anchor_source: "scene_keyframe" | "previous_tail" | "manual";
  video_url: string | null;
  tail_frame_url: string | null;
  head_frame_url: string | null;
  anchor_candidate_id: string | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  error_code: string | null;
  created_at: string;
}

export interface VideoSegment {
  segment_id: string;
  plan_id: string;
  order_index: number;
  scene_id: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  status: SegmentStatus;
  accepted_candidate_id: string | null;
  last_error: string | null;
  anchor_source: string | null;
  candidates: SegmentCandidate[];
}

export interface VideoSegmentState {
  plan_id: string | null;
  segments: VideoSegment[];
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
