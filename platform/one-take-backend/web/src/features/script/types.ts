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
}

export interface ScriptState {
  version: ScriptVersion | null;
}

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
