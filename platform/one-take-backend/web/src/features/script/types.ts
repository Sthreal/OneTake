export type ScriptStatus = "queued" | "generating" | "ready" | "confirmed" | "failed";

export interface ScriptFacts {
  product_name: string;
  product_note: string | null;
  pain_point: string;
  selling_points: string[];
  usage_scenario: string;
  offer: string | null;
}

export interface ScriptVersion {
  version_id: string;
  project_id: string;
  version_number: number;
  status: ScriptStatus;
  provider: string;
  model: string;
  facts: ScriptFacts;
  hook: string;
  pain_point: string;
  selling_points: string[];
  usage_scenario: string;
  offer: string | null;
  cta: string;
  full_text: string;
  character_count: number;
  estimated_duration_seconds: number;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  confirmed_at: string | null;
  /** 切片 B：pain_point / scene / comparison。旧稿可能没有。 */
  angle?: string | null;
  angle_label?: string | null;
  selected?: boolean;
  generation_batch_id?: string | null;
  /** 切片 C：花钱前审稿闸摘要。没有时前端按 enforce + pending 处理。 */
  review_gate?: ReviewGateSummary;
}

export interface ReviewGateSummary {
  mode: string;
  status: string;
  decision: string | null;
  length_ok: boolean | null;
  error_code: string | null;
}

export interface ScriptState {
  version: ScriptVersion | null;
  /** 同一次 generate 的三套角度。旧响应可以不带。 */
  candidates?: ScriptVersion[];
  selected_version_id?: string | null;
}

export interface ReviewDimension {
  passed: boolean;
  reason: string;
}

export interface RevisedScript {
  hook: string;
  pain_point: string;
  selling_points: string[];
  usage_scenario: string;
  cta: string;
}

/** POST .../script/review 与 .../script/review/apply 的 data。 */
export interface ScriptReviewResult {
  gate_mode: string;
  gate_status: string;
  decision: string | null;
  dimensions: Record<string, ReviewDimension>;
  failed_dimensions: string[];
  revised: RevisedScript | null;
  changed_fields: string[];
  length_ok: boolean;
  length_errors: string[];
  error_code: string | null;
  blocks_paid_video: boolean;
  version: ScriptVersion;
}

export type ScriptReviewAction = "apply" | "ack";

export interface GenerateScriptInput {
  painPoint: string;
  sellingPoints: string[];
  usageScenario: string;
  offer: string | null;
}

export interface EditScriptInput {
  hook: string;
  painPoint: string;
  sellingPoints: string[];
  usageScenario: string;
  cta: string;
}
