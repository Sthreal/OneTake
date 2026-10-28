/** 视频形态：档位已于 2026-10-14 收敛为只有 product（数字人 avatar 下线，见档案 M4-04）。
 *  「画面里有人」交给 Prompt 表达，不再是可枚举的档位。 */
export type VideoMode = "product";
/** 生成路径：segmented（逐镜关键帧 → 图生视频）| one_shot（多关键帧一次出片） */
export type GenerationPath = "segmented" | "one_shot";
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
  path: GenerationPath;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  batch_status?: VideoBatchStatus;
  batch_stop_requested?: boolean;
  /** S5：提示词真实感档（老项目 off / 新项目 auto / 导演模式可改） */
  motion_realism?: MotionRealismTier;
  /** S6：接缝模式（pin 钉帧 / tail 续拍 / off 各镜独立） */
  seam_mode?: SeamMode;
  /** S4-④a：方案级合成旋钮（null/undefined = 跟全局配置） */
  caption_style?: string | null;
  bgm_enabled?: boolean | null;
  bgm_gain_db?: number | null;
}

export interface SegmentCandidate {
  candidate_id: string;
  segment_id: string;
  order_index: number;
  status: SegmentCandidateStatus;
  provider: string;
  anchor_source:
    | "scene_keyframe"
    | "previous_tail"
    | "manual"
    | "integrated_keyframe"
    | "previous_tail_kf2v";
  video_url: string | null;
  tail_frame_url: string | null;
  head_frame_url: string | null;
  anchor_candidate_id: string | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  /** 症状式返修：本候选只针对该症状做了一次单变量修改（null 表示常规生成） */
  symptom: RetakeSymptom | null;
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
  /** S4-③：段级接缝覆盖（null = 继承方案级） */
  seam_mode?: SeamMode | null;
  /** S2：本段「当前这条」的成片与首帧缩略图（取自已采纳候选） */
  preview_url?: string | null;
  thumbnail_url?: string | null;
  /** S6：逐镜质量指标（各字段独立可为 null —— 没测就是没测） */
  quality?: SegmentQuality | null;
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
  path: GenerationPath;
  keyframe_calls: number;
  keyframe_images: number;
  i2v_clips: number;
  kf2v_clips: number;
  r2v_calls: number;
  r2v_seconds: number;
  composition: "local" | "shotstack";
}

// ==================== Phase 0 冻结契约：关键帧 / 交付门 / 合规 ====================
// 后端路由已按此结构返回；Phase 1（关键帧生成）、Phase 2（症状返修）、
// Phase 5（交付门确认）上线前，写操作会返回 501 FEATURE_NOT_IMPLEMENTED。

/** 关键帧生成模式：integrated（商品入画，Phase 1）| erase_background（旧空背景路径） */
export type KeyframeMode = "integrated" | "erase_background";
export type KeyframeCandidateStatus = "ready" | "accepted" | "rejected" | "failed";

export interface KeyframeCandidate {
  keyframe_id: string;
  scene_id: string;
  mode: KeyframeMode;
  status: KeyframeCandidateStatus;
  image_url: string | null;
  /** VLM 校验：商品与主图的一致度（0–1），未校验时为 null */
  product_match: number | null;
  /** VLM 校验：包装文字/Logo 是否保持完整 */
  text_intact: boolean | null;
  issues: string[];
  /** 质检不通过时走了哪条兜底（如 pixel_lock）；直接通过为 null */
  fallback: string | null;
  error_code: string | null;
}

export interface Keyframe {
  scene_id: string;
  order: number;
  purpose: string;
  visual_goal: string;
  mode: KeyframeMode;
  /** S4a：关键帧提示词含时序词时的告警（静帧只能画一个瞬间） */
  prompt_warning?: string | null;
  accepted: KeyframeCandidate | null;
  candidates: KeyframeCandidate[];
}

export interface KeyframeState {
  /** 九宫格整图的签名 URL（只有确实用过网格档时才给；1 小时有效） */
  grid_image_url?: string | null;
  /** 整片网格是否被判"不可用"（坏格过半 → 已自动回退单帧） */
  grid_unusable?: boolean;
  project_id: string;
  video_plan_id: string | null;
  content_plan_id: string | null;
  mode: KeyframeMode;
  /** Phase 1 上线前为 false：前端应禁用生成入口而不是静默失败 */
  generation_available: boolean;
  candidates_per_call: number;
  keyframes: Keyframe[];
}

export type GateLevel = "ok" | "warn" | "fail";
export type GateMode = "enforce" | "warn_only";

export interface GateCheck {
  id: string;
  level: GateLevel;
  label: string;
  message: string;
  /** 命中的时间点（秒），用于跳转到成片对应位置 */
  at_seconds: number[];
}

export interface GateReport {
  project_id: string;
  status: GateLevel;
  mode: GateMode;
  checks: GateCheck[];
  contact_sheet_url: string | null;
  acknowledged: string[];
  /** 唯一放行判据：fail 或仍有未确认的 warn 时为 false */
  download_allowed: boolean;
}

export interface BannedWordHit {
  word: string;
  where: "script" | "subtitle";
  index: number;
}

export interface PlatformWarning {
  id: string;
  message: string;
}

export interface ComplianceReport {
  project_id: string;
  /** Phase 5 实现违禁词与平台规则扫描后为 true */
  evaluated: boolean;
  rules_version: string;
  aigc_label_enabled: boolean;
  aigc_label_text: string;
  aigc_label_position: string;
  aigc_label_source: "local" | "model";
  banned_words: BannedWordHit[];
  platform_warnings: PlatformWarning[];
}

/** 症状式定向返修的症状标识（Phase 2 上线） */
export type RetakeSymptom =
  | "product_warped"
  | "text_blurry"
  | "background_dead"
  | "light_wrong"
  | "blurry"
  | "object_drift";

// ---- S4：导演模式消费的字段（后端 S2/S5/S6 已提供）----

export type MotionRealismTier = "auto" | "constraints" | "off";
export type SeamMode = "pin" | "tail" | "off";

export interface SegmentQuality {
  product_match: number | null;
  text_intact: boolean | null;
  keyframe_fallback: string | null;
  duration_delta_seconds: number | null;
  symptom: string | null;
}

export interface RepairAction {
  check_id: string;
  label: string;
  level: GateLevel;
  action: string;
  reason: string;
  target_ref: string | null;
  estimated_cny: number | null;
  execute_endpoint: string | null;
}

export interface RepairPlan {
  plan_id: string | null;
  gate_status: string | null;
  actions: RepairAction[];
}

export interface ModelCapability {
  key: string;
  label: string;
  first_frame: boolean;
  last_frame: boolean;
  reference_images: number;
  reference_video: boolean;
  max_call_seconds: number | null;
  source: string;
}

export interface PreflightCheck {
  code: string;
  level: "ok" | "warn";
  message: string;
}

export interface ComposeOption {
  id: string;
  label: string;
}

export interface ComposeOptions {
  caption_styles: ComposeOption[];
  /** 当前全局默认档（用于显示「跟全局（X）」） */
  default_caption_style: string;
  bgm: { gain_db_min: number; gain_db_max: number; default_enabled: boolean; default_gain_db: number };
}

export interface ModelPreflight {
  model_kind: string;
  capabilities: ModelCapability;
  checks: PreflightCheck[];
}
