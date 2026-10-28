export type ContentPlanStatus = "ready" | "confirmed" | "failed";

export interface ContentScene {
  scene_id: string;
  order: number;
  purpose: string;
  script_excerpt: string;
  start_seconds: number;
  end_seconds: number;
  shot_type: string;
  prompt: string;
  overlay_product: boolean;
  product_position: string;
  background_style: string;
  template_id: string;
  subtitle_segment_ids: number[];
  qa_rules: string[];
  // ---- 运动字段（Phase 0 起后端透出；Phase 1/2 用于关键帧与 i2v 运动提示词）----
  visual_goal: string;
  subject_action: string;
  camera_move: string;
  product_mode: string;
  transition: string;
}

export interface ContentVariant {
  variant_id: string;
  name: string;
  style: string;
  scenes: ContentScene[];
}

export interface ContentPlan {
  plan_id: string;
  project_id: string;
  status: ContentPlanStatus;
  provider: string;
  model: string;
  selected_variant_index: number;
  total_duration_seconds: number;
  variants: ContentVariant[];
  error_code: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
}

/** 运镜 / 转场 / 商品模式可选项（GET /content-plan/options） */
export interface ContentPlanOption {
  id: string;
  label: string;
}

export interface ContentPlanOptions {
  camera_moves: ContentPlanOption[];
  transitions: ContentPlanOption[];
  product_modes: ContentPlanOption[];
}